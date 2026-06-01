"""Agentic AI endpoint — Gemini Pro with chemistry tool-calling, streamed.

POST /api/agent/run (SSE) — drops the user into a real planning agent that
calls our chemistry tools (score, predict_resistance, harden, compare,
design, similar, properties, place_in_pocket, ...) one or more times,
and emits events live so the UI renders the agent's tool calls as
they happen — Claude/Cursor style.

Event types streamed (one per SSE `data:` line, JSON-encoded):
  {"event": "agent.start",     "session_id", "user_text"}
  {"event": "agent.thinking",  "text": "<plan-of-attack>"}
  {"event": "tool.call",       "tool", "args", "call_id"}
  {"event": "tool.result",     "call_id", "elapsed_ms", "result"}
  {"event": "tool.error",      "call_id", "error"}
  {"event": "text.delta",      "text": "<chunk>"}
  {"event": "agent.done",      "elapsed_ms", "n_tool_calls"}

Backed by Gemini's function-calling API: we declare each chemistry tool
once with its schema, hand the user's text + tool registry to Gemini Pro,
and run an iterative loop until Gemini returns a non-functioncall part
(final assistant text). Each function call is dispatched server-side
through the FastAPI app's own routes — so every tool the agent has is
identical to what the chat UI exposes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Optional, AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

log = logging.getLogger("api.agent")
router = APIRouter(prefix="/api/agent", tags=["agent"])


# ─────────────────────────────────────────────────────────────────────
# Tool registry — each tool maps to a real backend endpoint.
# Function declarations follow Gemini's function-calling schema.
# ─────────────────────────────────────────────────────────────────────

_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "score_molecule",
        "description": (
            "Score a SMILES candidate on the 12-component reward stack "
            "(predicted MIC, drug-likeness QED, synthesizability, novelty, "
            "hemolysis safety, structural alerts, validity, embedding novelty). "
            "Returns composite score + per-axis values."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "smiles": {"type": "string", "description": "Candidate SMILES string."},
                "target_pathogen": {
                    "type": "string",
                    "description": "Pathogen code (MRSA, Ecoli, etc.) — affects predicted_mic axis."
                },
            },
            "required": ["smiles"],
        },
    },
    {
        "name": "score_explain",
        "description": (
            "Like score_molecule but ALSO returns RDKit-derived properties "
            "(MW, LogP, HBA, HBD, TPSA, rotatables, fsp3, QED, formula), "
            "Lipinski/Veber/Egan/Ghose rule-compliance flags, and Gemini-"
            "generated per-axis WHY+IMPROVE reasoning. Use this when the "
            "user wants a deep breakdown."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "smiles": {"type": "string"},
                "target_pathogen": {"type": "string"},
            },
            "required": ["smiles"],
        },
    },
    {
        "name": "predict_resistance",
        "description": (
            "Predict per-atom resistance escape vectors for a candidate "
            "against a curated pathogen target. Returns robustness 0..1, "
            "vulnerable atoms, contact residues, drug-class profile, and "
            "the residue × mutation heatmap. Uses Grantham × distance × "
            "conservation chemistry math."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "smiles": {"type": "string"},
                "pdb_id": {"type": "string", "description": "PDB id, e.g. '1VQQ' for PBP2a."},
            },
            "required": ["smiles", "pdb_id"],
        },
    },
    {
        "name": "harden_atom",
        "description": (
            "Generate medchem swap suggestions to harden a specific atom "
            "against the clinical mutation that defeats it. Returns BOTH "
            "Gemini-bespoke (4) and curated playbook (3) suggestions, each "
            "with mechanism (steric/electronic/conformational/isosteric/"
            "h-bond), proposed_smiles validated by RDKit, predicted Δ-"
            "robustness, and confidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "smiles": {"type": "string"},
                "pdb_id": {"type": "string"},
                "atom_idx": {"type": "integer", "description": "0-based RDKit atom index."},
            },
            "required": ["smiles", "pdb_id", "atom_idx"],
        },
    },
    {
        "name": "cross_target_risk",
        "description": (
            "Run resistance prediction for ONE candidate against MANY "
            "curated targets to assess broad-spectrum profile. Returns "
            "per-target robustness + spectrum classification (broad/"
            "narrow/fragile)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "smiles": {"type": "string"},
                "pdb_ids": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Optional subset; defaults to ALL curated targets.",
                },
            },
            "required": ["smiles"],
        },
    },
    {
        "name": "compare_resistance",
        "description": (
            "Side-by-side resistance comparison of N (≤8) candidates against "
            "the same target. Returns per-candidate robustness + escape "
            "vectors + common-weak-residues across the set."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "smiles_list": {"type": "array", "items": {"type": "string"}},
                "pdb_id": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["smiles_list", "pdb_id"],
        },
    },
    {
        "name": "explain_resistance",
        "description": (
            "Plain-language explanation (3-4 sentences) of WHY a candidate "
            "is robust or vulnerable against a target. Suitable for the "
            "chat thread or report panel."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "smiles": {"type": "string"},
                "pdb_id": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["smiles", "pdb_id"],
        },
    },
    {
        "name": "list_targets",
        "description": "List validated targets for a pathogen (PBP2a/MRSA, etc.).",
        "parameters": {
            "type": "object",
            "properties": {"pathogen": {"type": "string"}},
            "required": ["pathogen"],
        },
    },
    {
        "name": "place_in_pocket",
        "description": (
            "Place a candidate into the active-site pocket of a target and "
            "report contact residues + binding/clashing atom indices."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "smiles": {"type": "string"},
                "pdb_id": {"type": "string"},
            },
            "required": ["smiles", "pdb_id"],
        },
    },
    {
        "name": "molecule_properties",
        "description": (
            "Compute RDKit molecular properties (MW, LogP, HBA, HBD, TPSA, "
            "rotatables, ring count, aromatic rings, fsp3, QED, formula, "
            "stereo centers)."
        ),
        "parameters": {
            "type": "object",
            "properties": {"smiles": {"type": "string"}},
            "required": ["smiles"],
        },
    },
    {
        "name": "analyze_toxicity",
        "description": (
            "QSAR toxicity / safety profile for a SMILES. Returns four "
            "endpoints — hERG cardiotoxicity, hepatotoxicity, Ames "
            "mutagenicity, and skin sensitization — each with a risk tier "
            "(low / medium / high), a 0-1 score, and the specific "
            "toxicophore or physicochemical rationale behind it, plus an "
            "overall_safety_score. This IS the platform's toxicity model "
            "— ALWAYS call it when the user asks about toxicity, safety, "
            "side effects, hERG, cardiotoxicity, mutagenicity, "
            "hepatotoxicity, or 'is this molecule safe'. Never tell the "
            "user the platform lacks a toxicity tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {"smiles": {"type": "string"}},
            "required": ["smiles"],
        },
    },
    {
        "name": "plan_synthesis",
        "description": (
            "Plan a retrosynthetic route for a SMILES — named steps, "
            "reagents + conditions, commercial building-block "
            "availability, a server-computed cost estimate, lead-time, "
            "and a feasibility band. Use this whenever the user asks "
            "'can we make this', 'how would you synthesize it', about "
            "the synthetic route, cost-to-make, or building blocks. "
            "Turns the abstract synthesizability score into a real plan."
        ),
        "parameters": {
            "type": "object",
            "properties": {"smiles": {"type": "string"}},
            "required": ["smiles"],
        },
    },
    {
        "name": "check_freedom_to_operate",
        "description": (
            "Freedom-to-operate (FTO) / IP scan for a SMILES. Returns "
            "the closest known antibiotic + its patent status, the "
            "closest LIVE-patent analog, prior-art density vs a 12k "
            "published-structure corpus, a claim-overlap risk tier, a "
            "freedom_score (0-1) and a verdict (clear / watch / "
            "blocked). Use whenever the user asks 'is this novel', "
            "'is it already patented', about IP, freedom to operate, "
            "patents, or prior art."
        ),
        "parameters": {
            "type": "object",
            "properties": {"smiles": {"type": "string"}},
            "required": ["smiles"],
        },
    },
    {
        "name": "predict_activity",
        "description": (
            "Predicted antibacterial-activity prior for a SMILES, from a "
            "REAL trained classifier (gradient-boosted, Morgan fingerprints, "
            "learned from ChEMBL antibiotic actives vs property-matched "
            "decoys + marketed-drug hard-negatives, test ROC-AUC ~0.98). "
            "Returns a 0-1 probability that the molecule structurally "
            "resembles known antibacterials. Use when the user asks 'is "
            "this likely active', 'will it work as an antibiotic', about "
            "predicted activity or potency prior. It is a structural-"
            "similarity prior, NOT a guaranteed MIC."
        ),
        "parameters": {
            "type": "object",
            "properties": {"smiles": {"type": "string"}},
            "required": ["smiles"],
        },
    },
    {
        "name": "predict_admet",
        "description": (
            "Five-axis ADMET prediction (Absorption / Distribution / "
            "Metabolism / Excretion / Toxicity) for a SMILES. Each axis "
            "returns a 0-1 score + band (good/moderate/poor) + the "
            "underlying values: F%, HIA, Caco-2 Papp, PPB%, BBB class, "
            "Vd, CYP3A4/2D6/2C9 inhibition risk, HLM stability, "
            "clearance, dose interval, hERG / hepatotox / AMES risks. "
            "Use whenever the user asks about PK, ADME, pharmacokinetics, "
            "bioavailability, half-life, dose interval, CYP "
            "interactions, BBB penetration, or wants the full safety + "
            "PK panel together. The agent also designs a structural "
            "fix for the worst axis when asked."
        ),
        "parameters": {
            "type": "object",
            "properties": {"smiles": {"type": "string"}},
            "required": ["smiles"],
        },
    },
    {
        "name": "list_axes",
        "description": "List all Pareto axis options + their direction/source/unit.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "session_pareto_explain",
        "description": (
            "Gemini-powered explanation of why a candidate is or isn't on "
            "the Pareto frontier of a session, given chosen axes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "candidate_id": {"type": "string"},
                "x_axis": {"type": "string"},
                "y_axis": {"type": "string"},
            },
            "required": ["session_id", "candidate_id"],
        },
    },
    # ── Agentic close-the-loop tool ──
    # Every analysis MUST end with this. Queues a concrete swap or
    # follow-up SMILES for the user to accept with "apply". Closes
    # the "narrates but never executes" gap once and for all.
    {
        "name": "propose_next_action",
        "description": (
            "Commit to the SPECIFIC next move. Call this EXACTLY ONCE at "
            "the end of every multi-step analysis, BEFORE writing your "
            "final summary. Queues a pending proposal — the user can "
            "accept it by saying 'apply', 'do it', 'go ahead', etc. "
            "Use this to make a concrete recommendation (a new SMILES "
            "to load, or a workflow to run) rather than hand-waving "
            "with 'future work could focus on...'. Failing to call "
            "this means the agent didn't deliver an actionable next "
            "step."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "'load_smiles' if you have a concrete modified molecule to apply; 'run_workflow' if the right move is a multi-step workflow.",
                    "enum": ["load_smiles", "run_workflow"],
                },
                "smiles": {
                    "type": "string",
                    "description": "Required when kind='load_smiles'. The exact SMILES you want loaded into 2D + 3D + auto-scored.",
                },
                "swap_label": {
                    "type": "string",
                    "description": "Short human label for the change (e.g. 'add 6α-methoxy', 'replace ester with amide').",
                },
                "workflow_name": {
                    "type": "string",
                    "description": "Required when kind='run_workflow'. e.g. 'harden_candidate', 'compare_top_n', 'optimize_for_property'.",
                },
                "rationale": {
                    "type": "string",
                    "description": "One-sentence WHY — what signal in the prior tool results justifies this move.",
                },
            },
            "required": ["kind", "rationale"],
        },
    },
]


async def _dispatch_tool(name: str, args: dict[str, Any], api_base: str) -> dict[str, Any]:
    """Execute a tool call by hitting the corresponding FastAPI route."""
    async with httpx.AsyncClient(timeout=60.0) as cx:
        if name == "score_molecule":
            r = await cx.post(f"{api_base}/workbench/score", json={
                "smiles": args["smiles"],
                "target_pathogen": args.get("target_pathogen", "MRSA"),
            })
        elif name == "score_explain":
            r = await cx.post(f"{api_base}/workbench/score-explain", json={
                "smiles": args["smiles"],
                "target_pathogen": args.get("target_pathogen", "MRSA"),
            })
        elif name == "predict_resistance":
            r = await cx.post(f"{api_base}/workbench/chem/resistance/predict", json={
                "smiles": args["smiles"], "pdb_id": args["pdb_id"],
            })
        elif name == "harden_atom":
            r = await cx.post(f"{api_base}/workbench/chem/resistance/harden", json={
                "smiles": args["smiles"], "pdb_id": args["pdb_id"],
                "atom_idx": int(args["atom_idx"]), "use_llm": True,
            })
        elif name == "cross_target_risk":
            payload: dict = {"smiles": args["smiles"]}
            if args.get("pdb_ids"):
                payload["pdb_ids"] = args["pdb_ids"]
            r = await cx.post(f"{api_base}/workbench/chem/resistance/cross-target", json=payload)
        elif name == "compare_resistance":
            r = await cx.post(f"{api_base}/workbench/chem/resistance/compare", json={
                "smiles_list": args["smiles_list"],
                "pdb_id": args["pdb_id"],
                "labels": args.get("labels"),
            })
        elif name == "explain_resistance":
            r = await cx.post(f"{api_base}/workbench/chem/resistance/explain", json={
                "smiles": args["smiles"], "pdb_id": args["pdb_id"],
                "session_id": args.get("session_id"),
            })
        elif name == "list_targets":
            r = await cx.get(f"{api_base}/workbench/chem/targets/{args['pathogen']}")
        elif name == "place_in_pocket":
            r = await cx.post(f"{api_base}/workbench/chem/place-in-pocket", json={
                "smiles": args["smiles"], "pdb_id": args["pdb_id"],
            })
        elif name == "molecule_properties":
            # Re-use the deep_properties helper inline by hitting score-explain
            # and stripping the rest. Simpler than a new endpoint.
            r = await cx.post(f"{api_base}/workbench/score-explain", json={
                "smiles": args["smiles"], "target_pathogen": "MRSA",
            })
            if r.status_code == 200:
                d = r.json()
                return {"properties": d.get("rdkit_properties"),
                        "rules": d.get("rules")}
            raise HTTPException(r.status_code, r.text)
        elif name == "analyze_toxicity":
            r = await cx.get(f"{api_base}/workbench/molecule/toxicity",
                             params={"smiles": args["smiles"]})
        elif name == "plan_synthesis":
            r = await cx.post(f"{api_base}/workbench/chem/synthesis/plan", json={
                "smiles": args["smiles"],
                "session_id": args.get("_session_id"),
                "save": True,
            })
        elif name == "check_freedom_to_operate":
            r = await cx.post(f"{api_base}/workbench/chem/ip/fto-scan", json={
                "smiles": args["smiles"],
                "session_id": args.get("_session_id"),
                "save": True,
            })
        elif name == "predict_admet":
            r = await cx.post(f"{api_base}/workbench/chem/admet/panel", json={
                "smiles": args["smiles"],
                "session_id": args.get("_session_id"),
                "save": True,
            })
        elif name == "predict_activity":
            r = await cx.get(f"{api_base}/workbench/chem/activity",
                             params={"smiles": args["smiles"]})
        elif name == "list_axes":
            r = await cx.get(f"{api_base}/workbench/chem/session/__init/axes")
        elif name == "session_pareto_explain":
            sid = args["session_id"]
            r = await cx.post(f"{api_base}/workbench/chem/session/{sid}/pareto/explain", json={
                "candidate_id": args["candidate_id"],
                "x_axis": args.get("x_axis", "predicted_mic"),
                "y_axis": args.get("y_axis", "composite_reward"),
            })
        elif name == "propose_next_action":
            # Local dispatch — queues the proposal in session memory.
            # No external HTTP call; we synthesize a response object.
            from . import session_memory as _sm
            kind = args.get("kind", "load_smiles")
            sid = args.get("_session_id") or ""
            queued = False
            if kind == "load_smiles" and args.get("smiles"):
                _sm.record_proposal(
                    sid,
                    args["smiles"],
                    source="agent",
                    swap_label=args.get("swap_label"),
                    rationale=args.get("rationale"),
                )
                queued = True
            return {
                "ok": True,
                "queued": queued,
                "kind": kind,
                "smiles": args.get("smiles"),
                "workflow_name": args.get("workflow_name"),
                "swap_label": args.get("swap_label"),
                "rationale": args.get("rationale"),
                "user_hint": (
                    "Say 'apply' to load this SMILES into the canvas."
                    if kind == "load_smiles" and queued
                    else "Say 'go ahead' to run this workflow."
                ),
            }
        else:
            raise HTTPException(400, f"unknown tool: {name}")

        if r.status_code != 200:
            raise HTTPException(r.status_code, r.text[:500])
        return r.json()


# ─────────────────────────────────────────────────────────────────────
# SSE streaming endpoint
# ─────────────────────────────────────────────────────────────────────

class AgentRunRequest(BaseModel):
    session_id: str
    text: str
    smiles: Optional[str] = None
    pathogen: Optional[str] = None
    pdb_id: Optional[str] = None
    max_iterations: int = 6


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _agent_loop(req: AgentRunRequest, api_base: str) -> AsyncIterator[str]:
    """The actual streaming generator. Yields SSE lines."""
    started = time.time()
    yield _sse({"event": "agent.start", "session_id": req.session_id,
                "user_text": req.text, "ts": started})

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        yield _sse({"event": "agent.error", "error": "GEMINI_API_KEY not set"})
        yield _sse({"event": "agent.done", "elapsed_ms": 0, "n_tool_calls": 0})
        return

    # Primary + fallback model. Gemini 2.5 Pro hits 503 (Service
    # Unavailable) under load — when that happens we automatically
    # retry the same payload on Gemini 2.5 Flash so the agent loop
    # never silently bails with an empty 0.8s response.
    primary_model = os.getenv("LYSOS_AGENT_GEMINI_MODEL", "gemini-2.5-pro")
    fallback_model = os.getenv("LYSOS_AGENT_GEMINI_FALLBACK", "gemini-2.5-flash")
    def _model_url(m: str) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
    url = _model_url(primary_model)

    system_text = (
        "You are Lysos, an AI medicinal-chemistry research partner specializing "
        "in antimicrobial drug discovery and resistance hardening. You have a "
        "rich toolkit of chemistry endpoints; USE them when relevant rather "
        "than guessing.\n\n"
        f"Current session context:\n"
        f"  session_id: {req.session_id}\n"
        f"  smiles: {req.smiles or '(none)'}\n"
        f"  pathogen: {req.pathogen or 'MRSA'}\n"
        f"  pdb_id: {req.pdb_id or '(none)'}\n\n"
        "## Answer the question that was ASKED\n"
        "Ground every response in the user's EXACT words. If they name a "
        "property — 'the MIC is bad', 'improve drug-likeness', 'is it toxic' "
        "— your answer MUST be about THAT property, by name, with its real "
        "number from a tool result. Do NOT pivot to a different axis just "
        "because it is mathematically weakest: if the user asked about "
        "predicted_mic, LEAD with predicted_mic. You may add 'the lowest "
        "axis overall is X' as a secondary note — never as the headline.\n"
        "NEVER deflect with 'the platform doesn't have an X model' before "
        "checking your tool list. You almost certainly have a tool for it — "
        "see the capability map.\n\n"
        "## Capability map — user concept → tool / axis\n"
        "  • toxicity / safety / side-effects / hERG / cardiotoxicity / "
        "mutagenic / hepatotox / 'is it safe' → call `analyze_toxicity` "
        "(hERG, hepatotox, Ames, skin sensitization). ALSO cite the "
        "`structural_alerts` axis from score_explain — that is the "
        "in-score toxicophore / PAINS signal; a low value means the "
        "molecule HAS alert substructures.\n"
        "  • potency / MIC / activity / 'does it kill the bug' → the "
        "`predicted_mic` axis (score_molecule / score_explain).\n"
        "  • drug-likeness / oral / Lipinski / QED → `drug_likeness_qed` "
        "axis + the Lipinski / Veber / Egan rule flags in score_explain.\n"
        "  • resistance / escape / will-it-survive-mutation → "
        "`predict_resistance`, then `harden_atom` on the weak atoms.\n"
        "  • synthesizability / can-we-make-it → `synthesizability` axis.\n"
        "  • novelty / is-it-new → `novelty` + `embedding_novelty` axes.\n\n"
        "## Plan, then execute\n"
        "Decide WHICH tools to call, in what ORDER, with what ARGS — then "
        "run them. After each result lands, synthesize what you found, cite "
        "the actual numbers, then call the next tool or answer.\n\n"
        "## Final answer shape (standardized — keep it tight, 2-5 sentences)\n"
        "  1. Direct answer to the asked question — name the property and "
        "its actual number.\n"
        "  2. The WHY — the chemistry / structural reason behind that number.\n"
        "  3. The concrete next step (which you have queued via "
        "propose_next_action).\n"
        "No rambling preamble, no 'let me think', no restating the question.\n\n"
        "## STRICT CONTRACT — close the loop\n"
        "**ANYTIME you write a concrete SMILES, suggest a structural "
        "modification, recommend a follow-up workflow, or end an analysis "
        "with anything more than a one-line answer, you MUST call "
        "`propose_next_action` FIRST — before your final user-facing "
        "message.** The proposal queues the move so the user can accept it "
        "with one word ('apply', 'do it', 'go ahead'). Hand-waving like "
        "'future work could focus on...' or 'I'm submitting the following "
        "improved molecule: ...' WITHOUT calling propose_next_action is a "
        "broken contract — the user can't act on it.\n\n"
        "Triggers that REQUIRE propose_next_action:\n"
        "  • You wrote a new SMILES → kind='load_smiles', smiles=<that SMILES>\n"
        "  • You picked a specific swap from harden_atom suggestions → "
        "kind='load_smiles', smiles=<the suggestion's after_smiles>\n"
        "  • You recommend running a workflow → kind='run_workflow', "
        "workflow_name=<harden_candidate | optimize_for_property | ...>\n"
        "The ONLY time you skip propose_next_action is a pure-Q&A turn with "
        "no actionable output (e.g. 'what does MIC mean?').\n\n"
        "## Truncation policy\n"
        "Tool results may include `_truncated_partial: true` along with the "
        "high-signal fields. The summary fields you need (key_contacts, "
        "vulnerable_atoms, binding_atoms, clashing_atoms, composite, "
        "robustness_score, etc.) are ALWAYS preserved. NEVER cite atom "
        "indices, residue numbers, or distances that aren't in the result. "
        "If you need verbose detail that was truncated, re-call the tool "
        "with a narrower scope."
    )

    contents: list[dict] = [
        {"role": "user", "parts": [{"text": req.text}]},
    ]

    n_tool_calls = 0
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}

    for iteration in range(req.max_iterations):
        payload = {
            "system_instruction": {"parts": [{"text": system_text}]},
            "contents": contents,
            "tools": [{"function_declarations": _TOOL_DEFS}],
            "generationConfig": {
                "maxOutputTokens": 8192,
                "temperature": 0.4,
                "thinkingConfig": {"thinkingBudget": 1024, "includeThoughts": True},
            },
        }
        # Try primary; on 503 (Service Unavailable) or 429 (rate limit),
        # fall through to the Flash fallback so the run isn't silently
        # killed by Google's load shedding.
        r = None
        used_model = primary_model
        for attempt_model in (primary_model, fallback_model):
            try:
                async with httpx.AsyncClient(timeout=60.0) as cx:
                    r = await cx.post(_model_url(attempt_model),
                                       headers=headers, json=payload)
            except Exception as exc:
                yield _sse({"event": "agent.error",
                            "error": f"gemini network ({attempt_model}): {exc}"})
                r = None
                break
            if r.status_code == 200:
                used_model = attempt_model
                break
            # Retry-eligible statuses fall through to fallback
            if r.status_code not in (429, 503):
                break
            yield _sse({"event": "agent.fallback",
                        "from": attempt_model, "to": fallback_model,
                        "reason": f"http {r.status_code}"})
        if r is None:
            break
        if r.status_code != 200:
            yield _sse({"event": "agent.error",
                        "error": f"gemini http {r.status_code}: {r.text[:240]}"})
            break

        d = r.json()
        cands = d.get("candidates") or []
        if not cands:
            yield _sse({"event": "agent.error", "error": "gemini empty candidates"})
            break

        cand = cands[0]
        parts = (cand.get("content") or {}).get("parts") or []
        if not parts:
            # Gemini returned a candidate with no content parts. This
            # happens when the model ends a tool-calling turn without a
            # closing message, or hits MAX_TOKENS mid-thinking. If the
            # agent has ALREADY done real work, NEVER dead-end the user
            # with a bare error — force one final text-only call so the
            # analysis actually gets answered. This is the fix for the
            # "agent runs tools then says nothing" broken-response bug.
            finish = cand.get("finishReason") or "unknown"
            if n_tool_calls > 0:
                final_txt = await _force_final_answer(
                    contents, system_text, headers, _model_url,
                    primary_model, fallback_model,
                )
                if final_txt:
                    for chunk in _chunks(final_txt, 80):
                        yield _sse({"event": "text.delta", "text": chunk})
                        await asyncio.sleep(0.01)
                else:
                    yield _sse({"event": "text.delta", "text": (
                        "I ran the analysis — the tool results above carry "
                        "the numbers, but I couldn't compose a summary this "
                        "turn. Ask me to recap and I'll pull it together."
                    )})
                break
            yield _sse({"event": "agent.error",
                        "error": f"gemini empty parts (finishReason={finish})"})
            break

        # Append the model's response to the conversation history
        contents.append({"role": "model", "parts": parts})

        function_call_parts = [p for p in parts if "functionCall" in p]
        text_parts = [p for p in parts if "text" in p]
        thought_parts = [p for p in parts if p.get("thought")]

        # Surface reasoning thoughts FIRST (they're rendered as a
        # collapsible reasoning block in the chat UI).
        for tp in thought_parts:
            t = tp.get("text") or ""
            if t.strip():
                yield _sse({"event": "agent.thinking", "text": t})

        if function_call_parts:
            # Execute each function call, append the result, loop again.
            tool_response_parts: list[dict] = []
            for fp in function_call_parts:
                fc = fp["functionCall"]
                tool_name = fc.get("name") or ""
                tool_args = fc.get("args") or {}
                call_id = uuid.uuid4().hex[:12]
                n_tool_calls += 1
                yield _sse({
                    "event": "tool.call",
                    "call_id": call_id,
                    "tool": tool_name,
                    "args": tool_args,
                })
                t0 = time.perf_counter()
                try:
                    # Thread session_id into EVERY tool call so dispatchers
                    # can bind their output (pending proposals, saved
                    # service artifacts, …) to the right session. Tools
                    # that don't use it simply ignore the extra key.
                    tool_args = {**tool_args, "_session_id": req.session_id}
                    result = await _dispatch_tool(tool_name, tool_args, api_base)
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    yield _sse({
                        "event": "tool.result",
                        "call_id": call_id,
                        "elapsed_ms": elapsed_ms,
                        "result": _truncate_for_event(result),
                    })
                    tool_response_parts.append({
                        "functionResponse": {
                            "name": tool_name,
                            "response": {"result": result},
                        },
                    })
                except HTTPException as exc:
                    err = f"{exc.status_code} {exc.detail}"
                    yield _sse({
                        "event": "tool.error",
                        "call_id": call_id,
                        "error": err,
                    })
                    tool_response_parts.append({
                        "functionResponse": {
                            "name": tool_name,
                            "response": {"error": err},
                        },
                    })
                except Exception as exc:  # noqa: BLE001
                    err = str(exc)[:240]
                    yield _sse({"event": "tool.error", "call_id": call_id, "error": err})
                    tool_response_parts.append({
                        "functionResponse": {
                            "name": tool_name,
                            "response": {"error": err},
                        },
                    })
            # Feed tool responses back so Gemini can synthesize next.
            contents.append({"role": "user", "parts": tool_response_parts})
            continue

        # No more function calls → final assistant text.
        for tp in text_parts:
            txt = tp.get("text") or ""
            # Stream in 80-char chunks to give a "live typing" feel.
            for chunk in _chunks(txt, 80):
                yield _sse({"event": "text.delta", "text": chunk})
                await asyncio.sleep(0.01)
        break  # done

    elapsed_ms = int((time.time() - started) * 1000)
    yield _sse({"event": "agent.done", "elapsed_ms": elapsed_ms, "n_tool_calls": n_tool_calls})


def _chunks(s: str, size: int):
    for i in range(0, len(s), size):
        yield s[i:i + size]


async def _force_final_answer(
    contents: list[dict], system_text: str, headers: dict,
    model_url_fn, primary: str, fallback: str,
) -> str:
    """Last-resort closing call. When the main loop gets an empty-parts
    response AFTER tool calls, this fires one more Gemini request with
    NO tools (so the model CANNOT function-call — it must emit text)
    and zero thinking budget (straight to the answer). Returns the
    text, or '' if even this fails. This guarantees a tool-using turn
    never dead-ends with silence."""
    msgs = contents + [{
        "role": "user",
        "parts": [{"text": (
            "Write your final answer to the user NOW, using the tool "
            "results above. 2-5 sentences. Name the property the user "
            "asked about and cite its actual number. Do not call any "
            "tools — just answer."
        )}],
    }]
    payload = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": msgs,
        "generationConfig": {
            "maxOutputTokens": 2048,
            "temperature": 0.4,
            "thinkingConfig": {"thinkingBudget": 0, "includeThoughts": False},
        },
    }
    for m in (primary, fallback):
        try:
            async with httpx.AsyncClient(timeout=45.0) as cx:
                r = await cx.post(model_url_fn(m), headers=headers, json=payload)
            if r.status_code != 200:
                continue
            cands = r.json().get("candidates") or []
            if not cands:
                continue
            parts = (cands[0].get("content") or {}).get("parts") or []
            txt = "".join(p.get("text", "") for p in parts if "text" in p)
            if txt.strip():
                return txt.strip()
        except Exception:  # noqa: BLE001
            continue
    return ""


# Engineered truncation — preserve high-signal summary fields even
# when the verbose raw arrays get clipped. Without this, oversized tool
# results (e.g. place_in_pocket with 152 contacts) collapsed into a
# 6-KB string preview, and the UI lost the clash_atoms / binding_atoms
# / key_contacts arrays that the agent's narration actually cites.
_KEEP_FIELDS_VERBATIM = {
    # Scoring
    "composite", "weakest", "strongest", "components", "axis_reasoning",
    "rdkit_properties", "rules",
    # Resistance
    "robustness_score", "n_escape_vectors", "vulnerable_atoms",
    "clinical_overlap", "drug_class_profile", "summary",
    "n_total_known_mutations", "n_residues_with_contacts",
    # Pose / contacts
    "pose_score", "n_contacts", "n_clashes", "key_contacts",
    "binding_atoms", "clashing_atoms", "target_name", "pathogen",
    # Hardening
    "weak_atoms", "n_vulnerable_total", "max_atoms",
    "gemini_suggestions", "playbook_suggestions", "suggestions",
    "after_smiles", "proposed_smiles", "mechanism",
    "predicted_robustness_delta", "confidence", "swap", "rationale",
    # Workflow
    "ranking", "candidates", "winner", "runner_up", "next_action",
    # Identifiers — never truncate
    "smiles", "pdb_id", "atom_idx", "atom_index",
}

_DROP_FIELDS = {
    # Noisy internals the agent doesn't need to reason from
    "_factors", "all_residue_scores", "contact_residue_details",
    "contacts",  # huge — `key_contacts` carries the signal
    "clashes",   # huge — `clashing_atoms` carries the signal
}


def _truncate_for_event(obj: Any, max_chars: int = 6000) -> Any:
    """Smart compaction:
    1. Drop verbose internal fields the agent doesn't read from.
    2. Keep all high-signal summary fields verbatim (key_contacts,
       vulnerable_atoms, etc.).
    3. If the result is STILL too big, cap arrays at 8 items each.
    4. As last resort, emit a preview envelope — but it's now a
       dict that retains the kept fields PLUS the preview.

    Note: this only affects the SSE event sent to the UI for display.
    The agent's tool_response_parts (line ~445) still get the FULL
    untouched result.
    """
    def _compact(o: Any, depth: int = 0) -> Any:
        if depth > 6:
            return "..."
        if isinstance(o, dict):
            out: dict[str, Any] = {}
            for k, v in o.items():
                if k in _DROP_FIELDS:
                    continue
                out[k] = _compact(v, depth + 1)
            return out
        if isinstance(o, list):
            return [_compact(x, depth + 1) for x in o]
        return o

    try:
        compacted = _compact(obj)
        as_str = json.dumps(compacted)
        if len(as_str) <= max_chars:
            return compacted
        # Still too big — cap arrays at 8 items
        def _cap_arrays(o: Any, depth: int = 0) -> Any:
            if depth > 6:
                return "..."
            if isinstance(o, dict):
                return {k: _cap_arrays(v, depth + 1) for k, v in o.items()}
            if isinstance(o, list):
                return [_cap_arrays(x, depth + 1) for x in o[:8]]
            return o
        capped = _cap_arrays(compacted)
        as_str = json.dumps(capped)
        if len(as_str) <= max_chars:
            return capped
        # Final fallback — preserve top-level scalar/short fields and
        # a preview of the rest. The agent / UI still gets composite,
        # robustness, pose_score, n_clashes, etc. as first-class.
        if isinstance(capped, dict):
            keep: dict[str, Any] = {"_truncated_partial": True}
            for k, v in capped.items():
                if k in _KEEP_FIELDS_VERBATIM and not isinstance(v, (list, dict)):
                    keep[k] = v
            keep["_len"] = len(as_str)
            keep["_preview"] = as_str[:max_chars]
            return keep
        return {"_truncated": True, "_len": len(as_str),
                "preview": as_str[:max_chars]}
    except Exception:
        return {"_unserializable": True}


@router.post("/run")
async def agent_run(req: AgentRunRequest) -> StreamingResponse:
    """Stream an agent execution as Server-Sent Events."""
    api_base = os.getenv("LYSOS_INTERNAL_API_BASE", "http://127.0.0.1:7860")
    return StreamingResponse(
        _agent_loop(req, api_base),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/tools")
async def list_agent_tools() -> dict:
    """Return the tool registry for the chat UI (used by the slash palette
    and the 'agent skills' panel). Each tool exposes its name, description,
    and JSON-schema parameters."""
    return {"tools": _TOOL_DEFS}
