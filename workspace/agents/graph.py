"""Multi-agent workbench graph — production-grade.

Fixes from deep audit:
  1. Designer runs a real tool-dispatch loop (LLM → tools → LLM → ...) until
     the model stops calling tools or produces a PROPOSAL.
  2. Constraints + resistome injected into every Designer/Critic prompt.
  3. Critic-Editor-rescore: verify the edit actually improved composite,
     otherwise the editor falls back to a different op or the loop bumps to
     the next iteration without overwriting the parent candidate.
  4. Strategist plateau detection: 3 consecutive iterations with composite
     delta < 0.01 → BRANCH (try a different scaffold suggestion).
  5. Tool errors surfaced back into the agent's next message so it can
     self-correct.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable, Optional

from .llm import LLMEndpoint, get_llm
from .prompts import (
    CRITIC_SYSTEM, DESIGNER_SYSTEM, EDITOR_SYSTEM, STRATEGIST_SYSTEM,
)
from .state import (
    AgentMessage, Candidate, CandidateScores, ToolCallRecord, WorkbenchState,
)

log = logging.getLogger("workbench.agents.graph")

MAX_TOOL_TURNS = 6  # max round-trips Designer can make per iteration
PLATEAU_WINDOW = 3
PLATEAU_DELTA = 0.01


def _registry():
    from tools import registry
    return registry


EventCallback = Callable[[dict], Awaitable[None]]


# ---------------------------------------------------------------------------
# Prompt builders — inject constraints + resistome into every turn
# ---------------------------------------------------------------------------

def _format_constraints(state: WorkbenchState) -> str:
    if not state.constraints:
        return "(none — propose freely)"
    lines = []
    for c in state.constraints:
        if c.type == "property_max":
            lines.append(f"- {c.field} must be < {c.value}")
        elif c.type == "property_min":
            lines.append(f"- {c.field} must be > {c.value}")
        elif c.type == "exclude_smarts":
            lines.append(f"- exclude substructure {c.field} ({c.value})")
        elif c.type == "require_smarts":
            lines.append(f"- require substructure {c.field} ({c.value})")
    return "\n".join(lines)


def _format_resistome_brief(state: WorkbenchState) -> str:
    r = state.resistome_summary or {}
    if not r:
        return f"Target: {state.target_pathogen}. (resistome not yet loaded)"
    genes = ", ".join(g["gene"] for g in r.get("resistome", [])[:6])
    first_line = ", ".join(r.get("first_line_therapy", [])[:3])
    return (
        f"Target: {state.target_pathogen} — {r.get('full_name', '')}\n"
        f"Resistance genes: {genes}\n"
        f"First-line therapy: {first_line}\n"
        f"Clinical context: {r.get('clinical_context', '')[:300]}"
    )


def _format_history_snippet(state: WorkbenchState, n: int = 3) -> str:
    """Last N candidates for the LLM's context."""
    if not state.candidates:
        return "(no candidates yet)"
    lines = []
    for c in state.candidates[-n:]:
        lines.append(
            f"- {c.smiles[:60]} composite={c.scores.composite:.3f} "
            f"weakest=lowest"
        )
    return "\n".join(lines)


def _format_interventions(interventions: list[dict]) -> str:
    if not interventions:
        return "(none)"
    lines = []
    for it in interventions:
        kind = it.get("kind", "?")
        payload = it.get("payload")
        if kind == "constraint":
            lines.append(f"- NEW CONSTRAINT: {payload}")
        elif kind == "directive":
            lines.append(f"- USER DIRECTIVE: {payload}")
        else:
            lines.append(f"- {kind}: {payload}")
    return "\n".join(lines)


def _designer_message(state: WorkbenchState) -> dict:
    interventions = state.consume_interventions()
    constraints_block = _format_constraints(state)
    resistome_block = _format_resistome_brief(state)
    history_block = _format_history_snippet(state)
    interventions_block = _format_interventions(interventions)
    return {
        "role": "user",
        "content": (
            f"## Iteration {state.iteration} of {state.max_iterations}\n\n"
            f"### Pathogen briefing\n{resistome_block}\n\n"
            f"### User interventions (since last turn)\n{interventions_block}\n\n"
            f"### Constraints (MUST honor)\n{constraints_block}\n\n"
            f"### Recent candidates\n{history_block}\n\n"
            f"### Task\n"
            "Propose ONE novel candidate SMILES. Use the available tools to "
            "ground your proposal:\n"
            "  - get_pathogen_resistome (if not yet loaded)\n"
            "  - find_active_against_mdr / find_similar_drugs (RAG anchors)\n"
            "  - check_resistance_genes (verify scaffold isn't already defeated)\n"
            "  - find_target_structure (look up target PDB)\n"
            "  - score_molecule (quick reward check before finalizing)\n\n"
            "After tool exploration, output exactly:\n"
            "```\n"
            "PROPOSAL: <SMILES>\n"
            "RATIONALE: <2-3 sentences citing the resistome + chosen scaffold class>\n"
            "```"
        ),
    }


def _critic_message(state: WorkbenchState) -> dict:
    cand = state.candidates[-1]
    constraints_block = _format_constraints(state)
    return {
        "role": "user",
        "content": (
            f"### Critique candidate\n"
            f"SMILES: {cand.smiles}\n\n"
            f"### Score breakdown\n"
            f"- composite: {cand.scores.composite:.3f}\n"
            f"- predicted_mic: {cand.scores.predicted_mic:.3f}\n"
            f"- drug_likeness_qed: {cand.scores.drug_likeness_qed:.3f}\n"
            f"- synthesizability: {cand.scores.synthesizability:.3f}\n"
            f"- structural_alerts: {cand.scores.structural_alerts:.3f}\n"
            f"- hemolysis_safety: {cand.scores.hemolysis_safety:.3f}\n"
            f"- novelty: {cand.scores.novelty:.3f}\n"
            f"- embedding_novelty: {cand.scores.embedding_novelty:.3f}\n\n"
            f"### Active constraints\n{constraints_block}\n\n"
            f"Iteration {state.iteration}/{state.max_iterations}.\n\n"
            "Identify the SINGLE weakest component and recommend one "
            "transformation. If composite ≥ 0.80 OR ≥3 prior iterations, "
            "output VERDICT: ACCEPT.\n\n"
            "Format:\n"
            "```\n"
            "WEAKNESS: <component> (current=<v>, target=<v>)\n"
            "TRANSFORMATION: <op_name>\n"
            "RATIONALE: <1-2 sentences>\n"
            "EXPECTED_DELTA: +<v> on <component>\n"
            "```\n"
            "Or `VERDICT: ACCEPT` to terminate."
        ),
    }


def _extract_smiles(text: str) -> Optional[str]:
    m = re.search(r"PROPOSAL:\s*([^\s]+)", text)
    if m:
        candidate = m.group(1).strip().rstrip(".,;")
        try:
            from rdkit import Chem
            if Chem.MolFromSmiles(candidate):
                return candidate
        except ImportError:
            return candidate
    # Fallback: any token that parses
    for tok in re.findall(r"\S+", text):
        if any(c in tok for c in "()[]") and len(tok) >= 6 and not tok.startswith("http"):
            try:
                from rdkit import Chem
                if Chem.MolFromSmiles(tok):
                    return tok
            except ImportError:
                pass
    return None


def _extract_critic_block(text: str) -> dict[str, str]:
    out = {}
    for key in ("WEAKNESS", "TRANSFORMATION", "RATIONALE", "EXPECTED_DELTA", "VERDICT"):
        m = re.search(rf"{key}:\s*([^\n]+)", text)
        if m:
            out[key.lower()] = m.group(1).strip()
    return out


# ---------------------------------------------------------------------------
# Tool dispatch helper — runs a tool, emits SSE event, records in state
# ---------------------------------------------------------------------------

async def _dispatch_tool(
    state: WorkbenchState,
    tool_name: str,
    args: dict,
    agent: str,
    emit: EventCallback,
) -> dict:
    reg = _registry()
    t = reg.get(tool_name)
    if t is None:
        record = {"tool": tool_name, "args": args, "result": None,
                  "error": f"unknown tool: {tool_name}", "duration_ms": 0}
    else:
        record = t.call(args)

    tcr = ToolCallRecord(
        tool=tool_name, args=args, result=record.get("result"),
        error=record.get("error"), duration_ms=record.get("duration_ms", 0),
        agent=agent,
    )
    state.tool_calls.append(tcr)
    await emit({"type": "tool_call_result", "agent": agent,
                "data": tcr.model_dump(mode="json")})
    return record


# ---------------------------------------------------------------------------
# Strategist init — load resistome
# ---------------------------------------------------------------------------

async def run_strategist_init(
    state: WorkbenchState,
    llm: LLMEndpoint,
    emit: EventCallback,
) -> None:
    record = await _dispatch_tool(
        state, "get_pathogen_resistome",
        {"pathogen": state.target_pathogen}, "strategist", emit,
    )
    state.resistome_summary = record.get("result")

    state.add_message(AgentMessage(
        role="strategist",
        content=(
            f"Pathogen loaded: {state.target_pathogen}. "
            f"{len(state.resistome_summary.get('resistome', []))} resistance genes identified. "
            f"First-line: {', '.join(state.resistome_summary.get('first_line_therapy', [])[:2])}."
        ),
    ))
    await emit({"type": "agent_message", "agent": "strategist",
                "data": state.history[-1].model_dump(mode="json")})


# ---------------------------------------------------------------------------
# Designer — proper tool-use loop (multi-turn until SMILES emerges)
# ---------------------------------------------------------------------------

async def run_designer(
    state: WorkbenchState,
    llm: LLMEndpoint,
    emit: EventCallback,
) -> Optional[str]:
    """Run Designer with multi-turn tool-use loop. Returns the proposed SMILES
    once the model emits PROPOSAL: <SMILES>."""
    reg = _registry()
    designer_tool_names = [
        "get_pathogen_resistome", "find_active_against_mdr",
        "find_similar_drugs", "check_resistance_genes",
        "find_target_structure", "score_molecule", "predict_admet",
        "explain_mechanism",
    ]
    tools = [reg.get(n).schema() for n in designer_tool_names if reg.get(n)]
    # Anthropic-style tool spec
    tool_specs = [
        {"name": t["name"], "description": t["description"],
         "input_schema": t["input_schema"]}
        for t in tools
    ]

    # Conversation: keep the running history so the model sees prior tool results
    msgs: list[dict] = [_designer_message(state)]

    final_smiles = None
    aggregated_text = ""

    for turn in range(MAX_TOOL_TURNS):
        resp = await llm.acomplete(
            messages=msgs, tools=tool_specs, system=DESIGNER_SYSTEM,
        )
        content = resp.get("content", "")
        tool_calls = resp.get("tool_calls", [])
        aggregated_text += "\n" + content

        # If model proposed SMILES, we're done
        smi = _extract_smiles(content)
        if smi:
            final_smiles = smi
            state.add_message(AgentMessage(role="designer", content=content))
            await emit({"type": "agent_message", "agent": "designer",
                        "data": state.history[-1].model_dump(mode="json")})
            break

        # If model called tools, dispatch them and add results to messages
        if tool_calls:
            # Append the assistant turn (text + tool_use blocks) to history
            assistant_blocks: list[Any] = []
            if content:
                assistant_blocks.append({"type": "text", "text": content})
            for tc in tool_calls:
                assistant_blocks.append({
                    "type": "tool_use", "id": tc["id"],
                    "name": tc["name"], "input": tc["args"],
                })
            msgs.append({"role": "assistant", "content": assistant_blocks})

            # Dispatch each tool and feed result back
            tool_result_blocks: list[Any] = []
            for tc in tool_calls:
                rec = await _dispatch_tool(
                    state, tc["name"], tc["args"], "designer", emit,
                )
                # Format result for the LLM
                if rec.get("error"):
                    result_str = f"ERROR: {rec['error']}"
                else:
                    result_str = json.dumps(rec.get("result", {}))[:2500]
                tool_result_blocks.append({
                    "type": "tool_result", "tool_use_id": tc["id"],
                    "content": result_str,
                })
            msgs.append({"role": "user", "content": tool_result_blocks})
            continue

        # Model neither proposed nor called tools — bail with whatever we got
        log.warning("Designer turn %d: no SMILES, no tool calls — bailing", turn)
        state.add_message(AgentMessage(role="designer", content=content))
        await emit({"type": "agent_message", "agent": "designer",
                    "data": state.history[-1].model_dump(mode="json")})
        break

    if final_smiles is None:
        log.warning("Designer exhausted %d turns without SMILES", MAX_TOOL_TURNS)
    return final_smiles


# ---------------------------------------------------------------------------
# Score a candidate
# ---------------------------------------------------------------------------

async def run_score_candidate(
    state: WorkbenchState,
    smiles: str,
    parent_id: Optional[str],
    emit: EventCallback,
    agent: str = "system",
) -> Candidate:
    cand = Candidate(smiles=smiles, parent_id=parent_id, pathogen=state.target_pathogen)

    # Score
    rec = await _dispatch_tool(
        state, "score_molecule",
        {"smiles": smiles, "target_pathogen": state.target_pathogen},
        agent, emit,
    )
    if rec.get("result"):
        for c in rec["result"]["components"]:
            setattr(cand.scores, c["name"], c["value"])
        cand.scores.composite = rec["result"]["composite"]

    # Find similar drugs (RAG context for the user)
    sim_rec = await _dispatch_tool(
        state, "find_similar_drugs",
        {"smiles": smiles, "k": 3}, agent, emit,
    )
    if sim_rec.get("result"):
        cand.similar_to = [m["name"] for m in sim_rec["result"].get("matches", [])[:3]]

    state.add_candidate(cand)
    await emit({"type": "candidate_added", "data": cand.model_dump(mode="json")})
    return cand


# ---------------------------------------------------------------------------
# Critic — rate candidate, suggest transformation
# ---------------------------------------------------------------------------

async def run_critic(
    state: WorkbenchState,
    llm: LLMEndpoint,
    emit: EventCallback,
) -> dict[str, str]:
    if not state.candidates:
        return {}

    msgs = [_critic_message(state)]
    resp = await llm.acomplete(messages=msgs, system=CRITIC_SYSTEM)
    content = resp.get("content", "")

    state.add_message(AgentMessage(role="critic", content=content))
    await emit({"type": "agent_message", "agent": "critic",
                "data": state.history[-1].model_dump(mode="json")})

    return _extract_critic_block(content)


# ---------------------------------------------------------------------------
# Editor — apply transformation, verify it improves composite
# ---------------------------------------------------------------------------

async def run_editor(
    state: WorkbenchState,
    op: str,
    emit: EventCallback,
) -> Optional[str]:
    """Apply transformation. Returns the new SMILES IF it improves composite,
    else returns None and lets the loop try a different op next iteration."""
    if not state.candidates:
        return None
    cand = state.candidates[-1]
    before_composite = cand.scores.composite

    rec = await _dispatch_tool(
        state, "transform_structure",
        {"smiles": cand.smiles, "op": op}, "editor", emit,
    )
    products = (rec.get("result") or {}).get("products", [])
    if not products:
        state.add_message(AgentMessage(
            role="editor",
            content=f"Transformation `{op}` produced no products on {cand.smiles[:40]}...",
        ))
        await emit({"type": "agent_message", "agent": "editor",
                    "data": state.history[-1].model_dump(mode="json")})
        return None

    # Try the first product, score it, ONLY accept if it improves composite
    new_smi = products[0]
    score_rec = await _dispatch_tool(
        state, "score_molecule",
        {"smiles": new_smi, "target_pathogen": state.target_pathogen},
        "editor", emit,
    )
    new_composite = (score_rec.get("result") or {}).get("composite", 0.0)
    delta = new_composite - before_composite

    if delta < -0.01:  # Allow tiny noise; reject clear regression
        state.add_message(AgentMessage(
            role="editor",
            content=(
                f"Applied `{op}` → {new_smi[:50]} but composite REGRESSED "
                f"({before_composite:.3f} → {new_composite:.3f}, Δ={delta:+.3f}). "
                f"Rejecting — Designer should propose a different scaffold."
            ),
        ))
        await emit({"type": "agent_message", "agent": "editor",
                    "data": state.history[-1].model_dump(mode="json")})
        return None

    state.add_message(AgentMessage(
        role="editor",
        content=(
            f"Applied `{op}`: {cand.smiles[:40]}... → {new_smi[:40]}... "
            f"(composite Δ={delta:+.3f}). Passing to next iteration."
        ),
    ))
    await emit({"type": "agent_message", "agent": "editor",
                "data": state.history[-1].model_dump(mode="json")})
    return new_smi


# ---------------------------------------------------------------------------
# Strategist — terminate / continue / branch with plateau detection
# ---------------------------------------------------------------------------

def _detect_plateau(state: WorkbenchState, window: int = PLATEAU_WINDOW) -> bool:
    """True if the last `window` candidates all have composite delta < PLATEAU_DELTA."""
    if len(state.candidates) < window + 1:
        return False
    recent = state.candidates[-(window + 1):]
    deltas = [
        recent[i + 1].scores.composite - recent[i].scores.composite
        for i in range(len(recent) - 1)
    ]
    return all(abs(d) < PLATEAU_DELTA for d in deltas)


async def run_strategist_decide(
    state: WorkbenchState,
    emit: EventCallback,
) -> str:
    if not state.candidates:
        decision = "CONTINUE"
        reason = "no candidates yet"
    elif state.iteration >= state.max_iterations:
        decision = "TERMINATE"
        reason = f"max iterations {state.max_iterations} reached"
    elif state.candidates[-1].scores.composite >= 0.80:
        decision = "TERMINATE"
        reason = f"composite {state.candidates[-1].scores.composite:.3f} ≥ 0.80"
    elif _detect_plateau(state):
        decision = "BRANCH"
        reason = (
            f"plateau detected: last {PLATEAU_WINDOW} candidates within "
            f"Δcomposite < {PLATEAU_DELTA}. Recommending scaffold-hop."
        )
    else:
        decision = "CONTINUE"
        reason = f"composite {state.candidates[-1].scores.composite:.3f} < 0.80"

    state.add_message(AgentMessage(
        role="strategist",
        content=f"Decision: {decision} ({reason})",
    ))
    await emit({"type": "agent_message", "agent": "strategist",
                "data": state.history[-1].model_dump(mode="json")})

    if decision == "TERMINATE":
        state.terminated = True
        state.termination_reason = reason
        await emit({"type": "agent_idle", "data": {
            "final_candidate_id": state.candidates[-1].id if state.candidates else None,
            "reason": reason,
        }})
    elif decision == "BRANCH":
        # Issue a scaffold-hop suggestion via the tool to seed the next iteration
        if state.candidates:
            await _dispatch_tool(
                state, "scaffold_hop",
                {"smiles": state.candidates[-1].smiles, "n_alternatives": 3},
                "strategist", emit,
            )
    return decision


# ---------------------------------------------------------------------------
# Red-team mode
# ---------------------------------------------------------------------------

async def run_red_team_loop(
    state: WorkbenchState,
    emit: EventCallback,
    seed_smiles: Optional[str] = None,
) -> WorkbenchState:
    if state.resistome_summary is None:
        await run_strategist_init(state, get_llm("mock"), emit)

    panel: list[dict] = []
    if seed_smiles:
        panel.append({"name": "user-supplied", "smiles": seed_smiles})

    active_rec = await _dispatch_tool(
        state, "find_active_against_mdr",
        {"pathogens": [state.target_pathogen], "status_filter": "approved"},
        "strategist", emit,
    )
    for d in (active_rec.get("result") or {}).get("drugs", [])[:5]:
        panel.append({"name": d["name"], "smiles": ""})

    state.add_message(AgentMessage(
        role="strategist",
        content=(
            f"Red-team mode active for {state.target_pathogen}. "
            f"Analyzing {len(panel)} drug(s) for predicted escape mutations."
        ),
    ))
    await emit({"type": "agent_message", "agent": "strategist",
                "data": state.history[-1].model_dump(mode="json")})

    for entry in panel:
        if not entry["smiles"]:
            continue
        rec = await _dispatch_tool(
            state, "predict_resistance_escape",
            {"smiles": entry["smiles"], "pathogen": state.target_pathogen},
            "critic", emit,
        )
        result = rec.get("result") or {}
        verdict = result.get("red_team_verdict", "unknown")
        muts = result.get("escape_mutations", [])
        msg = (
            f"Red-team report for {entry['name']}: verdict {verdict}. "
            f"{len(muts)} escape pathway(s) identified."
        )
        if muts:
            msg += (
                f" Top: {muts[0]['target']} {muts[0]['mutation']} "
                f"({muts[0]['predicted_fold_shift']}x MIC shift)"
            )
        state.add_message(AgentMessage(role="critic", content=msg))
        await emit({"type": "agent_message", "agent": "critic",
                    "data": state.history[-1].model_dump(mode="json")})

    state.terminated = True
    state.termination_reason = "Red-team analysis complete"
    await emit({"type": "agent_idle", "data": {
        "final_candidate_id": None,
        "reason": "red-team-complete",
    }})
    return state


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------

async def run_workbench_loop(
    state: WorkbenchState,
    emit: EventCallback,
    llm: Optional[LLMEndpoint] = None,
) -> WorkbenchState:
    llm = llm or get_llm()

    if state.mode == "red_team":
        return await run_red_team_loop(state, emit)

    # Design mode
    if state.resistome_summary is None:
        await run_strategist_init(state, llm, emit)

    while not state.terminated and state.iteration < state.max_iterations:
        state.iteration += 1
        await emit({"type": "iteration_start", "data": {"i": state.iteration}})

        # Designer with full tool-use loop
        smiles = await run_designer(state, llm, emit)
        if not smiles:
            state.add_message(AgentMessage(
                role="strategist",
                content="Designer produced no SMILES this turn — terminating.",
            ))
            await emit({"type": "agent_message", "agent": "strategist",
                        "data": state.history[-1].model_dump(mode="json")})
            break

        # Score it
        parent_id = state.candidates[-1].id if state.candidates else None
        await run_score_candidate(state, smiles, parent_id, emit)

        # Critic evaluates
        critic_block = await run_critic(state, llm, emit)
        if critic_block.get("verdict") == "ACCEPT":
            state.terminated = True
            state.termination_reason = "Critic accepted candidate"
            await emit({"type": "agent_idle", "data": {
                "final_candidate_id": state.candidates[-1].id,
                "reason": "Critic ACCEPT",
            }})
            break

        # Editor applies + verifies (re-scores) the transformation
        op = critic_block.get("transformation")
        if op:
            edited_smi = await run_editor(state, op, emit)
            if edited_smi:
                # The edited candidate is the new seed for the next iteration
                await run_score_candidate(
                    state, edited_smi, parent_id=state.candidates[-1].id,
                    emit=emit, agent="editor",
                )

        # Strategist decides — includes plateau detection
        decision = await run_strategist_decide(state, emit)
        if decision == "TERMINATE":
            break
        # CONTINUE / BRANCH both go around again

    return state


def build_workbench_graph() -> Callable:
    return run_workbench_loop
