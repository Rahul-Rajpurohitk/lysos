"""Workflow registry + SSE executor — multi-step agentic pipelines.

A workflow is a declarative DAG of steps. Each step:
  - has a unique id
  - runs a single tool from agent.py's tool registry (or custom)
  - takes args computed from the cumulative session state
  - validates its result through a postcondition
  - persists its output back into state for downstream steps

The executor topo-sorts steps, runs them in order, retries transient
failures with exponential backoff, and streams every transition as an
SSE event. The frontend's WorkflowCard renders this as a stepped
Claude-style progress card with collapsible per-step inputs/outputs.

Built-in workflows (registered at module load):
  • discover_and_assess  — design N candidates → score → resistance check → rank
  • harden_candidate     — find weak atoms → harden each → return ranked swaps
  • broad_spectrum_screen — cross-target risk + spectrum classification
  • compare_top_n        — N-candidate side-by-side analysis
  • optimize_for_property — identify weakest axis + propose improvements

Endpoints:
  GET  /api/workflows/list         registry of available workflows
  GET  /api/workflows/{name}/spec  full schema of one workflow
  POST /api/workflows/run          execute (SSE)
  POST /api/workflows/cancel       cancel a running workflow
  GET  /api/agent/suggest-next     guidance — given state, what next?
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, AsyncIterator

import httpx

from . import agent_activity

# Map workflow step tools/ids → which agent role "owns" the step.
# Used by the activity recorder so the Agents container shows the
# right role lighting up for each step (designer drafts seeds,
# critic predicts resistance, editor proposes hardenings, etc.).
_STEP_AGENT: dict[str, str] = {
    "predict_resistance": "critic",
    "score_each":         "designer",
    "score_molecule":     "designer",
    "score_explain":      "designer",
    "harden_atom":        "editor",
    "compare_resistance": "critic",
    "cross_target_risk":  "critic",
    "place_in_pocket":    "designer",
    "__inline__":         "strategist",
    "__loop__":           "editor",
}


def _step_agent(step_tool: str, step_id: str) -> str:
    """Resolve which agent role owns a workflow step. Step ID takes
    precedence over tool when the tool is a generic wrapper
    (__loop__, __inline__) — the loop's actual semantic owner is
    encoded in the step id (e.g. `score_each` → designer, even though
    the wrapper tool is `__loop__`)."""
    sid = (step_id or "").lower()
    # Step-id semantic mapping (most specific)
    if sid in {"seed", "rank", "pick_atoms", "plan"}:
        return "strategist"
    if "harden" in sid:
        return "editor"
    if "resistance" in sid or "escape" in sid or "compare" in sid or "stress" in sid:
        return "critic"
    if "score" in sid or "predict_score" in sid or "rank_each" in sid:
        return "designer"
    if "design" in sid or "propose" in sid or "synth" in sid:
        return "designer"
    # Fallback: tool-based mapping
    if step_tool in _STEP_AGENT:
        return _STEP_AGENT[step_tool]
    return "designer"
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

log = logging.getLogger("api.workflows")
router = APIRouter(prefix="/api", tags=["workflows"])


# ─────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    ok: bool
    data: Any = None
    error: Optional[str] = None
    elapsed_ms: int = 0


@dataclass
class Step:
    id: str
    label: str
    tool: str
    args_fn: Callable[[dict], dict]
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    skip_if: Optional[Callable[[dict], bool]] = None
    validate_fn: Optional[Callable[[Any], Optional[str]]] = None
    on_result: Optional[Callable[[dict, Any], None]] = None
    retry: int = 1  # number of retries on transient failure
    optional: bool = False  # if True, workflow continues on failure
    # When set, the executor calls this async fn instead of HTTP-dispatching
    # `tool`. Used by the design_with_debate workflow's `debate` step which
    # runs a multi-Gemini orchestration in-process.
    inline_fn: Optional[Callable[[dict], Any]] = None


@dataclass
class Workflow:
    name: str
    label: str
    description: str
    inputs: list[dict[str, Any]]  # JSON-Schema-like input descriptors
    steps: list[Step]
    synthesize_fn: Optional[Callable[[dict], str]] = None
    tags: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# Tool dispatcher — reuses agent.py's tool registry
# ─────────────────────────────────────────────────────────────────────

async def _dispatch(tool: str, args: dict, api_base: str) -> StepResult:
    from .agent import _dispatch_tool
    t0 = time.perf_counter()
    try:
        result = await _dispatch_tool(tool, args, api_base)
        return StepResult(ok=True, data=result,
                          elapsed_ms=int((time.perf_counter() - t0) * 1000))
    except HTTPException as exc:
        return StepResult(ok=False, error=f"{exc.status_code} {exc.detail}",
                          elapsed_ms=int((time.perf_counter() - t0) * 1000))
    except Exception as exc:
        return StepResult(ok=False, error=str(exc)[:240],
                          elapsed_ms=int((time.perf_counter() - t0) * 1000))


# ─────────────────────────────────────────────────────────────────────
# Built-in workflows
# ─────────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, Workflow] = {}


def _register(wf: Workflow) -> Workflow:
    _REGISTRY[wf.name] = wf
    return wf


# ── Workflow 1: discover_and_assess ──────────────────────────────────
# Design N candidates, score each, predict resistance against a target,
# rank by composite robustness × score.
# (Note: design tool isn't in the agent registry yet. We use a stub that
#  returns a small set of canonical antibiotic scaffolds for now —
#  swap to /workbench/design when it's wired into the agent registry.)

_SCAFFOLDS = [
    "CC(=O)Nc1ccc(O)cc1",                                  # paracetamol
    "Cn1cnc2c1c(=O)n(C)c(=O)n2C",                          # caffeine
    "OC(=O)Cc1ccccc1Nc1c(Cl)cccc1Cl",                      # diclofenac
    "CC1=CC=C(C=C1)C(C(=O)O)C",                            # ibuprofen-like
    "Oc1ccc2c(c1)oc1ccccc1c2=O",                           # 7-hydroxyflavone
]


def _design_step_args(state: dict) -> dict:
    return {"smiles_list": _SCAFFOLDS[:state.get("n", 3)]}


_register(Workflow(
    name="discover_and_assess",
    label="Discover & assess candidates",
    description=(
        "Generate N candidate scaffolds, score each on the 12-axis reward "
        "stack, predict resistance against the target, and rank them by "
        "composite × robustness."
    ),
    inputs=[
        {"name": "pathogen", "type": "string", "default": "MRSA"},
        {"name": "pdb_id", "type": "string", "default": "1VQQ"},
        {"name": "n", "type": "integer", "default": 3, "min": 1, "max": 5},
    ],
    tags=["design", "score", "resistance"],
    steps=[
        Step(
            id="seed",
            label="Seed candidate set",
            tool="__inline__",
            description="Pull a small set of canonical scaffolds.",
            args_fn=_design_step_args,
            on_result=lambda st, _: st.__setitem__("candidates",
                _SCAFFOLDS[:st.get("n", 3)]),
        ),
        Step(
            id="score_each",
            label="Score every candidate",
            tool="__loop__",
            description="Run /score-explain on each candidate.",
            depends_on=["seed"],
            args_fn=lambda st: {
                "tool": "score_explain",
                "items": [{"smiles": smi, "target_pathogen": st.get("pathogen", "MRSA")}
                          for smi in st["candidates"]],
            },
            on_result=lambda st, r: st.__setitem__("scored", r),
        ),
        Step(
            id="resistance_each",
            label="Resistance check per candidate",
            tool="__loop__",
            description="Run /predict_resistance against the target for each.",
            depends_on=["seed"],
            args_fn=lambda st: {
                "tool": "predict_resistance",
                "items": [{"smiles": smi, "pdb_id": st.get("pdb_id", "1VQQ")}
                          for smi in st["candidates"]],
            },
            on_result=lambda st, r: st.__setitem__("resistance", r),
        ),
        Step(
            id="rank",
            label="Rank candidates",
            tool="__inline__",
            description="Compute composite × robustness + sort.",
            depends_on=["score_each", "resistance_each"],
            args_fn=lambda st: {},
            on_result=lambda st, _: st.__setitem__(
                "ranking", _rank_candidates(st)),
        ),
    ],
    synthesize_fn=lambda st: _synth_discover(st),
))


def _rank_candidates(state: dict) -> list[dict]:
    smis = state.get("candidates", [])
    scored = state.get("scored") or []
    resistance = state.get("resistance") or []
    out = []
    for i, smi in enumerate(smis):
        composite = 0.0
        robustness = 0.0
        try: composite = float(scored[i].get("composite", 0.0))
        except Exception: pass
        try: robustness = float(resistance[i].get("robustness_score", 0.0))
        except Exception: pass
        out.append({
            "smiles": smi,
            "composite": round(composite, 3),
            "robustness": round(robustness, 3),
            "fitness": round(composite * robustness, 3),
        })
    out.sort(key=lambda r: -r["fitness"])
    return out


def _synth_discover(state: dict) -> str:
    ranking = state.get("ranking") or []
    if not ranking:
        return "Discovery completed but ranking is empty."
    top = ranking[0]
    lines = [
        f"Evaluated {len(ranking)} candidates against "
        f"{state.get('pathogen', 'MRSA')} target {state.get('pdb_id', '1VQQ')}.",
        "",
        f"**Winner**: `{top['smiles']}`",
        f"  composite={top['composite']}, robustness={top['robustness']}, "
        f"fitness={top['fitness']}",
        "",
        "**Full ranking**:",
    ]
    for i, r in enumerate(ranking):
        lines.append(f"{i+1}. `{r['smiles']}` — fitness {r['fitness']} "
                     f"(score {r['composite']}, rob {r['robustness']})")
    return "\n".join(lines)


# ── Workflow 2: harden_candidate ─────────────────────────────────────
_register(Workflow(
    name="harden_candidate",
    label="Harden a candidate",
    description=(
        "Predict resistance, identify the most-vulnerable atoms, then "
        "generate hardening swap suggestions (Gemini Pro + curated "
        "playbook) for each weak atom. Returns the best swap per atom."
    ),
    inputs=[
        {"name": "smiles", "type": "string", "required": True},
        {"name": "pdb_id", "type": "string", "default": "1VQQ"},
        {"name": "max_atoms", "type": "integer", "default": 3},
    ],
    tags=["resistance", "harden"],
    steps=[
        Step(
            id="predict",
            label="Predict resistance",
            tool="predict_resistance",
            args_fn=lambda st: {"smiles": st["smiles"], "pdb_id": st.get("pdb_id", "1VQQ")},
            on_result=lambda st, r: st.__setitem__("prediction", r),
        ),
        Step(
            id="pick_atoms",
            label="Pick weak atoms",
            tool="__inline__",
            depends_on=["predict"],
            args_fn=lambda st: {},
            skip_if=lambda st: not (st.get("prediction") or {}).get("vulnerable_atoms"),
            on_result=lambda st, _: st.__setitem__(
                "weak_atoms",
                [v["atom_idx"] for v in (st.get("prediction") or {}).get("vulnerable_atoms", [])][:st.get("max_atoms", 3)],
            ),
        ),
        Step(
            id="harden_each",
            label="Generate hardening suggestions",
            tool="__loop__",
            depends_on=["pick_atoms"],
            skip_if=lambda st: not st.get("weak_atoms"),
            args_fn=lambda st: {
                "tool": "harden_atom",
                "items": [{"smiles": st["smiles"], "pdb_id": st.get("pdb_id", "1VQQ"),
                           "atom_idx": idx}
                          for idx in st.get("weak_atoms", [])],
            },
            on_result=lambda st, r: st.__setitem__("hardenings", r),
        ),
    ],
    synthesize_fn=lambda st: _synth_harden(st),
))


def _synth_harden(state: dict) -> str:
    pred = state.get("prediction") or {}
    rob = pred.get("robustness_score", 0)
    weak = state.get("weak_atoms") or []
    hardenings = state.get("hardenings") or []
    if not weak:
        return f"Robustness {rob:.2f} — no vulnerable atoms above threshold; nothing to harden."
    lines = [
        f"Robustness against {pred.get('target_name')}: **{rob:.2f}**.",
        f"Weak atoms: {weak}",
        "",
        "**Top hardening per atom**:",
    ]
    for i, h in enumerate(hardenings):
        gem = h.get("gemini_suggestions") or []
        pb = h.get("playbook_suggestions") or []
        all_s = gem + pb
        if not all_s:
            continue
        top = all_s[0]
        lines.append(
            f"  • atom {weak[i]} → **{top.get('swap')}** "
            f"(conf {top.get('confidence', 0):.2f}, "
            f"{top.get('source')})  — {top.get('rationale', '')[:120]}"
        )
    return "\n".join(lines)


# ── Workflow 3: broad_spectrum_screen ────────────────────────────────
_register(Workflow(
    name="broad_spectrum_screen",
    label="Broad-spectrum screen",
    description="Run cross-target resistance prediction for one candidate against ALL curated PDBs. Classifies as broad/narrow/fragile.",
    inputs=[
        {"name": "smiles", "type": "string", "required": True},
    ],
    tags=["resistance", "spectrum"],
    steps=[
        Step(
            id="cross_target",
            label="Cross-target risk",
            tool="cross_target_risk",
            args_fn=lambda st: {"smiles": st["smiles"]},
            on_result=lambda st, r: st.__setitem__("spectrum", r),
        ),
    ],
    synthesize_fn=lambda st: _synth_spectrum(st),
))


def _synth_spectrum(state: dict) -> str:
    """Render the broad-spectrum result as plain English with an
    interpretive caveat — many "rob 1.00" results are an artifact of
    an inert ligand making zero contacts with the target, NOT genuine
    robustness. Without this caveat users read the table as "this
    molecule is amazing against everything" which is wrong for tiny
    or generic scaffolds (benzene, methane, etc)."""
    s = state.get("spectrum") or {}
    rows = s.get("rows") or []
    smi = state.get("smiles") or "?"
    n_targets = s.get("n_targets", 0)

    # Count "no-contact" rows — robustness 1.0 + 0 contacts is the
    # tell-tale "ligand doesn't bind" signature, NOT real robustness.
    n_inert = sum(
        1 for r in rows
        if (r.get("robustness_score", 0) >= 0.99
            and r.get("n_residues_with_contacts", 0) == 0)
    )
    n_engaged = n_targets - n_inert

    lines = [
        f"`{smi}` tested against **{n_targets} targets**. "
        f"Avg robustness **{s.get('avg_robustness', 0):.2f}** — "
        f"classified as **{s.get('spectrum', '?')}**.",
    ]
    if n_inert > 0:
        lines.append(
            f"\n⚠ {n_inert}/{n_targets} of those scores are "
            f"`rob=1.00 with 0 contacts` — the ligand isn't actually "
            f"engaging the binding site, so the perfect score is the "
            f"absence of clinical mutations being able to weaken a "
            f"non-existent interaction. Treat as 'no signal', not "
            f"'great drug'."
        )
    lines.append(
        f"\nReal hits ({n_engaged} target{'s' if n_engaged != 1 else ''} "
        f"with actual contacts):"
    )
    engaged_rows = [r for r in rows if r.get("n_residues_with_contacts", 0) > 0]
    for r in engaged_rows or rows:
        lines.append(
            f"  • {r.get('pdb_id')} ({r.get('pathogen')}): "
            f"rob {r.get('robustness_score', 0):.2f}, "
            f"esc {r.get('n_escape_vectors', 0)}, "
            f"{r.get('n_residues_with_contacts', 0)} contacts"
        )
    return "\n".join(lines)


# ── Workflow 4: compare_top_n ────────────────────────────────────────
_register(Workflow(
    name="compare_top_n",
    label="Compare candidates",
    description="Side-by-side resistance comparison of N candidates against the same target.",
    inputs=[
        {"name": "smiles_list", "type": "array", "required": True},
        {"name": "pdb_id", "type": "string", "default": "1VQQ"},
    ],
    tags=["compare"],
    steps=[
        Step(
            id="compare",
            label="Compare resistance profiles",
            tool="compare_resistance",
            args_fn=lambda st: {
                "smiles_list": st["smiles_list"],
                "pdb_id": st.get("pdb_id", "1VQQ"),
            },
            on_result=lambda st, r: st.__setitem__("comparison", r),
        ),
    ],
    synthesize_fn=lambda st: _synth_compare(st),
))


def _synth_compare(state: dict) -> str:
    c = state.get("comparison") or {}
    rows = c.get("rows") or []
    best_idx = c.get("best_idx")
    out = [f"Compared {c.get('n', 0)} candidates against {c.get('pdb_id')}."]
    for i, r in enumerate(rows):
        marker = " ★" if i == best_idx else ""
        out.append(
            f"  {i+1}. {r.get('label')}{marker} — rob {r.get('robustness_score', 0):.2f}, "
            f"esc {r.get('n_escape_vectors', 0)}"
        )
    common = c.get("common_weak_residues") or []
    if common:
        out.append("")
        out.append(f"Common weak residues across the set: "
                   f"{', '.join(str(r['position']) for r in common[:5])}")
    return "\n".join(out)


# ── Workflow 5: optimize_for_property ────────────────────────────────
_register(Workflow(
    name="optimize_for_property",
    label="Identify weakest axis",
    description="Score the candidate, identify the weakest axis with the highest improvement Δ, and surface concrete medchem suggestions.",
    inputs=[
        {"name": "smiles", "type": "string", "required": True},
        {"name": "pathogen", "type": "string", "default": "MRSA"},
    ],
    tags=["score", "optimize"],
    steps=[
        Step(
            id="score",
            label="Deep score with reasoning",
            tool="score_explain",
            args_fn=lambda st: {"smiles": st["smiles"],
                                "target_pathogen": st.get("pathogen", "MRSA")},
            on_result=lambda st, r: st.__setitem__("score", r),
        ),
    ],
    synthesize_fn=lambda st: _synth_optimize(st),
))


def _synth_optimize(state: dict) -> str:
    s = state.get("score") or {}
    weakest = s.get("weakest")
    reasoning = (s.get("axis_reasoning") or {}).get(weakest) or {}
    rdkit = s.get("rdkit_properties") or {}
    return (
        f"Composite: **{s.get('composite', 0):.3f}** "
        f"(MW {rdkit.get('mw')}, LogP {rdkit.get('logp')}).\n\n"
        f"**Weakest axis**: `{weakest}`\n"
        f"  • {reasoning.get('explanation', '')}\n"
        f"  • Improve: {reasoning.get('improvement', '')}\n"
        f"  • Predicted Δ: +{reasoning.get('predicted_delta', 0):.2f}"
    )


# ── Workflow 6: design_with_debate ───────────────────────────────────
# REAL multi-agent debate. Each role is a separate Gemini Pro call with
# a role-specific system prompt. Designer proposes → Critic challenges
# → Editor refines → repeat for N rounds → Strategist picks winner.
# This is the workflow that LIGHTS UP all four roles in the Agents tab
# and produces a visible debate in the chat.

async def _debate_step(state: dict, session_id_in_state: bool = True) -> dict:
    """The single 'debate' step — runs the full N-round debate, scores
    the winner, and emits structured candidates for the UI."""
    from . import debate as _debate
    sid = state.get("_session_id") or ""
    pathogen = state.get("pathogen") or "MRSA"
    target_pdb = state.get("pdb_id") or "1VQQ"
    criteria = state.get("criteria") or state.get("objective") or ""
    n_rounds = int(state.get("n_rounds") or 2)
    n_proposals = int(state.get("n_proposals") or 3)
    outcome = await _debate.run_debate(
        sid, pathogen, target_pdb,
        criteria=criteria, n_rounds=n_rounds, n_proposals=n_proposals,
    )
    state["debate"] = {
        "winner": outcome.winner,
        "runner_up": outcome.runner_up,
        "next_action": outcome.next_action,
        "justification": outcome.justification,
        "rounds": outcome.rounds_log,
        "tokens_in": outcome.total_tokens_in,
        "tokens_out": outcome.total_tokens_out,
        "cost_usd": outcome.total_cost_usd,
        "elapsed_ms": outcome.elapsed_ms,
        "proposals": outcome.proposals,
        "refined": outcome.refined,
    }
    state["candidates"] = [
        r.get("refined_smiles") or r.get("original_smiles")
        for r in outcome.refined if r.get("refined_smiles") or r.get("original_smiles")
    ]
    return state["debate"]


_register(Workflow(
    name="design_with_debate",
    label="Design — multi-agent debate",
    description=(
        "Designer drafts → Critic challenges → Editor refines (×N rounds) → "
        "Strategist picks winner. Real Gemini Pro calls per role. Visible "
        "debate in chat + Agents tab lights up all four specialists."
    ),
    inputs=[
        {"name": "pathogen", "type": "string", "default": "MRSA"},
        {"name": "pdb_id", "type": "string", "default": "1VQQ"},
        {"name": "criteria", "type": "string", "default": ""},
        {"name": "n_rounds", "type": "integer", "default": 2, "min": 1, "max": 4},
        {"name": "n_proposals", "type": "integer", "default": 3, "min": 2, "max": 4},
    ],
    tags=["design", "debate", "multi-agent", "gemini"],
    steps=[
        Step(
            id="debate",
            label="Multi-agent debate (Designer / Critic / Editor / Strategist)",
            tool="__inline__",
            args_fn=lambda st: {},
            on_result=lambda st, _: None,
            inline_fn=_debate_step,
        ),
        Step(
            id="score_winner",
            label="Score the winner (12-axis reward stack)",
            tool="score_explain",
            depends_on=["debate"],
            args_fn=lambda st: {
                "smiles": (st.get("debate") or {}).get("winner") or "c1ccccc1",
                "target_pathogen": st.get("pathogen", "MRSA"),
            },
            on_result=lambda st, r: st.__setitem__("winner_score", r),
        ),
    ],
    synthesize_fn=lambda st: _synth_debate(st),
))


def _synth_debate(state: dict) -> str:
    d = state.get("debate") or {}
    s = state.get("winner_score") or {}
    if not d.get("winner"):
        return "Debate inconclusive — no winner emerged. Check the per-role messages above."
    rounds = d.get("rounds") or []
    n_proposals_total = sum(r.get("n_proposals", 0) for r in rounds if r.get("n_proposals"))
    composite = s.get("composite")
    composite_str = f"{composite:.3f}" if isinstance(composite, (int, float)) else "?"
    cost = d.get("cost_usd", 0)
    return (
        f"## Multi-agent debate complete\n\n"
        f"**{len(rounds)} rounds** · {n_proposals_total} proposals explored · "
        f"${cost:.4f} spent ({d.get('tokens_in', 0):,}→{d.get('tokens_out', 0):,} tokens) · "
        f"{(d.get('elapsed_ms') or 0) / 1000:.1f}s\n\n"
        f"**Winner**: `{d.get('winner')}` — composite **{composite_str}**\n"
        f"**Runner-up**: `{d.get('runner_up')}`\n"
        f"**Strategist's verdict**: {d.get('justification')}\n"
        f"**Next action recommended**: `{d.get('next_action')}`"
    )


# ─────────────────────────────────────────────────────────────────────
# Executor
# ─────────────────────────────────────────────────────────────────────

_RUNNING: dict[str, asyncio.Event] = {}


def _topo_sort(steps: list[Step]) -> list[Step]:
    by_id = {s.id: s for s in steps}
    seen: set[str] = set()
    out: list[Step] = []

    def visit(s: Step):
        if s.id in seen:
            return
        for dep in s.depends_on:
            if dep in by_id:
                visit(by_id[dep])
        seen.add(s.id)
        out.append(s)

    for s in steps:
        visit(s)
    return out


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _run_loop_step(
    tool_name: str, items: list[dict], api_base: str,
    on_progress: Callable[[int, int, dict], Awaitable[None]],
) -> list[Any]:
    """Execute a tool over a list of inputs. Sequential (parallel would
    blow Gemini rate limits). Reports progress per-item."""
    out: list[Any] = []
    for i, args in enumerate(items):
        await on_progress(i, len(items), args)
        res = await _dispatch(tool_name, args, api_base)
        out.append(res.data if res.ok else {"_error": res.error})
    return out


async def _execute_workflow(
    wf: Workflow, inputs: dict, run_id: str, api_base: str,
    session_id: str = "",
) -> AsyncIterator[str]:
    """Generator yielding SSE lines for a workflow run."""
    cancel_event = asyncio.Event()
    _RUNNING[run_id] = cancel_event

    state: dict = dict(inputs)
    # Seed session_id into state so inline_fn (e.g. the multi-agent
    # debate runner) can record into agent_activity + session_memory
    # under the right session.
    if session_id:
        state["_session_id"] = session_id
    started = time.time()
    yield _sse({
        "event": "workflow.start",
        "run_id": run_id,
        "name": wf.name,
        "label": wf.label,
        "inputs": inputs,
        "ts": started,
    })
    # Record the workflow kick-off as a strategist action — the
    # strategist is the role that decides which workflow to run.
    if session_id:
        agent_activity.record(
            session_id, "strategist", "workflow_start",
            message=f"{wf.label} ({wf.name})",
            references={"inputs": inputs, "run_id": run_id},
        )

    try:
        steps = _topo_sort(wf.steps)
        # Emit the plan up-front so the UI can render the empty step list.
        yield _sse({
            "event": "workflow.plan",
            "run_id": run_id,
            "steps": [
                {"id": s.id, "label": s.label, "tool": s.tool,
                 "depends_on": s.depends_on, "description": s.description}
                for s in steps
            ],
        })

        for step in steps:
            if cancel_event.is_set():
                yield _sse({"event": "workflow.cancelled", "run_id": run_id})
                return

            if step.skip_if and step.skip_if(state):
                yield _sse({
                    "event": "step.skipped", "run_id": run_id, "step_id": step.id,
                })
                continue

            # Record step.start so the Agents container shows the
            # right role flipping to "running".
            if session_id:
                agent_activity.record(
                    session_id, _step_agent(step.tool, step.id), "step_start",
                    message=f"{step.label}",
                    references={"step_id": step.id, "tool": step.tool, "wf": wf.name},
                    status="running",
                )
            yield _sse({
                "event": "step.start", "run_id": run_id, "step_id": step.id,
                "label": step.label, "tool": step.tool,
            })

            try:
                args = step.args_fn(state) or {}
            except Exception as exc:
                yield _sse({
                    "event": "step.error", "run_id": run_id, "step_id": step.id,
                    "error": f"args_fn raised: {exc}",
                })
                if not step.optional:
                    yield _sse({"event": "workflow.error", "run_id": run_id,
                                "error": f"step {step.id} args failed"})
                    return
                continue

            # Dispatch — three modes: __inline__, __loop__, real tool.
            t0 = time.perf_counter()
            ok, data, err = False, None, None

            if step.tool == "__inline__":
                # Inline step — if an inline_fn is provided, call it
                # asynchronously and use its return value as `data`.
                # Otherwise the on_result callback does all the work
                # using `args` as data.
                if step.inline_fn is not None:
                    try:
                        rv = step.inline_fn(state)
                        if asyncio.iscoroutine(rv):
                            rv = await rv
                        ok, data, err = True, rv, None
                    except Exception as exc:  # noqa: BLE001
                        ok, data, err = False, None, f"inline_fn raised: {exc}"
                else:
                    ok, data, err = True, args, None

            elif step.tool == "__loop__":
                items = args.get("items") or []
                tool = args.get("tool") or ""
                async def on_prog(i: int, total: int, item_args: dict):
                    yield_payload = {
                        "event": "step.progress", "run_id": run_id,
                        "step_id": step.id, "i": i, "n": total,
                        "tool": tool, "args": item_args,
                    }
                    # Buffered through outer generator via shared queue.
                    queue.append(_sse(yield_payload))
                queue: list[str] = []
                results: list[Any] = []
                for i, item_args in enumerate(items):
                    yield _sse({
                        "event": "step.progress", "run_id": run_id,
                        "step_id": step.id, "i": i, "n": len(items),
                        "tool": tool, "args": item_args,
                    })
                    if cancel_event.is_set():
                        yield _sse({"event": "workflow.cancelled", "run_id": run_id})
                        return
                    res = await _dispatch(tool, item_args, api_base)
                    results.append(res.data if res.ok else {"_error": res.error})
                ok, data, err = True, results, None

            else:
                # Single-tool step with retry.
                attempts = step.retry + 1
                for attempt in range(attempts):
                    res = await _dispatch(step.tool, args, api_base)
                    if res.ok:
                        ok, data, err = True, res.data, None
                        break
                    err = res.error
                    if attempt < attempts - 1:
                        yield _sse({
                            "event": "step.retry", "run_id": run_id,
                            "step_id": step.id, "attempt": attempt + 1,
                            "error": err,
                        })
                        await asyncio.sleep(0.5 * (attempt + 1))

            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            if not ok:
                yield _sse({
                    "event": "step.error", "run_id": run_id, "step_id": step.id,
                    "error": err, "elapsed_ms": elapsed_ms,
                })
                if not step.optional:
                    yield _sse({"event": "workflow.error", "run_id": run_id,
                                "error": f"step {step.id} failed: {err}"})
                    return
                continue

            # Validate
            if step.validate_fn:
                vmsg = step.validate_fn(data)
                if vmsg:
                    yield _sse({
                        "event": "step.error", "run_id": run_id, "step_id": step.id,
                        "error": f"validation: {vmsg}",
                    })
                    if not step.optional:
                        return
                    continue

            # Persist to state
            if step.on_result:
                try:
                    step.on_result(state, data)
                except Exception as exc:
                    yield _sse({
                        "event": "step.error", "run_id": run_id, "step_id": step.id,
                        "error": f"on_result raised: {exc}",
                    })

            # Record step.done with the actual elapsed_ms so KPIs
            # populate (avg latency per role).
            if session_id:
                agent_activity.record(
                    session_id, _step_agent(step.tool, step.id), "step_done",
                    message=f"{step.label} · {elapsed_ms}ms",
                    references={"step_id": step.id, "tool": step.tool},
                    elapsed_ms=elapsed_ms,
                    confidence=0.9,
                )
            yield _sse({
                "event": "step.done", "run_id": run_id, "step_id": step.id,
                "elapsed_ms": elapsed_ms, "result": _truncate(data),
            })

        # Final synthesis
        synth = ""
        if wf.synthesize_fn:
            try:
                synth = wf.synthesize_fn(state) or ""
            except Exception as exc:
                synth = f"(synthesis failed: {exc})"

        # Preserve KEY structured fields even when the full state would
        # be truncated — UI needs `ranking` as a real array (not a string
        # blob) to render Apply buttons.
        truncated_state = _truncate(state)
        if isinstance(truncated_state, dict) and truncated_state.get("_truncated"):
            for keep in ("ranking", "candidates", "scored", "harden_results", "debate", "winner_score"):
                if keep in state:
                    truncated_state[keep] = state[keep]

        # Auto-promote a champion candidate from the workflow's winner
        # if applicable. Best effort — never blocks the workflow.
        try:
            from . import champions as _champ
            winner_smi = None
            winner_composite = None
            winner_robustness = None
            winner_scores: dict = {}
            pathogen = state.get("pathogen") or "MRSA"
            if state.get("ranking"):
                top = state["ranking"][0]
                winner_smi = top.get("smiles")
                winner_composite = top.get("composite")
                winner_robustness = top.get("robustness")
            elif state.get("debate", {}).get("winner"):
                winner_smi = state["debate"]["winner"]
                ws = state.get("winner_score") or {}
                winner_composite = ws.get("composite")
                if isinstance(ws.get("components"), list):
                    for c in ws["components"]:
                        if isinstance(c, dict) and c.get("name"):
                            winner_scores[c["name"]] = c.get("value")
            if winner_smi:
                promo = _champ.propose(
                    pathogen, winner_smi,
                    composite=winner_composite,
                    robustness=winner_robustness,
                    scores=winner_scores,
                    session_id=session_id,
                    rationale=f"auto-promoted from {wf.name} workflow",
                )
                state["champion_promotion"] = promo
                if isinstance(truncated_state, dict):
                    truncated_state["champion_promotion"] = promo
        except Exception as exc:  # noqa: BLE001
            log.debug("champion auto-promote failed: %s", exc)

        yield _sse({
            "event": "workflow.done", "run_id": run_id,
            "name": wf.name, "elapsed_ms": int((time.time() - started) * 1000),
            "summary": synth, "state": truncated_state,
        })

    finally:
        _RUNNING.pop(run_id, None)


def _truncate(obj: Any, max_chars: int = 8000) -> Any:
    try:
        s = json.dumps(obj)
        if len(s) <= max_chars:
            return obj
        return {"_truncated": True, "_len": len(s), "preview": s[:max_chars]}
    except Exception:
        return {"_unserializable": True}


# ─────────────────────────────────────────────────────────────────────
# HTTP routes
# ─────────────────────────────────────────────────────────────────────

@router.get("/workflows/list")
async def list_workflows() -> dict:
    return {
        "workflows": [
            {
                "name": wf.name, "label": wf.label,
                "description": wf.description, "tags": wf.tags,
                "n_steps": len(wf.steps),
                "inputs": wf.inputs,
            }
            for wf in _REGISTRY.values()
        ],
    }


@router.get("/workflows/{name}/spec")
async def workflow_spec(name: str) -> dict:
    wf = _REGISTRY.get(name)
    if not wf:
        raise HTTPException(404, f"unknown workflow: {name}")
    return {
        "name": wf.name, "label": wf.label, "description": wf.description,
        "inputs": wf.inputs, "tags": wf.tags,
        "steps": [
            {"id": s.id, "label": s.label, "tool": s.tool,
             "description": s.description, "depends_on": s.depends_on,
             "optional": s.optional}
            for s in wf.steps
        ],
    }


class WorkflowRunRequest(BaseModel):
    name: str
    inputs: dict[str, Any] = {}
    session_id: Optional[str] = None


@router.post("/workflows/run")
async def run_workflow(req: WorkflowRunRequest) -> StreamingResponse:
    wf = _REGISTRY.get(req.name)
    if not wf:
        raise HTTPException(404, f"unknown workflow: {req.name}")
    api_base = os.getenv("LYSOS_INTERNAL_API_BASE", "http://127.0.0.1:7860")
    run_id = f"wfrun-{uuid.uuid4().hex[:10]}"
    return StreamingResponse(
        _execute_workflow(wf, req.inputs, run_id, api_base,
                          session_id=req.session_id or ""),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform",
                 "X-Accel-Buffering": "no"},
    )


class CancelRequest(BaseModel):
    run_id: str


@router.post("/workflows/cancel")
async def cancel_workflow(req: CancelRequest) -> dict:
    ev = _RUNNING.get(req.run_id)
    if ev is None:
        return {"ok": False, "reason": "not running"}
    ev.set()
    return {"ok": True, "run_id": req.run_id}


# ─────────────────────────────────────────────────────────────────────
# Guidance — given current session state, suggest next steps
# ─────────────────────────────────────────────────────────────────────

@router.get("/agent/suggest-next")
async def suggest_next(
    smiles: Optional[str] = None,
    pdb_id: Optional[str] = None,
    pathogen: Optional[str] = None,
    has_score: bool = False,
    has_resistance: bool = False,
    has_harden: bool = False,
    n_candidates: int = 0,
) -> dict:
    """Return ranked next-step suggestions given the user's current state.

    The chat panel renders these as quick-action chips ("Score this candidate",
    "Predict resistance", "Compare with another"). Each suggestion has:
      - label (button text)
      - workflow (name to invoke)
      - inputs (preset)
      - reason (one-line explanation of why it's relevant now)
      - priority (1-10, higher = more relevant)
    """
    suggestions: list[dict] = []

    if not smiles:
        suggestions.append({
            "label": "Discover candidates for " + (pathogen or "MRSA"),
            "workflow": "discover_and_assess",
            "inputs": {"pathogen": pathogen or "MRSA",
                       "pdb_id": pdb_id or "1VQQ", "n": 3},
            "reason": "No active candidate — start by generating and assessing a small set.",
            "priority": 9,
        })
        return {"suggestions": suggestions}

    if not has_score:
        suggestions.append({
            "label": "Deep-score this candidate",
            "workflow": "optimize_for_property",
            "inputs": {"smiles": smiles, "pathogen": pathogen or "MRSA"},
            "reason": "Run /score-explain to get RDKit properties + per-axis Gemini reasoning.",
            "priority": 9,
        })

    if pdb_id and not has_resistance:
        suggestions.append({
            "label": "Check resistance against " + pdb_id,
            "workflow": "harden_candidate",
            "inputs": {"smiles": smiles, "pdb_id": pdb_id, "max_atoms": 3},
            "reason": "Predict the escape vectors and produce hardening swaps for the worst atoms.",
            "priority": 8,
        })

    if has_resistance and not has_harden:
        suggestions.append({
            "label": "Generate hardening swaps",
            "workflow": "harden_candidate",
            "inputs": {"smiles": smiles, "pdb_id": pdb_id or "1VQQ", "max_atoms": 3},
            "reason": "Resistance predicted but no swaps yet — get bespoke medchem suggestions.",
            "priority": 9,
        })

    suggestions.append({
        "label": "Broad-spectrum screen",
        "workflow": "broad_spectrum_screen",
        "inputs": {"smiles": smiles},
        "reason": "Test against ALL curated targets to classify spectrum.",
        "priority": 6 if has_resistance else 7,
    })

    if n_candidates >= 2:
        suggestions.append({
            "label": f"Compare your {n_candidates} candidates",
            "workflow": "compare_top_n",
            "inputs": {"smiles_list": [], "pdb_id": pdb_id or "1VQQ"},
            "reason": "Side-by-side robustness with shared weak-residue summary.",
            "priority": 7,
        })

    suggestions.sort(key=lambda s: -s["priority"])
    return {"suggestions": suggestions}
