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


# ── Per-step Gemini narration ───────────────────────────────────────
# Each step's narrator_role triggers a real Gemini Pro call after the
# tool runs. Replaces frontend template strings with genuine LLM
# reasoning so the chat reads like agents thinking, not data fetched.
_NARRATOR_PROMPTS = {
    "critic": (
        "You are the **Critic** in a multi-agent antibiotic-design loop. "
        "A tool just returned data. Write 2-3 sentences of ACTUAL "
        "reasoning over that data — call out the strongest signal, the "
        "weakest signal, and what the team should do next. Be opinionated; "
        "DON'T just restate the numbers. Use plain prose, no headings, "
        "no bullet lists. Bold key terms with **double-asterisks** but "
        "NEVER nest them inside another bolded phrase.\n\n"
        "STRICT FACT RULES — never violate:\n"
        "  • If `vulnerable_atoms` is non-empty, those ARE escape vectors. "
        "NEVER say 'zero escape vectors' or 'no vulnerabilities' just "
        "because `n_escape_vectors` (a threshold counter) is 0. Count the "
        "items in `vulnerable_atoms` and reference them by `atom_idx`.\n"
        "  • Cite each atom by its actual index from the data (atom #1, "
        "atom #4, etc.), the actual mutation (e.g. K247T), and the actual "
        "escape score. No invented numbers, no rounding away non-zero scores.\n"
        "  • If the data shows weak atoms, say 'these atoms are worth "
        "hardening' — never tell the user the molecule is safe."
    ),
    "strategist": (
        "You are the **Strategist** deciding the next move. The tool's "
        "output is below. In 2 sentences, name the candidate's strongest "
        "asset, then commit to ONE next step (harden? branch? terminate? "
        "score?) with a one-line justification. No bullets, no headings."
    ),
    "editor": (
        "You are the **Editor** — you decide which structural edit to "
        "apply.\n\n"
        "STRICT INPUT RULES:\n"
        "  • The tool's result contains a LIST of proposed swaps in each "
        "atom's `gemini_suggestions` or `suggestions` field. You MUST "
        "pick ONE swap from that list — do NOT invent a new swap name, "
        "do NOT reference a mutation site the data doesn't mention.\n"
        "  • Quote the swap's exact `swap` field verbatim. Reference its "
        "`mechanism` and `predicted_robustness_delta` from the data.\n"
        "  • If the data references mutations K247T, S365A, etc., use "
        "those exact codes — don't invent K382Q or any other code that "
        "isn't in the input.\n\n"
        "Write 2-3 sentences: which swap, why (mechanism + Δ), and a "
        "final 'I'd apply <exact swap name>' line. No bullets, no "
        "headings."
    ),
    "designer": (
        "You are the **Designer** reviewing this step's output. In 2-3 "
        "sentences explain what the result means for the next scaffold "
        "iteration. Plain prose, no bullets."
    ),
}


async def _gemini_narrate(role: str, step_label: str, result: Any) -> Optional[str]:
    """Call Gemini Pro to write a per-step agent commentary. Returns
    plain markdown text the frontend renders directly. Returns None on
    any failure — the chat falls back to the structured summary."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    sys_prompt = _NARRATOR_PROMPTS.get(role) or _NARRATOR_PROMPTS["designer"]
    # Trim the result to the most informative subset so we don't blow
    # context on full RDKit dumps.
    try:
        compact = json.dumps(_compact_for_narrator(result), ensure_ascii=False)
    except Exception:
        compact = str(result)[:2000]
    if len(compact) > 4000:
        compact = compact[:4000] + "...(truncated)"
    model = os.getenv("LYSOS_NARRATOR_MODEL", "gemini-2.5-pro")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    user_text = (
        f"Step that just ran: **{step_label}**.\n\n"
        f"Tool result:\n```json\n{compact}\n```\n\n"
        f"Write your {role} commentary now (2-3 sentences max)."
    )
    payload = {
        "system_instruction": {"parts": [{"text": sys_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "maxOutputTokens": 512,
            "temperature": 0.4,
            "thinkingConfig": {"thinkingBudget": 256, "includeThoughts": False},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.post(
                url, json=payload,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            )
        if r.status_code != 200:
            return None
        body = r.json()
        cands = body.get("candidates") or []
        if not cands:
            return None
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join((p.get("text") or "") for p in parts).strip()
        return text or None
    except Exception:
        return None


def _extract_applied_smiles(narration: str, result: Any) -> Optional[dict]:
    """Parse the editor's narration for 'I'd apply <swap name>' and
    find the matching suggestion in the harden_each result. Returns
    {smiles, swap, rationale} or None.

    Two-pass match:
      1. Exact substring match on swap label (case-insensitive).
      2. Fall back to the top-ranked suggestion across all atoms if
         no specific match (better than leaving the canvas unchanged).
    """
    if not narration or result is None:
        return None
    # Collect all suggestions across all atom loops.
    all_sugs: list[dict] = []
    if isinstance(result, list):
        for item in result:
            if not isinstance(item, dict):
                continue
            all_sugs.extend(item.get("gemini_suggestions") or [])
            all_sugs.extend(item.get("playbook_suggestions") or [])
    elif isinstance(result, dict):
        all_sugs.extend(result.get("gemini_suggestions") or [])
        all_sugs.extend(result.get("playbook_suggestions") or [])
    # Only consider suggestions that have a usable after_smiles.
    candidates = [s for s in all_sugs
                  if isinstance(s, dict) and s.get("after_smiles")]
    if not candidates:
        return None
    nlow = narration.lower()
    # Pass 1: exact swap-label match.
    for s in candidates:
        swap = (s.get("swap") or "").strip().lower()
        if swap and swap in nlow:
            return {
                "smiles": s["after_smiles"],
                "swap": s.get("swap"),
                "rationale": s.get("rationale"),
            }
    # Pass 2: top-confidence fallback.
    top = max(candidates, key=lambda s: s.get("confidence", 0.0))
    return {
        "smiles": top["after_smiles"],
        "swap": top.get("swap"),
        "rationale": top.get("rationale"),
    }


def _compact_for_narrator(result: Any, depth: int = 0) -> Any:
    """Compact a tool result for the narrator prompt — drop the noisy
    `_factors`, `all_residue_scores`, and other internals the LLM
    doesn't need, keep the structural signal."""
    if depth > 4:
        return "..."
    DROP = {"_factors", "all_residue_scores", "contact_residue_details", "axis_reasoning"}
    if isinstance(result, dict):
        out: dict[str, Any] = {}
        for k, v in result.items():
            if k in DROP:
                continue
            out[k] = _compact_for_narrator(v, depth + 1)
        return out
    if isinstance(result, list):
        # cap arrays at 6 items
        return [_compact_for_narrator(x, depth + 1) for x in result[:6]]
    return result

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
    # Inline / loop steps don't dispatch a real tool, so args_fn is
    # optional. Defaulting to None keeps the dataclass happy when only
    # `inline_fn` is provided.
    args_fn: Optional[Callable[[dict], dict]] = None
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
    # Agentic narration — when set, after the step completes the
    # executor calls Gemini with `narrator_role` as persona to produce
    # REAL reasoning over the step's result. The output streams as a
    # `step.narration` SSE event, which the frontend renders as a
    # critic/editor/strategist message. Turns the chat from template
    # strings into actual LLM-generated commentary.
    narrator_role: Optional[str] = None  # "critic" | "editor" | "strategist" | None


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
            narrator_role="critic",  # real Gemini critic commentary
        ),
        Step(
            id="pick_atoms",
            label="Pick weak atoms",
            tool="__inline__",
            depends_on=["predict"],
            skip_if=lambda st: not (st.get("prediction") or {}).get("vulnerable_atoms"),
            # inline_fn returns the actual picked atoms so the step's
            # `result` field carries real content (was `{}` before,
            # which made the chat look like the strategist did nothing).
            inline_fn=lambda st: {
                "weak_atoms": [
                    v["atom_idx"]
                    for v in (st.get("prediction") or {}).get("vulnerable_atoms", [])
                ][:st.get("max_atoms", 3)],
                "n_vulnerable_total": len((st.get("prediction") or {}).get("vulnerable_atoms", [])),
                "max_atoms": st.get("max_atoms", 3),
            },
            on_result=lambda st, r: st.__setitem__("weak_atoms", (r or {}).get("weak_atoms", [])),
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
            narrator_role="editor",  # real Gemini editor commentary
        ),
    ],
    synthesize_fn=lambda st: _synth_harden(st),
))


def _synth_harden(state: dict) -> str:
    """Render the harden_candidate result as a clean, scannable per-atom
    breakdown.

    Two bugs this rewrite fixes:
      1. The mechanism rationale was sliced to 120 chars mid-word
         (the user saw '…the K382 ammonium group and re'). No more
         truncation — the full medchem reasoning is surfaced.
      2. The per-atom rows used a `•` bullet, which MarkdownText does
         NOT recognize as a list marker — so every suggestion plus the
         lines above collapsed into one run-on paragraph. Each atom is
         now its own block, separated by a horizontal rule, with the
         header / meta / SMILES / mechanism on their own paragraphs.
    """
    pred = state.get("prediction") or {}
    rob = pred.get("robustness_score", 0) or 0
    target = pred.get("target_name") or pred.get("pdb_id") or "the target"
    weak = state.get("weak_atoms") or []
    hardenings = state.get("hardenings") or []

    def _safe(s: Any) -> str:
        # Strip `*` so a stray asterisk in a Gemini swap label can't
        # break the **bold** span in the markdown renderer.
        return str(s or "").replace("*", "").strip()

    if not weak:
        return (
            f"Robustness against **{_safe(target)}**: **{rob:.2f}** — "
            f"no vulnerable atoms above the escape threshold. Nothing to "
            f"harden; this candidate is structurally insensitive to the "
            f"curated clinical mutations for this target."
        )

    tier = "solid" if rob >= 0.9 else "borderline" if rob >= 0.7 else "fragile"
    n_weak = len(weak)
    lines: list[str] = [
        f"Robustness against **{_safe(target)}**: **{rob:.2f}** — {tier}. "
        f"{n_weak} weak atom{'s' if n_weak != 1 else ''} flagged; here is the "
        f"highest-confidence hardening swap per atom."
    ]

    rendered = 0
    for i, h in enumerate(hardenings):
        gem = h.get("gemini_suggestions") or []
        pb = h.get("playbook_suggestions") or []
        all_s = [*gem, *pb]
        if not all_s:
            continue
        # Pick the genuinely highest-confidence suggestion across both
        # the Gemini and playbook sources, not just the first one.
        top = max(all_s, key=lambda s: s.get("confidence", 0) or 0)
        atom_idx = h.get("atom_idx")
        if atom_idx is None:
            atom_idx = weak[i] if i < len(weak) else "?"
        conf = top.get("confidence", 0) or 0
        source = _safe(top.get("source") or "playbook")
        swap = _safe(top.get("swap")) or "structural swap"
        delta = top.get("predicted_robustness_delta")
        after = top.get("after_smiles")
        rationale = (top.get("rationale") or "").strip()

        meta = f"conf {conf:.2f} · {source}"
        if isinstance(delta, (int, float)) and delta:
            meta += f" · projected Δrobustness {'+' if delta >= 0 else ''}{delta:.2f}"

        # Each piece on its own paragraph (blank-line separated) so the
        # renderer keeps them visually distinct instead of joining them.
        lines += ["", "---", "", f"**Atom {atom_idx} → {swap}**", "", meta]
        if after:
            lines += ["", f"`{after}`"]
        else:
            lines += ["", "_No auto-applied structure — apply this swap "
                          "manually in the 2D builder._"]
        if rationale:
            lines += ["", rationale]
        rendered += 1

    if rendered == 0:
        lines += ["", "_No hardening suggestions were generated for the "
                      "flagged atoms — try a different target or atom._"]
    else:
        lines += ["", "---", "", "Click any structure above to load + "
                      "re-score it, or run `/wf compare_top_n` to A/B the "
                      "hardened variants against the parent."]
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


# ── Workflow 4: compare_top_n (agentic — multi-step deep dive) ──────
def _build_compare_args(state: dict) -> dict:
    """Resolve smiles_list with graceful fallbacks. Order:
      1. Explicit smiles_list from inputs.
      2. Session candidates (recent loaded SMILES from session memory).
      3. Current SMILES + champion for the pathogen.
      4. Current SMILES alone (1-candidate compare still produces a
         valid step.done, even if 'side-by-side' is moot).
    Raises ValueError only when there is literally no SMILES anywhere
    — at which point the workflow can fail with a clear user-facing
    error instead of a KeyError stack trace.
    """
    sl = state.get("smiles_list") or []
    if isinstance(sl, list) and len(sl) >= 2:
        return {
            "smiles_list": sl,
            "labels": sl,
            "pdb_id": state.get("pdb_id", "1VQQ"),
        }

    # Pull from session memory: recent loads + scores
    candidates: list[str] = list(sl) if isinstance(sl, list) else []
    try:
        from . import session_memory as _sm
        sid = state.get("_session_id") or ""
        if sid:
            for ev in _sm.snapshot(sid, kinds=("load", "score", "candidate")):
                smi = ev.get("smiles")
                if smi and smi not in candidates:
                    candidates.append(smi)
    except Exception:
        pass

    # Champion for this pathogen
    pathogen = state.get("pathogen", "MRSA")
    try:
        from . import champions as _ch
        champ = _ch.get(pathogen)
        if champ and champ.get("smiles") and champ["smiles"] not in candidates:
            candidates.append(champ["smiles"])
    except Exception:
        pass

    # Current SMILES (the just-loaded molecule)
    cur = state.get("smiles")
    if cur and cur not in candidates:
        candidates.insert(0, cur)

    # Dedup + cap at 6
    seen = set()
    final = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            final.append(c)
        if len(final) >= 6:
            break

    if not final:
        raise ValueError(
            "compare_top_n needs at least one SMILES — pass smiles_list "
            "explicitly or load a candidate / promote a champion first."
        )
    if len(final) == 1:
        # Single-candidate compare is still informative (drug-class
        # profile + clinical_overlap) — don't crash.
        pass
    return {
        "smiles_list": final,
        "labels": final,
        "pdb_id": state.get("pdb_id", "1VQQ"),
    }


async def _critic_narrate_step(state: dict) -> dict:
    """Inline step: hand the structured compare result to the Critic
    Gemini call so the user gets a real narrative instead of a static
    template. Best-effort — failure does not abort the workflow."""
    from . import debate
    comparison = state.get("comparison") or {}
    pathogen = state.get("pathogen") or "MRSA"
    session_id = state.get("_session_id") or ""
    if not comparison.get("rows"):
        return {"error": "no comparison rows to narrate"}
    res = await debate.critic_narrate_compare(session_id, comparison, pathogen=pathogen)
    if res.error:
        return {"error": res.error, "elapsed_ms": res.elapsed_ms,
                "tokens_in": res.tokens_in, "tokens_out": res.tokens_out}
    out = dict(res.raw)
    out["elapsed_ms"] = res.elapsed_ms
    out["tokens_in"] = res.tokens_in
    out["tokens_out"] = res.tokens_out
    out["cost_usd"] = res.cost_usd
    return out


_register(Workflow(
    name="compare_top_n",
    label="Compare candidates",
    description="Side-by-side resistance comparison of N candidates plus a Gemini-driven Critic narrative naming the winner, loser's specific weakness, and recommended next action.",
    inputs=[
        # smiles_list is no longer required — workflow auto-fills from
        # session candidates + champion + current_smiles when missing.
        # User can still pass explicit list to override.
        {"name": "smiles_list", "type": "array", "required": False},
        {"name": "pdb_id", "type": "string", "default": "1VQQ"},
        {"name": "pathogen", "type": "string", "default": "MRSA"},
    ],
    tags=["compare", "critic"],
    steps=[
        Step(
            id="compare",
            label="Compare resistance profiles",
            tool="compare_resistance",
            # Defensive args_fn: when user says 'A/B test' / 'compare
            # both' without passing smiles_list, auto-fill from
            # 1) explicit input, 2) session candidates, 3) champion +
            # current SMILES. Avoids KeyError 'smiles_list' crash.
            args_fn=lambda st: _build_compare_args(st),
            on_result=lambda st, r: st.__setitem__("comparison", r),
        ),
        Step(
            id="critic_narrate",
            label="Critic narrates the comparison",
            tool="__inline__",
            inline_fn=_critic_narrate_step,
            on_result=lambda st, r: st.__setitem__("critic_verdict", r),
        ),
    ],
    synthesize_fn=lambda st: _synth_compare(st),
))


def _synth_compare(state: dict) -> str:
    c = state.get("comparison") or {}
    verdict = state.get("critic_verdict") or {}
    rows = c.get("rows") or []
    best_idx = c.get("best_idx")
    out: list[str] = [f"### Compared {c.get('n', 0)} candidates against `{c.get('pdb_id')}`"]
    out.append("")
    out.append("| # | SMILES | robustness | escape | contacts |")
    out.append("|---|---|---:|---:|---:|")
    for i, r in enumerate(rows):
        marker = "★ " if i == best_idx else ""
        smi = r.get("smiles") or r.get("label") or "?"
        smi_short = smi if len(smi) <= 30 else smi[:29] + "…"
        out.append(
            f"| {marker}{i+1} | `{smi_short}` | "
            f"{r.get('robustness_score', 0):.3f} | "
            f"{r.get('n_escape_vectors', 0)} | "
            f"{r.get('n_residues_with_contacts', 0)} |"
        )
    common = c.get("common_weak_residues") or []
    if common:
        out.append("")
        out.append(
            f"**Common weak residues** (hit by ≥½ the set): "
            + ", ".join(f"`{r['position']}`" for r in common[:5])
        )
    if verdict and not verdict.get("error"):
        out.append("")
        out.append("---")
        out.append("")
        out.append("**Critic's verdict** (Gemini Pro):")
        if verdict.get("winner_smiles"):
            out.append(f"  - 🏆 **Winner**: `{verdict['winner_smiles']}` — "
                       f"{verdict.get('winner_reason', '')}")
        if verdict.get("loser_smiles"):
            out.append(f"  - ❌ **Loser**: `{verdict['loser_smiles']}` — "
                       f"{verdict.get('loser_weakness', '')}")
        if verdict.get("common_pitfall"):
            out.append(f"  - ⚠ **Common pitfall**: {verdict['common_pitfall']}")
        if verdict.get("next_action"):
            out.append(f"  - ➡ **Next**: `{verdict['next_action']}` — "
                       f"{verdict.get('next_reason', '')}")
        if verdict.get("thinking"):
            out.append("")
            out.append(f"_{verdict['thinking']}_")
    elif verdict and verdict.get("error"):
        out.append("")
        out.append(f"_(Critic narration unavailable: {verdict['error']})_")
    return "\n".join(out)


# ── Workflow 5: optimize_for_property ────────────────────────────────
_register(Workflow(
    name="optimize_for_property",
    label="Improvement plan",
    description="Score the candidate, then build an improvement plan for the axis the user named (or the weakest axis if none given) with concrete medchem suggestions.",
    inputs=[
        {"name": "smiles", "type": "string", "required": True},
        {"name": "pathogen", "type": "string", "default": "MRSA"},
        {"name": "axis", "type": "string", "required": False,
         "description": ("Specific reward axis the user asked to improve "
                         "(predicted_mic, drug_likeness_qed, "
                         "synthesizability, hemolysis_safety, "
                         "structural_alerts, novelty, …). When omitted, "
                         "the mathematically weakest axis is targeted.")},
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


# Map free-form user terms to the canonical reward-axis name. The
# orchestrator should already hand us a canonical name, but users (and
# the model) say "MIC" / "drug-likeness" / "toxicity" — resolve those
# so optimize_for_property always answers the axis the user MEANT.
_AXIS_ALIASES: dict[str, list[str]] = {
    "predicted_mic":      ["predicted_mic", "predicted mic", "mic", "potency",
                           "activity", "efficacy", "kill", "antibacterial"],
    "drug_likeness_qed":  ["drug_likeness_qed", "drug likeness", "drug-likeness",
                           "druglikeness", "qed", "lipinski", "oral",
                           "bioavailability"],
    "synthesizability":   ["synthesizability", "synthesis", "synthesizable",
                           "sa score", "sa_score", "makeability"],
    "novelty":            ["novelty", "novel", "newness"],
    "embedding_novelty":  ["embedding_novelty", "embedding novelty", "embedding"],
    "hemolysis_safety":   ["hemolysis_safety", "hemolysis", "hemolytic", "rbc",
                           "red blood cell", "membrane safety"],
    "structural_alerts":  ["structural_alerts", "structural alerts", "alerts",
                           "toxicophore", "pains", "toxicity", "toxic", "tox"],
    "validity":           ["validity", "valid", "well-formed"],
}


def _resolve_axis_alias(text: str) -> Optional[str]:
    """Resolve a free-form axis term to a canonical reward-axis name.
    Returns None when nothing matches (caller falls back to argmin)."""
    t = (text or "").strip().lower()
    if not t:
        return None
    # Exact canonical name wins.
    if t in _AXIS_ALIASES:
        return t
    # Longest alias substring match — check the most specific first so
    # "embedding novelty" isn't shadowed by "novelty".
    best: Optional[str] = None
    best_len = 0
    for canon, aliases in _AXIS_ALIASES.items():
        for a in aliases:
            if a in t and len(a) > best_len:
                best, best_len = canon, len(a)
    return best


def _synth_optimize(state: dict) -> str:
    """Improvement plan. Leads with the axis the USER named — not a
    blind argmin. If the user said 'the MIC is bad' we answer
    predicted_mic, even when embedding_novelty scores lower; the
    mathematically-weakest axis is shown as a secondary note."""
    s = state.get("score") or {}
    reasoning_map = s.get("axis_reasoning") or {}
    rdkit = s.get("rdkit_properties") or {}
    composite = s.get("composite", 0) or 0
    computed_weakest = s.get("weakest")
    components = {
        c.get("name"): c
        for c in (s.get("components") or [])
        if isinstance(c, dict) and c.get("name")
    }

    def _axis_val(ax: Optional[str]) -> Optional[float]:
        c = components.get(ax or "")
        if not c:
            return None
        try:
            return float(c.get("value"))
        except (TypeError, ValueError):
            return None

    # The user-named axis WINS over the argmin — answer what was asked.
    requested = _resolve_axis_alias(state.get("axis") or "")
    if requested and (requested in reasoning_map or requested in components):
        focus, focus_src = requested, "requested"
    else:
        focus, focus_src = computed_weakest, "weakest"

    fr = reasoning_map.get(focus) or {}
    fv = _axis_val(focus)
    fv_str = f"{fv:.3f}" if isinstance(fv, (int, float)) else "n/a"

    lines: list[str] = [
        f"Composite: **{composite:.3f}** "
        f"(MW {rdkit.get('mw')}, LogP {rdkit.get('logp')}).",
        "",
    ]
    if focus_src == "requested":
        lines.append(f"**You flagged `{focus}`** — currently **{fv_str}**. "
                      f"Here is how to lift it:")
    else:
        lines.append(f"**Weakest axis: `{focus}`** — currently **{fv_str}**. "
                      f"Here is how to lift it:")
    lines.append("")
    # Real markdown `-` bullets (the old `•` char was not a recognised
    # list marker, so the lines collapsed into one run-on paragraph).
    if fr.get("explanation"):
        lines.append(f"- {fr['explanation']}")
    if fr.get("improvement"):
        lines.append(f"- **Improve:** {fr['improvement']}")
    pd = fr.get("predicted_delta")
    if isinstance(pd, (int, float)) and pd:
        lines.append(f"- **Projected Δ if applied:** +{pd:.2f}")

    # If the user named an axis that ISN'T the math-weakest, say so —
    # honest, not a silent override of their framing.
    if (focus_src == "requested" and computed_weakest
            and computed_weakest != focus):
        wv = _axis_val(computed_weakest)
        wv_str = f"{wv:.3f}" if isinstance(wv, (int, float)) else "n/a"
        lines += ["", f"_The lowest-scoring axis overall is "
                       f"`{computed_weakest}` ({wv_str}) — attack that "
                       f"instead if you want the single biggest composite "
                       f"lift._"]

    # Surface the 3 lowest axes so a "these are bad" complaint gets a
    # full picture, not just one number.
    ranked = sorted(
        ((n, _axis_val(n)) for n in components),
        key=lambda kv: kv[1] if isinstance(kv[1], (int, float)) else 1.0,
    )
    low3 = [f"`{n}` {v:.2f}" for n, v in ranked[:3]
            if isinstance(v, (int, float))]
    if low3:
        lines += ["", f"Lowest axes right now: {', '.join(low3)}."]
    return "\n".join(lines)


# ── Workflow 5b: plan_synthesis (Service 1 — retrosynthesis route) ───
# Three STREAMED steps so the agent is visibly working, not a 30s
# opaque wait: editor proposes the route → server validates + costs it
# → critic reviews it. Each step emits its own SSE event.

async def _synth_route_step(state: dict) -> dict:
    """Step 1 — editor agent proposes the retrosynthetic route."""
    from .chem_synthesis import _gemini_route, _heuristic_route, _canonical
    smi = state.get("smiles") or state.get("current_smiles") or ""
    if not smi or _canonical(smi) is None:
        return {"error": f"need a valid candidate SMILES (got {smi!r})"}
    raw = await _gemini_route(smi)
    if raw is None:
        raw = _heuristic_route(smi)
    state["_raw_route"] = raw
    return {
        "strategy": raw.get("strategy", ""),
        "n_steps": len(raw.get("steps") or []),
        "model": raw.get("_model"),
    }


def _synth_assemble_step(state: dict) -> dict:
    """Step 2 — server validates every intermediate with RDKit and
    costs the route from its reaction classes. No LLM, instant."""
    from .chem_synthesis import _assemble_route
    smi = state.get("smiles") or ""
    raw = state.get("_raw_route") or {}
    if not raw or not raw.get("steps"):
        return {"error": "no proposed route to validate"}
    return _assemble_route(smi, raw)


async def _synth_critique_step(state: dict) -> dict:
    """Step 3 — critic agent reviews the assembled route, then the
    complete route is persisted as a CRUD artifact."""
    from .chem_synthesis import _critique_route
    from . import service_store as _ss
    route = state.get("synthesis_route") or {}
    if route.get("error") or not route.get("steps"):
        return {"error": "no assembled route to critique"}
    crit = await _critique_route(route)
    route["critique"] = crit
    try:
        sid = state.get("session_id") or state.get("_session_id")
        rec = _ss.save_artifact(
            "synthesis_route", route, session_id=sid,
            smiles=route.get("smiles"),
            title=(f"Route · {route.get('n_steps')} steps · "
                   f"{route.get('cost_band')} cost · "
                   f"{route.get('overall_yield_pct')}% yield"),
        )
        route["artifact_id"] = rec["id"]
    except Exception:  # noqa: BLE001
        pass
    state["synthesis_route"] = route
    return crit


async def _synth_easier_analog_step(state: dict) -> dict:
    """Step 4 — THE agentic action: when the route is hard, the agent
    designs an easier-to-make analog, proves it, and queues it."""
    from .chem_synthesis import _design_simpler_analog
    from . import service_store as _ss, session_memory as _sm
    route = state.get("synthesis_route") or {}
    if route.get("error") or not route.get("steps"):
        return {"error": "no route to simplify"}
    analog = await _design_simpler_analog(route)
    route["easier_analog"] = analog
    sid = state.get("session_id") or state.get("_session_id")
    try:
        rec = _ss.save_artifact(
            "synthesis_route", route, session_id=sid, smiles=route.get("smiles"),
            title=(f"Route · {route.get('n_steps')} steps · "
                   f"{route.get('cost_band')} cost · "
                   f"{route.get('overall_yield_pct')}% yield"))
        route["artifact_id"] = rec["id"]
    except Exception:  # noqa: BLE001
        pass
    if analog and analog.get("improved"):
        try:
            _sm.record_proposal(
                sid or "", analog["analog_smiles"], source="synthesis",
                swap_label=f"easier-to-make analog ({analog['simplification']})",
                rationale=(f"Route {analog['steps_before']}→{analog['steps_after']} "
                           f"steps. {analog['rationale']}"))
        except Exception:  # noqa: BLE001
            pass
    state["synthesis_route"] = route
    return analog or {"note": "route is already practical — no simpler "
                              "analog needed"}


def _synth_plan_synthesis(state: dict) -> str:
    """Render the reasoned route — strategy, per-step yield/risk/cost,
    building blocks with derived availability, and the critic verdict."""
    r = state.get("synthesis_route") or {}
    if r.get("error"):
        return f"Couldn't plan a synthesis route: {r['error']}"
    n = r.get("n_steps", "?")
    cost = r.get("estimated_cost_usd")
    band = r.get("cost_band", "?")
    feas = r.get("feasibility_band", "?")
    lead = r.get("lead_time_days")
    yld = r.get("overall_yield_pct")
    cost_str = f"${cost:.0f}" if isinstance(cost, (int, float)) else "?"
    lines: list[str] = [
        f"Retrosynthetic route: **{n} steps** · ~**{cost_str}** ({band} cost) "
        f"· **{yld}%** overall yield · ~{lead} d lead time · feasibility "
        f"**{feas}**.",
    ]
    if r.get("strategy"):
        lines += ["", f"_Strategy: {r['strategy']}_"]
    if not r.get("route_reaches_target", True):
        lines.append("_Note: the final step did not cleanly close on the "
                      "target — treat the last disconnection as approximate._")
    for s in (r.get("steps") or []):
        rc = s.get("reaction_class") or ""
        meta = (f"yield {s.get('yield_pct')}% · {s.get('risk')} risk · "
                f"${s.get('est_cost_usd')} ({s.get('cost_driver')})")
        lines += ["", f"**Step {s.get('step')} — {s.get('name')}**"
                  + (f" · {rc}" if rc else ""), meta]
        reag = ", ".join(s.get("reagents") or [])
        if reag:
            lines.append(f"- Reagents: {reag}")
        if s.get("conditions"):
            lines.append(f"- Conditions: {s['conditions']}")
        if s.get("product_smiles"):
            lines.append(f"- Product: `{s['product_smiles']}`")
        if s.get("rationale"):
            lines.append(f"- {s['rationale']}")
    sms = r.get("starting_materials") or []
    if sms:
        lines += ["", "**Building blocks** (availability derived from "
                  "structural complexity):"]
        for sm in sms:
            lines.append(f"- {sm.get('name')} — _{sm.get('availability')}_ "
                         f"(${sm.get('est_cost_usd')}) · {sm.get('availability_reason')}")
    crit = r.get("critique") or {}
    if crit:
        lines += ["", "---", "",
                  f"**Critic review** — confidence "
                  f"{crit.get('confidence')}. Riskiest: step "
                  f"{crit.get('riskiest_step')} — {crit.get('risk_reason')}. "
                  f"Scale-up: {crit.get('scale_up_concern')} "
                  f"**Verdict:** {crit.get('verdict')}"]
    ea = r.get("easier_analog")
    if ea and ea.get("improved"):
        lines += ["", "---", "",
                  f"**Agent designed an easier-to-make analog** via "
                  f"_{ea['simplification']}_ — route "
                  f"**{ea['steps_before']}→{ea['steps_after']} steps**, "
                  f"${ea['cost_before']:.0f}→${ea['cost_after']:.0f}, "
                  f"feasibility {ea['feasibility_before']}→{ea['feasibility_after']}.",
                  f"`{ea['analog_smiles']}`",
                  f"{ea['rationale']} — say **apply** to load it."]
    elif ea and ea.get("note"):
        lines += ["", f"_{ea['note']}_"]
    return "\n".join(lines).strip()


_register(Workflow(
    name="plan_synthesis",
    label="Synthesis route",
    description=("Plan a retrosynthetic route for a candidate — editor "
                 "proposes named steps with yields + risk, the server "
                 "validates every intermediate and costs each step by "
                 "reaction class, and a critic reviews the route."),
    inputs=[
        {"name": "smiles", "type": "string", "required": True},
        {"name": "session_id", "type": "string", "required": False},
    ],
    tags=["synthesis", "make-route"],
    steps=[
        Step(
            id="plan_route",
            label="Editor proposes the retrosynthetic route",
            tool="__inline__",
            inline_fn=_synth_route_step,
            on_result=lambda st, r: st.__setitem__("_route_meta", r),
            narrator_role="editor",
        ),
        Step(
            id="validate_cost",
            label="Validate intermediates + cost the route",
            tool="__inline__",
            inline_fn=_synth_assemble_step,
            on_result=lambda st, r: st.__setitem__("synthesis_route", r),
        ),
        Step(
            id="critique",
            label="Critic reviews the route",
            tool="__inline__",
            inline_fn=_synth_critique_step,
            on_result=lambda st, r: st.__setitem__("route_critique", r),
            narrator_role="critic",
            optional=True,
        ),
        Step(
            id="design_easier",
            label="Agent designs an easier-to-make analog",
            tool="__inline__",
            inline_fn=_synth_easier_analog_step,
            on_result=lambda st, r: st.__setitem__("easier_analog", r),
            narrator_role="editor",
            optional=True,
        ),
    ],
    synthesize_fn=lambda st: _synth_plan_synthesis(st),
))


# ── Workflow 5c: fto_scan (Service 2 — agentic IP / novelty) ─────────
# Two streamed steps: honest prior-art scan → the agent DESIGNS a
# novelty-escaping variant and queues it. The service ACTS, it does
# not just grade.

async def _fto_scan_step(state: dict) -> dict:
    """Step 1 — honest prior-art scan vs the published corpus + the
    curated marketed-drug panel."""
    from .chem_ip import _scan, _canonical
    smi = state.get("smiles") or state.get("current_smiles") or ""
    if not smi or _canonical(smi) is None:
        return {"error": f"need a valid candidate SMILES (got {smi!r})"}
    try:
        return _scan(smi)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


async def _fto_escape_step(state: dict) -> dict:
    """Step 2 — THE agentic action: design a novelty-escaping variant,
    prove the novelty gain, persist + queue it for one-tap apply."""
    from .chem_ip import _design_escape_variant
    from . import service_store as _ss, session_memory as _sm
    report = state.get("fto_report") or {}
    if report.get("error") or "novelty_score" not in report:
        return {"error": "no prior-art report to act on"}
    escape = await _design_escape_variant(report)
    report["escape_variant"] = escape
    sid = state.get("session_id") or state.get("_session_id")
    try:
        rec = _ss.save_artifact(
            "fto_report", report, session_id=sid, smiles=report.get("smiles"),
            title=f"Novelty · {report.get('novelty_tier')} · "
                  f"score {report.get('novelty_score')}")
        report["artifact_id"] = rec["id"]
    except Exception:  # noqa: BLE001
        pass
    if escape and escape.get("improved"):
        try:
            _sm.record_proposal(
                sid or "", escape["variant_smiles"], source="ip-sentinel",
                swap_label=f"novelty-escape variant ({escape['modification']})",
                rationale=(f"Lifts novelty {escape['novelty_before']}→"
                           f"{escape['novelty_after']}. {escape['rationale']}"))
        except Exception:  # noqa: BLE001
            pass
    state["fto_report"] = report
    return escape or {"note": "already structurally novel — no escape edit needed"}


def _synth_fto_scan(state: dict) -> str:
    """Render the prior-art report + the agent's escape variant."""
    r = state.get("fto_report") or {}
    if r.get("error"):
        return f"Couldn't run the IP scan: {r['error']}"
    cps = r.get("closest_published_similarity")
    pub = r.get("closest_published") or {}
    drug = r.get("closest_marketed_drug")
    pa = r.get("prior_art") or {}
    lines = [
        f"Novelty: **{r.get('verdict')}** — novelty score "
        f"**{r.get('novelty_score')}** ({r.get('novelty_tier')}).",
        "",
        f"**Closest published structure:** {pub.get('ref','—')} at "
        f"**{cps}** Tanimoto. {r.get('ip_note','')}",
    ]
    if drug:
        lines.append(f"**Closest marketed antibiotic:** {drug['name']} "
                     f"({drug['similarity']} sim · {drug.get('drug_class')} · "
                     f"{drug.get('ip_status')}).")
    else:
        lines.append("No structurally related marketed antibiotic — the "
                     "candidate sits in its own region of chemical space.")
    lines.append(f"**Prior art:** {pa.get('close',0)} close + "
                 f"{pa.get('near_identical',0)} near-identical published "
                 f"structures (corpus {pa.get('corpus_size',0)}).")
    esc = r.get("escape_variant")
    if esc and esc.get("improved"):
        lines += ["", "---", "",
                  f"**Agent designed a more-novel variant** via "
                  f"_{esc['modification']}_ — novelty "
                  f"**{esc['novelty_before']} → {esc['novelty_after']}** "
                  f"(closest-similarity {esc['closest_similarity_before']} → "
                  f"{esc['closest_similarity_after']}).",
                  f"`{esc['variant_smiles']}`",
                  f"{esc['rationale']} — say **apply** to load it."]
    elif esc and esc.get("note"):
        lines += ["", f"_{esc['note']}_"]
    return "\n".join(lines).strip()


_register(Workflow(
    name="fto_scan",
    label="IP / novelty scan",
    description=("Honest prior-art scan for a candidate, then the agent "
                 "designs a novelty-escaping variant that breaks the "
                 "overlap while keeping the antibacterial pharmacophore "
                 "— queued for one-tap apply."),
    inputs=[
        {"name": "smiles", "type": "string", "required": True},
        {"name": "session_id", "type": "string", "required": False},
    ],
    tags=["ip", "fto", "novelty"],
    steps=[
        Step(
            id="prior_art_scan",
            label="Scan published prior art + marketed-drug panel",
            tool="__inline__",
            inline_fn=_fto_scan_step,
            on_result=lambda st, r: st.__setitem__("fto_report", r),
        ),
        Step(
            id="design_escape",
            label="Agent designs a novelty-escaping variant",
            tool="__inline__",
            inline_fn=_fto_escape_step,
            on_result=lambda st, r: st.__setitem__("fto_escape", r),
            narrator_role="editor",
        ),
    ],
    synthesize_fn=lambda st: _synth_fto_scan(st),
))


# ── Workflow 5d: admet_panel (Service 3 — agentic 5-axis ADMET) ──────
# Two streamed steps: physchem + 5-axis predictions, then the agent
# DESIGNS a structural fix for the worst-scoring axis and queues it.

async def _admet_panel_step(state: dict) -> dict:
    """Step 1 — compute the full 5-axis ADMET envelope (A/D/M/E/T) from
    RDKit physchem + reuses the SMARTS toxicity scan."""
    from .chem_admet import _build_panel, _canonical, _non_drug_like_reason
    smi = state.get("smiles") or state.get("current_smiles") or ""
    canon = _canonical(smi)
    if canon is None:
        return {"error": f"need a valid candidate SMILES (got {smi!r})"}
    nd = _non_drug_like_reason(canon)
    if nd:
        return {"smiles": canon, "non_drug_reason": nd,
                "composite": 0.0, "tier": "n/a",
                "axes": {}, "worst": {"axis": None, "score": 0.0}}
    try:
        return await _build_panel(canon)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


async def _admet_fix_step(state: dict) -> dict:
    """Step 2 — agent designs a structural fix for the worst axis,
    re-panels the analog to PROVE improvement, queues it."""
    from .chem_admet import _gemini_admet_fix, _ARTIFACT_KIND
    from . import service_store as _ss, session_memory as _sm
    panel = state.get("admet_panel") or {}
    if panel.get("error") or panel.get("non_drug_reason"):
        return {"note": panel.get("non_drug_reason") or "no panel to act on"}
    fix = await _gemini_admet_fix(panel)
    panel["fix"] = fix
    sid = state.get("session_id") or state.get("_session_id")
    try:
        rec = _ss.save_artifact(
            _ARTIFACT_KIND, panel, session_id=sid, smiles=panel.get("smiles"),
            title=(f"ADMET · {panel.get('tier')} · "
                   f"composite {panel.get('composite')} · "
                   f"weakest {panel.get('worst',{}).get('axis')}"))
        panel["artifact_id"] = rec["id"]
    except Exception:  # noqa: BLE001
        pass
    if fix and fix.get("improved"):
        try:
            _sm.record_proposal(
                sid or "", fix["variant_smiles"], source="admet-observatory",
                swap_label=f"ADMET fix ({fix['modification']})",
                rationale=(f"Lifts {fix['axis_label']} "
                           f"{fix['score_before']}→{fix['score_after']}. "
                           f"{fix['rationale']}"))
        except Exception:  # noqa: BLE001
            pass
    state["admet_panel"] = panel
    return fix or {"note": "no fix needed — worst axis is already healthy "
                   "or no improvement could be proven"}


def _synth_admet_panel(state: dict) -> str:
    p = state.get("admet_panel") or {}
    if p.get("error"):
        return f"Couldn't compute the ADMET panel: {p['error']}"
    if p.get("non_drug_reason"):
        return (f"Not applicable — {p['non_drug_reason']}. Load a drug-like "
                "candidate (≥10 heavy atoms, ≥1 ring) for a PK panel.")
    axes = p.get("axes") or {}
    worst = p.get("worst") or {}
    src = p.get("source", "heuristic")
    src_label = ("real model (ADMET-AI · Chemprop-RDKit, 41 TDC endpoints)"
                 if src == "admet-ai" else "physchem heuristics (real model offline)")
    lines = [
        f"ADMET panel — composite **{p.get('composite')}** · "
        f"tier **{p.get('tier')}** · weakest axis **{worst.get('axis')}** "
        f"({worst.get('band')}).",
        f"_Source: {src_label}._",
        "",
        "Per-axis scores (0-1, higher = better):",
        f"- **A** (absorption): {axes.get('A',{}).get('score','—')} · F% "
        f"{axes.get('A',{}).get('f_percent','—')} · HIA "
        f"{axes.get('A',{}).get('hia_percent','—')}",
        f"- **D** (distribution): {axes.get('D',{}).get('score','—')} · PPB "
        f"{axes.get('D',{}).get('ppb_percent','—')}% · BBB "
        f"{axes.get('D',{}).get('bbb_class','—')}",
        f"- **M** (metabolism): {axes.get('M',{}).get('score','—')} · HLM "
        f"{axes.get('M',{}).get('hlm_band','—')} · CYP3A4 inhib "
        f"{axes.get('M',{}).get('cyp3a4_inhib_risk','—')}",
        f"- **E** (excretion): {axes.get('E',{}).get('score','—')} · t½ "
        f"{axes.get('E',{}).get('t_half_hours','—')}h · "
        f"{axes.get('E',{}).get('dose_interval','—')}",
        f"- **T** (toxicity): {axes.get('T',{}).get('score','—')} · hERG "
        f"{axes.get('T',{}).get('herg_risk','—')} · hepatotox "
        f"{axes.get('T',{}).get('hepatotox_risk','—')}",
    ]
    fix = p.get("fix")
    if fix and fix.get("improved"):
        lines += ["", "---", "",
                  f"**Agent designed an ADMET-fix analog** via "
                  f"_{fix['modification']}_ — lifts {fix['axis_label']} "
                  f"**{fix['score_before']} → {fix['score_after']}** "
                  f"(composite {fix['composite_before']} → "
                  f"{fix['composite_after']}).",
                  f"`{fix['variant_smiles']}`",
                  f"{fix['rationale']} — say **apply** to load it."]
    elif fix and fix.get("note"):
        lines += ["", f"_{fix['note']}_"]
    return "\n".join(lines).strip()


_register(Workflow(
    name="admet_panel",
    label="ADMET panel · 5-axis PK",
    description=("Five-axis ADMET prediction (Absorption / Distribution / "
                 "Metabolism / Excretion / Toxicity) for a candidate, "
                 "then the agent designs a structural fix for the worst "
                 "axis — queued for one-tap apply."),
    inputs=[
        {"name": "smiles", "type": "string", "required": True},
        {"name": "session_id", "type": "string", "required": False},
    ],
    tags=["admet", "pk", "absorption", "metabolism", "toxicity"],
    steps=[
        Step(
            id="compute_panel",
            label="Compute 5-axis ADMET panel",
            tool="__inline__",
            inline_fn=_admet_panel_step,
            on_result=lambda st, r: st.__setitem__("admet_panel", r),
        ),
        Step(
            id="design_fix",
            label="Agent designs a fix for the worst axis",
            tool="__inline__",
            inline_fn=_admet_fix_step,
            on_result=lambda st, r: st.__setitem__("admet_fix", r),
            narrator_role="editor",
        ),
    ],
    synthesize_fn=lambda st: _synth_admet_panel(st),
))


# ── Workflow 6: pareto_explore (agentic — score → frontier → critic) ─
# Runs the full Pareto loop: kicks scoring on any unscored candidates,
# fetches the frontier on the chosen axes, then has Gemini Pro Critic
# narrate the trade-offs and recommend advance/A-B/drop.

async def _pareto_score_missing_step(state: dict) -> dict:
    """Inline step: kick the score-missing job for the session.
    Best-effort — workflow continues even if no missing candidates."""
    sid = state.get("session_id") or state.get("_session_id") or ""
    if not sid:
        return {"skipped": "no session_id"}
    try:
        from . import chem_pareto as _cp
        # session_pareto_score_missing returns {"queued": int}
        rv = await _cp.session_pareto_score_missing(sid)
        return rv if isinstance(rv, dict) else {"result": rv}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"score-missing skipped: {exc}"}


async def _pareto_fetch_step(state: dict) -> dict:
    """Inline step: fetch the Pareto frontier on the requested axes."""
    sid = state.get("session_id") or state.get("_session_id") or ""
    if not sid:
        return {"error": "no session_id"}
    x = state.get("x_axis") or "predicted_mic"
    y = state.get("y_axis") or "composite_reward"
    try:
        from . import chem_pareto as _cp
        rv = await _cp.session_pareto(sid, x=x, y=y)
        return rv
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


async def _pareto_critic_step(state: dict) -> dict:
    """Inline step: Critic narrates the frontier."""
    from . import debate
    pareto = state.get("pareto_frontier") or {}
    if pareto.get("error") or not pareto.get("all_points"):
        return {"error": pareto.get("error") or "no Pareto points to narrate"}
    pathogen = state.get("pathogen") or "MRSA"
    sid = state.get("_session_id") or state.get("session_id") or ""
    res = await debate.critic_narrate_pareto(sid, pareto, pathogen=pathogen)
    if res.error:
        return {"error": res.error, "elapsed_ms": res.elapsed_ms,
                "tokens_in": res.tokens_in, "tokens_out": res.tokens_out}
    out = dict(res.raw)
    out["elapsed_ms"] = res.elapsed_ms
    out["tokens_in"] = res.tokens_in
    out["tokens_out"] = res.tokens_out
    out["cost_usd"] = res.cost_usd
    return out


_register(Workflow(
    name="pareto_explore",
    label="Pareto frontier · explore",
    description=("Kick scoring on unscored candidates, fetch the "
                 "Pareto frontier, and have the Critic narrate which "
                 "candidate to advance, A/B partner, and drop with "
                 "specific dimension citations."),
    inputs=[
        {"name": "session_id", "type": "string", "required": False,
         "description": "Defaults to the active chat session"},
        {"name": "x_axis", "type": "string", "default": "predicted_mic"},
        {"name": "y_axis", "type": "string", "default": "composite_reward"},
        {"name": "pathogen", "type": "string", "default": "MRSA"},
    ],
    tags=["pareto", "critic", "explore"],
    steps=[
        Step(
            id="score_missing",
            label="Kick scoring on unscored candidates",
            tool="__inline__",
            inline_fn=_pareto_score_missing_step,
            on_result=lambda st, r: st.__setitem__("score_missing_result", r),
            optional=True,
        ),
        Step(
            id="fetch_frontier",
            label="Fetch Pareto frontier",
            tool="__inline__",
            inline_fn=_pareto_fetch_step,
            on_result=lambda st, r: st.__setitem__("pareto_frontier", r),
        ),
        Step(
            id="critic_narrate_pareto",
            label="Critic narrates the frontier",
            tool="__inline__",
            inline_fn=_pareto_critic_step,
            on_result=lambda st, r: st.__setitem__("pareto_critic", r),
            optional=True,
        ),
    ],
    synthesize_fn=lambda st: _synth_pareto_explore(st),
))


def _synth_pareto_explore(state: dict) -> str:
    pareto = state.get("pareto_frontier") or {}
    critic = state.get("pareto_critic") or {}
    score_missing = state.get("score_missing_result") or {}
    if pareto.get("error"):
        return f"_Pareto frontier unavailable: {pareto['error']}_"
    points = pareto.get("all_points") or []
    scored = [p for p in points if p.get("x_value") is not None and p.get("y_value") is not None]
    pareto_set = pareto.get("pareto_set") or []
    x_label = (pareto.get("x_axis_meta") or {}).get("label") or pareto.get("x_axis", "x")
    y_label = (pareto.get("y_axis_meta") or {}).get("label") or pareto.get("y_axis", "y")
    out: list[str] = [f"### Pareto frontier · **{x_label}** vs **{y_label}**"]
    out.append("")
    n_kicked = score_missing.get("queued") or score_missing.get("n_queued") or 0
    if n_kicked:
        out.append(f"_Kicked scoring on {n_kicked} unscored candidate(s) — "
                   f"results may need a refresh._")
        out.append("")
    out.append(
        f"**{len(scored)} scored** of {len(points)} total · "
        f"**{len(pareto_set)} on the frontier**"
    )
    out.append("")
    if scored:
        out.append("| candidate | SMILES | x | y | pareto |")
        out.append("|---|---|---:|---:|:---:|")
        for p in scored[:8]:
            cid = (p.get("candidate_id") or "")[:10]
            smi = p.get("smiles") or "?"
            smi_short = smi if len(smi) <= 28 else smi[:27] + "…"
            on = "★" if p.get("on_pareto") else ""
            out.append(
                f"| `{cid}` | `{smi_short}` | "
                f"{p.get('x_value', 0):.3f} | {p.get('y_value', 0):.3f} | {on} |"
            )
    if critic and not critic.get("error"):
        out.append("")
        out.append("---")
        out.append("")
        out.append("**Critic's verdict** (Gemini Pro):")
        if critic.get("advance_smiles"):
            out.append(f"  - 🚀 **Advance**: `{critic['advance_smiles']}` — "
                       f"{critic.get('advance_reason', '')}")
        if critic.get("secondary_smiles"):
            out.append(f"  - ⚖️ **A/B partner**: `{critic['secondary_smiles']}` — "
                       f"{critic.get('secondary_reason', '')}")
        if critic.get("drop_smiles"):
            out.append(f"  - 🗑️ **Drop**: `{critic['drop_smiles']}` — "
                       f"{critic.get('drop_reason', '')}")
        if critic.get("trade_off_insight"):
            out.append(f"  - 💡 **Trade-off**: {critic['trade_off_insight']}")
        if critic.get("next_action"):
            out.append(f"  - ➡ **Next**: `{critic['next_action']}`")
        if critic.get("thinking"):
            out.append("")
            out.append(f"_{critic['thinking']}_")
    elif critic and critic.get("error"):
        out.append("")
        out.append(f"_(Critic narration unavailable: {critic['error']})_")
    return "\n".join(out)


# ── Workflow 7: design_with_debate ───────────────────────────────────
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
    # ── Queue the winner as a pending agent proposal ──
    # Strategist's `next_action` is frequently 'ship' — meaning the
    # user should accept this candidate. Push the winner SMILES onto
    # the proposal queue so when the user types 'ship'/'ship it'/
    # 'apply'/'accept', the orchestrator's accept-phrase fast-path
    # pops it and loads the winner into the canvas. Without this,
    # 'ship' fell through to Gemini and got hallucinated as a SMILES
    # ('/load ship' → 'invalid SMILES').
    if outcome.winner and sid:
        try:
            from . import session_memory as _sm
            _sm.record_proposal(
                sid,
                outcome.winner,
                source="strategist",
                swap_label=f"debate winner ({outcome.next_action})",
                rationale=outcome.justification or "Strategist picked this as the round's winner.",
            )
        except Exception:
            pass
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
                 "depends_on": s.depends_on, "description": s.description,
                 "narrator_role": s.narrator_role}
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

            # `args_fn` is optional for inline / loop steps that don't
            # have an HTTP tool to dispatch.
            if step.args_fn is None:
                args = {}
            else:
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

            # ── Agentic narration ──
            # When a step declares a narrator_role, fire a Gemini call
            # to produce REAL reasoning over the result. The chat
            # renders this as a critic/editor/strategist message
            # instead of a Python-templated stat dump. This is what
            # makes the loop genuinely agentic — every step closes
            # with an LLM-written opinion, not a string format.
            if step.narrator_role:
                try:
                    narration = await _gemini_narrate(
                        step.narrator_role, step.label, data,
                    )
                except Exception:
                    narration = None
                if narration:
                    yield _sse({
                        "event": "step.narration",
                        "run_id": run_id,
                        "step_id": step.id,
                        "role": step.narrator_role,
                        "text": narration,
                    })
                # ── Auto-apply: when the editor commits to a swap in
                # its narration, find the matching after_smiles in the
                # tool result and emit a step.apply_smiles SSE event.
                # The frontend listens and loads that SMILES into the
                # 2D + 3D canvas. Closes the "narrates but never
                # executes" gap user pointed out.
                if step.narrator_role == "editor" and narration:
                    applied = _extract_applied_smiles(narration, data)
                    if applied:
                        # Queue the proposal so a follow-up 'apply that'
                        # / 'do it' from chat finds the right SMILES
                        # even if the auto-apply event was missed by
                        # the frontend (older session, race, etc.).
                        try:
                            from . import session_memory as _sm
                            _sm.record_proposal(
                                session_id or "",
                                applied["smiles"],
                                source="editor",
                                swap_label=applied.get("swap"),
                                rationale=applied.get("rationale"),
                            )
                        except Exception:
                            pass
                        yield _sse({
                            "event": "step.apply_smiles",
                            "run_id": run_id,
                            "step_id": step.id,
                            "smiles": applied["smiles"],
                            "swap_label": applied.get("swap"),
                            "rationale": applied.get("rationale"),
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

        # ── Integration backbone — harness-level dossier feed ──
        # Auto-link this workflow's results into the candidate's
        # dossier. ONE hook: any workflow that touched a candidate
        # (scored / hardened / planned a route) attaches its facets,
        # so the dossier stays integrated without per-workflow wiring.
        try:
            from . import candidate_dossier as _dossier
            fed = _dossier.feed_from_state(state)
            if fed and isinstance(truncated_state, dict):
                truncated_state["dossier_facets_fed"] = fed
        except Exception as exc:  # noqa: BLE001
            log.debug("dossier feed failed: %s", exc)

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
