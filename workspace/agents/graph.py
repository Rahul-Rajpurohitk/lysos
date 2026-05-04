"""Multi-agent workbench graph.

A thin state machine that drives the 4 agents (Designer, Critic, Editor,
Strategist). We could use LangGraph for this — and on the production VM we
will — but to keep local dev unblocked we ship a pragmatic async loop with
the same semantics: one transition per call, append events, support pausing,
support branching.

The transitions are:
  start → Strategist (initial pathogen analysis)
        → Designer (propose candidate)
        → Critic (score + identify weakness)
        → Editor (apply transformation) → loops back to Critic
        → Strategist (terminate / branch / red-team)
        → done

Every transition emits one or more `event` dicts to a callback (the SSE
event bus). The frontend consumes these in real time.
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

# Lazy import of tool registry — avoid circular imports
def _registry():
    from tools import registry
    return registry


EventCallback = Callable[[dict], Awaitable[None]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msgs_for_designer(state: WorkbenchState) -> list[dict]:
    """Build Anthropic-style messages for the Designer."""
    msgs: list[dict] = []
    if state.resistome_summary:
        msgs.append({
            "role": "user",
            "content": (
                f"Target: {state.target_pathogen} ({state.resistome_summary.get('full_name', '')})\n\n"
                f"Resistome summary: {state.resistome_summary.get('clinical_context', '')[:500]}\n\n"
                f"First-line therapy: {', '.join(state.resistome_summary.get('first_line_therapy', [])[:3])}\n\n"
                f"Constraints: {[c.model_dump() for c in state.constraints] or 'none'}\n\n"
                f"Iteration {state.iteration} of {state.max_iterations}. "
                f"Propose a novel candidate SMILES + 2-3 sentence rationale."
            ),
        })
    else:
        msgs.append({
            "role": "user",
            "content": (
                f"Target: {state.target_pathogen}. Use `get_pathogen_resistome` first, "
                f"then propose a candidate."
            ),
        })

    if state.candidates:
        latest = state.candidates[-1]
        msgs.append({
            "role": "user",
            "content": (
                f"Previous candidate: {latest.smiles} (composite {latest.scores.composite:.3f}). "
                f"Iterate: propose an improved candidate."
            ),
        })
    return msgs


def _extract_smiles(text: str) -> Optional[str]:
    """Pull SMILES from Designer output, looking for `PROPOSAL: <SMILES>` line."""
    m = re.search(r"PROPOSAL:\s*([^\s]+)", text)
    if m:
        return m.group(1).strip()
    # Fallback: any token that looks like SMILES (very rough)
    for tok in text.split():
        if any(c in tok for c in "()[]") and len(tok) >= 6 and not tok.startswith("http"):
            # Validate via rdkit
            try:
                from rdkit import Chem
                if Chem.MolFromSmiles(tok) is not None:
                    return tok
            except ImportError:
                return tok
    return None


def _extract_critic_block(text: str) -> dict[str, str]:
    """Parse Critic output WEAKNESS/TRANSFORMATION/RATIONALE block."""
    out = {}
    for key in ("WEAKNESS", "TRANSFORMATION", "RATIONALE", "EXPECTED_DELTA", "VERDICT"):
        m = re.search(rf"{key}:\s*([^\n]+)", text)
        if m:
            out[key.lower()] = m.group(1).strip()
    return out


# ---------------------------------------------------------------------------
# Agent nodes
# ---------------------------------------------------------------------------

async def run_strategist_init(
    state: WorkbenchState,
    llm: LLMEndpoint,
    emit: EventCallback,
) -> None:
    """Start of session: have Strategist load the pathogen resistome."""
    reg = _registry()
    tool = reg.get("get_pathogen_resistome")
    if tool is None:
        return
    record = tool.call({"pathogen": state.target_pathogen})
    state.resistome_summary = record.get("result")
    tcr = ToolCallRecord(
        tool="get_pathogen_resistome",
        args={"pathogen": state.target_pathogen},
        result=record.get("result"),
        error=record.get("error"),
        duration_ms=record.get("duration_ms", 0),
        agent="strategist",
    )
    state.tool_calls.append(tcr)
    await emit({"type": "tool_call_result", "agent": "strategist",
                "data": tcr.model_dump(mode="json")})

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


async def run_designer(
    state: WorkbenchState,
    llm: LLMEndpoint,
    emit: EventCallback,
) -> Optional[str]:
    """Designer proposes a candidate SMILES."""
    reg = _registry()
    tools = [reg.get(n).schema() for n in [
        "get_pathogen_resistome", "find_similar_drugs", "find_active_against_mdr",
        "check_resistance_genes", "score_molecule", "predict_complex_structure",
    ] if reg.get(n) is not None]

    msgs = _msgs_for_designer(state)
    resp = await llm.acomplete(messages=msgs, tools=tools, system=DESIGNER_SYSTEM)
    content = resp.get("content", "")

    # Dispatch any tool calls the Designer made
    for tc in resp.get("tool_calls", []):
        t = reg.get(tc["name"])
        if t is None:
            continue
        record = t.call(tc["args"])
        tcr = ToolCallRecord(
            tool=tc["name"], args=tc["args"], result=record.get("result"),
            error=record.get("error"), duration_ms=record.get("duration_ms", 0),
            agent="designer",
        )
        state.tool_calls.append(tcr)
        await emit({"type": "tool_call_result", "agent": "designer",
                    "data": tcr.model_dump(mode="json")})

    state.add_message(AgentMessage(role="designer", content=content))
    await emit({"type": "agent_message", "agent": "designer",
                "data": state.history[-1].model_dump(mode="json")})

    return _extract_smiles(content)


async def run_score_candidate(
    state: WorkbenchState,
    smiles: str,
    parent_id: Optional[str],
    emit: EventCallback,
) -> Candidate:
    """Score a candidate via score_molecule + (optional) predict_complex_structure."""
    reg = _registry()
    cand = Candidate(smiles=smiles, parent_id=parent_id, pathogen=state.target_pathogen)

    score_tool = reg.get("score_molecule")
    if score_tool:
        rec = score_tool.call({"smiles": smiles, "target_pathogen": state.target_pathogen})
        if rec.get("result"):
            for c in rec["result"]["components"]:
                setattr(cand.scores, c["name"], c["value"])
            cand.scores.composite = rec["result"]["composite"]
        tcr = ToolCallRecord(
            tool="score_molecule",
            args={"smiles": smiles, "target_pathogen": state.target_pathogen},
            result=rec.get("result"), error=rec.get("error"),
            duration_ms=rec.get("duration_ms", 0), agent="system",
        )
        state.tool_calls.append(tcr)
        await emit({"type": "tool_call_result", "agent": "system",
                    "data": tcr.model_dump(mode="json")})

    # Find similar drugs (cheap RAG)
    sim_tool = reg.get("find_similar_drugs")
    if sim_tool:
        rec = sim_tool.call({"smiles": smiles, "k": 3})
        if rec.get("result"):
            cand.similar_to = [m["name"] for m in rec["result"].get("matches", [])[:3]]

    state.add_candidate(cand)
    await emit({"type": "candidate_added", "data": cand.model_dump(mode="json")})
    return cand


async def run_critic(
    state: WorkbenchState,
    llm: LLMEndpoint,
    emit: EventCallback,
) -> dict[str, str]:
    """Critic scores + identifies weakness."""
    if not state.candidates:
        return {}
    cand = state.candidates[-1]
    msgs = [{
        "role": "user",
        "content": (
            f"Critique candidate: {cand.smiles}\n\n"
            f"Composite score: {cand.scores.composite:.3f}\n"
            f"Per-component: validity={cand.scores.validity:.2f}, "
            f"alerts={cand.scores.structural_alerts:.2f}, "
            f"mic={cand.scores.predicted_mic:.2f}, "
            f"qed={cand.scores.drug_likeness_qed:.2f}, "
            f"sa={cand.scores.synthesizability:.2f}, "
            f"safety={cand.scores.hemolysis_safety:.2f}, "
            f"novelty={cand.scores.novelty:.2f}, "
            f"emb_novelty={cand.scores.embedding_novelty:.2f}\n\n"
            f"Iteration {state.iteration} of {state.max_iterations}. "
            f"Identify the weakest component and suggest one transformation."
        ),
    }]
    resp = await llm.acomplete(messages=msgs, system=CRITIC_SYSTEM)
    content = resp.get("content", "")

    state.add_message(AgentMessage(role="critic", content=content))
    await emit({"type": "agent_message", "agent": "critic",
                "data": state.history[-1].model_dump(mode="json")})

    block = _extract_critic_block(content)
    return block


async def run_editor(
    state: WorkbenchState,
    op: str,
    emit: EventCallback,
) -> Optional[str]:
    """Apply the Critic-suggested transformation."""
    if not state.candidates:
        return None
    cand = state.candidates[-1]
    reg = _registry()
    tool = reg.get("transform_structure")
    if tool is None:
        return None

    rec = tool.call({"smiles": cand.smiles, "op": op})
    tcr = ToolCallRecord(
        tool="transform_structure",
        args={"smiles": cand.smiles, "op": op},
        result=rec.get("result"), error=rec.get("error"),
        duration_ms=rec.get("duration_ms", 0), agent="editor",
    )
    state.tool_calls.append(tcr)
    await emit({"type": "tool_call_result", "agent": "editor",
                "data": tcr.model_dump(mode="json")})

    products = (rec.get("result") or {}).get("products", [])
    if not products:
        state.add_message(AgentMessage(
            role="editor",
            content=f"Transformation `{op}` produced no products. Designer must propose differently.",
        ))
        await emit({"type": "agent_message", "agent": "editor",
                    "data": state.history[-1].model_dump(mode="json")})
        return None

    new_smiles = products[0]
    state.add_message(AgentMessage(
        role="editor",
        content=f"Applied `{op}`: {cand.smiles} → {new_smiles}",
    ))
    await emit({"type": "agent_message", "agent": "editor",
                "data": state.history[-1].model_dump(mode="json")})
    return new_smiles


async def run_strategist_decide(
    state: WorkbenchState,
    emit: EventCallback,
) -> str:
    """Strategist decides CONTINUE / TERMINATE / BRANCH / RED_TEAM (rules-based)."""
    if not state.candidates:
        decision = "CONTINUE"
        reason = "no candidates yet"
    elif state.iteration >= state.max_iterations:
        decision = "TERMINATE"
        reason = f"max iterations {state.max_iterations} reached"
    elif state.candidates[-1].scores.composite >= 0.80:
        decision = "TERMINATE"
        reason = f"composite {state.candidates[-1].scores.composite:.3f} ≥ 0.80"
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
    return decision


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------

async def run_red_team_loop(
    state: WorkbenchState,
    emit: EventCallback,
    seed_smiles: Optional[str] = None,
) -> WorkbenchState:
    """Red-team workflow: instead of designing new candidates, predict the
    most likely resistance-escape mutations against an EXISTING drug or
    candidate. Run for each known approved drug + the most recent candidate.
    """
    reg = _registry()

    # Pull resistome if not loaded
    if state.resistome_summary is None:
        await run_strategist_init(state, get_llm("mock"), emit)

    # Build the panel of drugs to red-team
    panel: list[dict] = []
    if seed_smiles:
        panel.append({"name": "user-supplied", "smiles": seed_smiles})

    # Pull active known drugs for the pathogen
    active_tool = reg.get("find_active_against_mdr")
    if active_tool:
        rec = active_tool.call({"pathogens": [state.target_pathogen],
                                "status_filter": "approved"})
        for d in (rec.get("result") or {}).get("drugs", [])[:5]:
            panel.append({"name": d["name"], "smiles": ""})  # name-only red-team

    state.add_message(AgentMessage(
        role="strategist",
        content=(
            f"Red-team mode active for {state.target_pathogen}. "
            f"Analyzing {len(panel)} drug(s) for predicted escape mutations."
        ),
    ))
    await emit({"type": "agent_message", "agent": "strategist",
                "data": state.history[-1].model_dump(mode="json")})

    escape_tool = reg.get("predict_resistance_escape")
    for entry in panel:
        if not entry["smiles"]:
            # No SMILES, skip predictive escape for name-only entries
            continue
        rec = escape_tool.call({"smiles": entry["smiles"],
                                "pathogen": state.target_pathogen})
        tcr = ToolCallRecord(
            tool="predict_resistance_escape",
            args={"smiles": entry["smiles"], "pathogen": state.target_pathogen},
            result=rec.get("result"), error=rec.get("error"),
            duration_ms=rec.get("duration_ms", 0), agent="critic",
        )
        state.tool_calls.append(tcr)
        await emit({"type": "tool_call_result", "agent": "critic",
                    "data": tcr.model_dump(mode="json")})

        result = rec.get("result") or {}
        verdict = result.get("red_team_verdict", "unknown")
        muts = result.get("escape_mutations", [])
        msg = (
            f"Red-team report for {entry['name']}: verdict {verdict}. "
            f"{len(muts)} escape pathway(s) identified. "
            + (f"Top: {muts[0]['target']} {muts[0]['mutation']} "
               f"({muts[0]['predicted_fold_shift']}x MIC shift)" if muts else "")
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


async def run_workbench_loop(
    state: WorkbenchState,
    emit: EventCallback,
    llm: Optional[LLMEndpoint] = None,
) -> WorkbenchState:
    """Drive the full Designer → Critic → Editor loop until termination."""
    llm = llm or get_llm()

    # Branch on mode
    if state.mode == "red_team":
        return await run_red_team_loop(state, emit)

    # Design mode (default): full multi-agent loop
    # Phase 1: Strategist initializes — loads resistome
    if state.resistome_summary is None:
        await run_strategist_init(state, llm, emit)

    while not state.terminated and state.iteration < state.max_iterations:
        state.iteration += 1
        await emit({"type": "iteration_start", "data": {"i": state.iteration}})

        # Designer proposes
        smiles = await run_designer(state, llm, emit)
        if not smiles:
            await emit({"type": "error", "data": "Designer produced no SMILES — terminating"})
            break

        # Score the proposal
        parent_id = state.candidates[-2].id if len(state.candidates) >= 2 else None
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

        # Editor applies transformation IF the loop should continue
        op = critic_block.get("transformation")
        if op:
            new_smi = await run_editor(state, op, emit)
            if new_smi:
                # Re-score the edited candidate as the next iteration's seed
                await run_score_candidate(
                    state, new_smi, parent_id=state.candidates[-1].id, emit=emit,
                )

        # Strategist decides whether to continue
        decision = await run_strategist_decide(state, emit)
        if decision != "CONTINUE":
            break

    return state


def build_workbench_graph() -> Callable:
    """Compatibility shim — returns the run_workbench_loop coroutine factory.
    On production we'll swap to a real LangGraph compile here.
    """
    return run_workbench_loop
