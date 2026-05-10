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
        elif name == "list_axes":
            r = await cx.get(f"{api_base}/workbench/chem/session/__init/axes")
        elif name == "session_pareto_explain":
            sid = args["session_id"]
            r = await cx.post(f"{api_base}/workbench/chem/session/{sid}/pareto/explain", json={
                "candidate_id": args["candidate_id"],
                "x_axis": args.get("x_axis", "predicted_mic"),
                "y_axis": args.get("y_axis", "composite_reward"),
            })
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

    model_id = os.getenv("LYSOS_AGENT_GEMINI_MODEL", "gemini-2.5-pro")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"

    system_text = (
        "You are Lysos, an AI medicinal-chemistry research partner specializing "
        "in antimicrobial drug discovery and resistance hardening. You have a "
        "rich toolkit of chemistry endpoints; USE them when relevant rather "
        "than guessing. After each tool call's result lands, synthesize what "
        "you found, then either call another tool or reply to the user.\n\n"
        f"Current session context:\n"
        f"  smiles: {req.smiles or '(none)'}\n"
        f"  pathogen: {req.pathogen or 'MRSA'}\n"
        f"  pdb_id: {req.pdb_id or '(none)'}\n"
        f"\nWhen the user asks a question, plan: WHICH tools should I call, in "
        f"what ORDER, with what ARGS? Then execute. Cite numerical results in "
        f"your final answer. Be concise but rigorous."
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
        try:
            async with httpx.AsyncClient(timeout=60.0) as cx:
                r = await cx.post(url, headers=headers, json=payload)
        except Exception as exc:
            yield _sse({"event": "agent.error", "error": f"gemini network: {exc}"})
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
            yield _sse({"event": "agent.error", "error": "gemini empty parts"})
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


def _truncate_for_event(obj: Any, max_chars: int = 6000) -> Any:
    """Rough payload size guard so SSE events don't blow up the connection."""
    try:
        as_str = json.dumps(obj)
        if len(as_str) <= max_chars:
            return obj
        return {"_truncated": True, "_len": len(as_str), "preview": as_str[:max_chars]}
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
