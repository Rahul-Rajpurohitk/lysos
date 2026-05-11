"""Orchestrator agent — plain-English prompt → routed execution.

The orchestrator is the **front door** for the chat. The user types
plain English (no `/` prefix); the orchestrator:

  1. Reads the prompt + session context (current SMILES, pathogen, last
     candidates, last score, last harden, etc.).
  2. Calls Gemini Pro with structured-output (JSON mode) to classify
     intent and pick a route. Routes:
        - "workflow"     run a registered Workflow (best for multi-step plans)
        - "slash"        translate to a /command (lowest-friction; the
                         existing chat-side handler already does the
                         heavy lifting)
        - "agent"        run the Gemini tool-calling agent loop (the user
                         is asking an open-ended question that needs
                         flexible tool-calls)
        - "answer"       no execution needed — just answer in prose (the
                         user is asking "what does X mean", "explain Y").
  3. Emits an `orchestrator.plan` SSE event with the rationale + route
     choice so the chat UI can show the routing decision visibly
     (Claude/Cursor style "I'm going to use the harden_candidate
     workflow because…").
  4. Dispatches the chosen route via internal HTTP to the corresponding
     existing endpoint (`/api/agent/run`, `/api/workflows/run`, …) and
     forwards every downstream SSE event verbatim, prefixed with the
     run_id so the frontend can graft them under the orchestrator card.
  5. Emits `orchestrator.done` when the dispatched route finishes.

Why a separate endpoint and not just the agent loop? Because the agent
loop is a *single* Gemini call with tools. The orchestrator gives the
user explicit visibility into routing — "this prompt → workflow vs.
slash vs. plain answer" — which is the missing piece for product-grade
agentic UX. It also lets us pick the fast path (a single slash
dispatch) when the prompt is unambiguous, instead of always paying the
agent-loop tax.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Any, AsyncIterator, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import session_memory, agent_activity

log = logging.getLogger("api.orchestrator")
router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


# ─────────────────────────────────────────────────────────────────────
# Route catalog — what the orchestrator can pick from. Kept in lockstep
# with workspace/api/workflows.py and the slash-command registry.
# ─────────────────────────────────────────────────────────────────────

_KNOWN_WORKFLOWS = [
    {
        "name": "design_with_debate",
        "description": "Multi-agent debate (Designer drafts → Critic challenges → Editor refines → Strategist crowns winner) — use this for any 'design / propose / make me a molecule' intent. This is the agentic flow that lights up all 4 roles.",
        "intent_phrases": ["design", "propose", "make me a molecule", "create a molecule",
                           "generate a candidate", "better than the seed", "improve on this"],
        "inputs": {"pathogen": "MRSA"},
    },
    {
        "name": "discover_and_assess",
        "description": "Generate fresh candidates from a SMILES generator (no debate), score them, screen for resistance. Use only if user explicitly asks for a 'broad candidate sweep' rather than agentic design.",
        "intent_phrases": ["broad sweep", "candidate sweep", "bulk discover"],
        "inputs": {"pathogen": "MRSA", "objective": "β-lactam"},
    },
    {
        "name": "harden_candidate",
        "description": "Take an existing SMILES, find the worst escape vulnerability, and propose hardened variants (Gemini + playbook).",
        "intent_phrases": ["harden", "make resistant", "fix vulnerability", "escape-proof"],
        "inputs": {"smiles": "<current>", "pathogen": "MRSA"},
    },
    {
        "name": "broad_spectrum_screen",
        "description": "Test a SMILES against a list of pathogens for cross-target risk + spectrum coverage.",
        "intent_phrases": ["broad spectrum", "test on multiple", "cross target", "spectrum"],
        "inputs": {"smiles": "<current>", "pathogens": ["MRSA", "EColi-CRE"]},
    },
    {
        "name": "compare_top_n",
        "description": "Side-by-side compare top N candidates from this session on per-axis scores + Pareto rank.",
        "intent_phrases": ["compare", "best of", "top candidates", "side by side"],
        "inputs": {"n": 3},
    },
    {
        "name": "optimize_for_property",
        "description": "Iteratively edit a SMILES to improve a chosen reward axis (e.g. drug-likeness, predicted MIC).",
        "intent_phrases": ["improve", "optimize", "boost", "increase score"],
        "inputs": {"smiles": "<current>", "axis": "predicted_mic"},
    },
]

_KNOWN_SLASH = [
    {"cmd": "/help",
     "phrases": ["help", "what can you do", "what commands", "list commands",
                 "tell me which commands", "available commands", "options"],
     "args_hint": "/help",
     "what_it_does": "List every registered slash command + workflow with descriptions. Use when the user asks 'what can you do', 'which commands', 'list commands', or types /help.",
    },
    {"cmd": "/trace",
     "phrases": ["trace", "agent traces", "agent history", "show traces",
                 "what did the agents do", "check traces", "recent events"],
     "args_hint": "/trace [n]",
     "what_it_does": "Return the last N harness events: tool calls, agent messages, errors. Use when the user asks for traces / history / 'what did the agents do recently'.",
    },
    {"cmd": "/score",
     "phrases": ["score", "evaluate", "rate this", "assess", "grade"],
     "args_hint": "/score <smiles>",
     "what_it_does": "12-axis composite scoring (activity, novelty, drug-likeness, ADMET, safety) for ONE SMILES. Use when user wants a single quality readout.",
    },
    {"cmd": "/explain",
     "phrases": ["explain target", "tell me about target", "what is mecA",
                 "what is PBP2a", "explain gene", "explain pathogen"],
     "args_hint": "/explain <pathogen | gene | PDB>",
     "what_it_does": "Pull a structured BRIEF on a TARGET (pathogen / gene / PDB id). Does NOT accept SMILES — for molecules use /score. Use when user asks about a biological target.",
    },
    {"cmd": "/load",
     "phrases": ["show", "visualize", "render", "display", "load this",
                 "open in 2d", "open in 3d", "see the molecule",
                 "show the structure", "apply", "apply that",
                 "apply the suggestion", "do it", "go ahead",
                 "use that one", "then apply", "make the change"],
     "args_hint": "/load <smiles>",
     "what_it_does": "Load a SMILES into the 2D + 3D viewers and auto-score it. ALSO use when the user says 'apply', 'apply that', 'do it', 'go ahead' — pull the most-recently mentioned SMILES from the recent_messages context and dispatch /load with it. Use when the user wants to SEE / VISUALIZE / DISPLAY / APPLY a molecule on the canvas.",
    },
    {"cmd": "/harden",
     "phrases": ["harden", "make resistant", "fix vulnerability", "escape proof"],
     "args_hint": "/harden [smiles] [pdb=1VQQ]",
     "what_it_does": "Find weak atoms in the current candidate and propose hardening edits. Uses ambient SMILES if not given.",
    },
    # /design intentionally NOT routed here — design intents go to the
    # design_with_debate workflow above so the user sees the full
    # Designer→Critic→Editor→Strategist flow in the Agents tab.
    {"cmd": "/champion",
     "phrases": ["champion", "current best", "reigning"],
     "args_hint": "/champion [pathogen]",
     "what_it_does": "Show the reigning best candidate for a pathogen (auto-promoted from session winners).",
    },
]


def _build_routing_system_prompt() -> str:
    wf_list = "\n".join(f"  - {w['name']}: {w['description']}" for w in _KNOWN_WORKFLOWS)
    slash_list = "\n".join(
        f"  - {s['cmd']} ({s.get('args_hint', s['cmd'])}): "
        f"{s.get('what_it_does', '')}"
        for s in _KNOWN_SLASH
    )
    return (
        "You are the Lysos Orchestrator. Your job is to ROUTE a free-text user "
        "prompt to one of four execution paths. You DO NOT execute the work "
        "yourself — you only pick the route + the inputs.\n\n"
        "Routes:\n"
        '  1. "workflow"  — multi-step pipeline (best for plans that need '
        "score → resistance → harden → compare in one shot).\n"
        '  2. "slash"     — single-purpose command (when the user wants ONE '
        "thing: just score, just explain, just spectrum). Faster path.\n"
        '  3. "agent"     — Gemini tool-calling loop (open-ended questions, '
        "exploratory, multiple unknowns).\n"
        '  4. "answer"    — no execution; just answer in prose. Use this for '
        "definitions, explanations of generic concepts, conversational replies.\n\n"
        f"Available workflows:\n{wf_list}\n\n"
        f"Available slash commands:\n{slash_list}\n\n"
        "Output STRICT JSON:\n"
        "{\n"
        '  "route": "workflow" | "slash" | "agent" | "answer",\n'
        '  "rationale": "<one short sentence WHY this route>",\n'
        '  "name": "<workflow name OR slash cmd OR null>",\n'
        '  "inputs": { ...args for the chosen route... },\n'
        '  "answer": "<only set if route=answer; the prose to display>"\n'
        "}\n\n"
        "Rules:\n"
        "  - When the user's text STARTS WITH a literal slash (e.g. `/help`, "
        "`/score c1ccccc1`, `/champion MRSA`), ALWAYS pick route='slash' and "
        "set name to the slash they typed (lowercased, with the leading /). "
        "Don't second-guess the user — they explicitly asked for that command. "
        "If the slash isn't in the registry above, fall back to the most "
        "relevant workflow or the agent route.\n"
        "  - PREFER 'slash' when the prompt clearly maps to one command.\n"
        "  - PREFER 'workflow' when the user wants a multi-step outcome (e.g. "
        "'find me a beta-lactam for MRSA and harden it').\n"
        "  - 'agent' is for ambiguous prompts where you genuinely need to "
        "decide between multiple tool calls.\n"
        "  - 'answer' for definitions / chitchat / conceptual questions that "
        "don't require a tool. Cite the molecule + pathogen context if "
        "relevant.\n"
        "  - For workflow inputs, map session context onto required args. If "
        "smiles is needed but missing, fall back to slash:/design.\n"
        "  - For slash, the 'inputs' object should match the command's "
        "argument syntax — for /score, return inputs={\"smiles\": ...}.\n"
        "  - DO NOT invent workflow names. Pick from the list above ONLY.\n"
        "  - CRITICAL distinction:\n"
        "      • SHOW / VISUALIZE / DISPLAY / RENDER a SMILES → /load (NEVER "
        "/explain — /explain is for biological targets, not molecules).\n"
        "      • EXPLAIN a target/gene/PDB (mecA, PBP2a, 1VQQ) → /explain.\n"
        "      • Score a SMILES → /score.\n"
        "      • 'apply', 'apply that', 'apply the suggestion', 'do it', "
        "'go ahead', 'then apply', 'use that one' → route='slash', "
        "name='/load', inputs={smiles: <THE MOST RECENT SMILES SUGGESTED "
        "in recent_messages>}. Scan recent_messages for the LAST SMILES "
        "the editor/critic proposed (anything inside `backticks` that "
        "parses as SMILES, especially after 'I'd apply' or 'New "
        "structure:'). NEVER route 'apply' to optimize_for_property or "
        "any workflow — apply means LOAD THE MOLECULE, not start a new "
        "workflow.\n"
        "      • If the user says 'execute the recommendation' or 'do the "
        "improvement you suggested', and they want a NEW design loop "
        "(not just loading a candidate), pick a workflow.\n"
    )


# ─────────────────────────────────────────────────────────────────────
# Heuristic fallback — used when GEMINI_API_KEY is missing or the
# Gemini call fails. Cheap pattern matching that still gives the user
# *something* useful instead of crashing.
# ─────────────────────────────────────────────────────────────────────

_SMILES_RE = re.compile(r"\b[A-Za-z0-9@+\-\[\]\(\)=#$/\\.]{4,}\b")


def _heuristic_route(text: str, ctx: dict[str, Any]) -> dict:
    t = text.lower().strip()
    smi = ctx.get("smiles")

    # 1) Direct slash passthrough — user already typed one
    if t.startswith("/"):
        m = re.match(r"^/(\w+)\s*(.*)$", t)
        if m:
            return {
                "route": "slash",
                "rationale": "User explicitly used a slash command.",
                "name": f"/{m.group(1)}",
                "inputs": {"raw": m.group(2).strip()},
            }

    # 2) Workflow phrase match — score the prompt against each workflow's
    #    intent_phrases and pick the best.
    best: tuple[int, dict | None] = (0, None)
    for wf in _KNOWN_WORKFLOWS:
        score = sum(1 for ph in wf["intent_phrases"] if ph in t)
        if score > best[0]:
            best = (score, wf)
    if best[1] is not None:
        wf = best[1]
        inputs = dict(wf["inputs"])
        if "<current>" in inputs.values():
            for k, v in inputs.items():
                if v == "<current>":
                    inputs[k] = smi or ""
        if "pathogen" in inputs and ctx.get("pathogen"):
            inputs["pathogen"] = ctx["pathogen"]
        return {
            "route": "workflow",
            "rationale": f"Matched intent '{wf['intent_phrases'][0]}' → workflow {wf['name']}.",
            "name": wf["name"],
            "inputs": inputs,
        }

    # 3) Slash-command phrase match
    for sc in _KNOWN_SLASH:
        for ph in sc["phrases"]:
            if ph in t:
                args: dict[str, Any] = {}
                if sc["cmd"] in ("/score", "/harden"):
                    args["smiles"] = smi or ""
                if sc["cmd"] == "/spectrum":
                    args["smiles"] = smi or ""
                return {
                    "route": "slash",
                    "rationale": f"Matched phrase '{ph}' → command {sc['cmd']}.",
                    "name": sc["cmd"],
                    "inputs": args,
                }

    # 4) Fallback — let the agent loop figure it out
    return {
        "route": "agent",
        "rationale": "No clear workflow / slash match — running the Gemini tool-calling agent.",
        "name": None,
        "inputs": {},
    }


# ─────────────────────────────────────────────────────────────────────
# Gemini routing call — structured output (JSON mode)
# ─────────────────────────────────────────────────────────────────────

async def _gemini_route(text: str, ctx: dict[str, Any], session_id: Optional[str] = None) -> dict:
    """Ask Gemini Pro to classify intent + pick a route. Returns the
    parsed JSON plan, or raises on failure. Pulls the session memory
    brief so the model has cross-turn continuity (last SMILES, last
    score, recent harden, recent workflows)."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing")

    # Primary + fallback. Gemini 2.5 Pro hits 503 under demand; auto-
    # retry the routing call on Flash so the orchestrator never
    # silently fails over to the heuristic-only path.
    primary_model = os.getenv("LYSOS_ORCHESTRATOR_MODEL", "gemini-2.5-pro")
    fallback_model = os.getenv("LYSOS_ORCHESTRATOR_FALLBACK", "gemini-2.5-flash")
    def _model_url(m: str) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
    url = _model_url(primary_model)

    system_text = _build_routing_system_prompt()
    memory_brief = session_memory.brief(session_id) if session_id else ""
    ctx_block = (
        f"Session context:\n"
        f"  current_smiles: {ctx.get('smiles') or '(none)'}\n"
        f"  pathogen: {ctx.get('pathogen') or 'MRSA'}\n"
        f"  last_composite: {ctx.get('last_composite') if ctx.get('last_composite') is not None else '(unscored)'}\n"
        f"  candidate_count: {ctx.get('n_candidates', 0)}\n"
    )
    if memory_brief:
        ctx_block += "\n" + memory_brief + "\n"

    # Recent visible chat messages so the orchestrator agent can ground
    # follow-up turns (e.g. "score the other one", "tell me which
    # commands you can run") in what's already on screen. The frontend
    # ships oldest→newest. Cap at 12 to keep latency low.
    recent_msgs = ctx.get("recent_messages") or []
    if recent_msgs:
        lines = ["", "Recent chat (oldest → newest):"]
        for m in recent_msgs[-12:]:
            if not isinstance(m, dict):
                continue
            a = (m.get("agent") or "system").lower()
            c = (m.get("content") or "").strip().replace("\n", " ")
            if not c:
                continue
            if len(c) > 280:
                c = c[:277] + "…"
            lines.append(f"  - {a}: {c}")
        ctx_block += "\n".join(lines) + "\n"

    payload = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": f"{ctx_block}\n\nUser prompt:\n{text}"}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 4096,
            "temperature": 0.2,
            "thinkingConfig": {"thinkingBudget": 1024, "includeThoughts": False},
        },
    }
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    r = None
    for attempt_model in (primary_model, fallback_model):
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.post(_model_url(attempt_model), headers=headers, json=payload)
        if r.status_code == 200:
            break
        if r.status_code not in (429, 503):
            break
        log.warning("gemini routing %s returned %d; falling back to %s",
                    attempt_model, r.status_code, fallback_model)
    if r is None or r.status_code != 200:
        code = r.status_code if r is not None else 0
        body = r.text[:200] if r is not None else "no response"
        raise RuntimeError(f"gemini http {code}: {body}")
    body = r.json()
    cands = body.get("candidates", [])
    if not cands:
        raise RuntimeError("no candidates from gemini")
    parts = (cands[0].get("content") or {}).get("parts") or []
    txt = ""
    for p in parts:
        t = p.get("text")
        if t:
            txt += t
    if not txt:
        raise RuntimeError("empty gemini response text")
    # Sometimes Gemini wraps the JSON in fenced code blocks even with
    # responseMimeType=json. Strip defensively.
    s = txt.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.M).strip()
    try:
        plan = json.loads(s)
    except json.JSONDecodeError:
        raise RuntimeError(f"orchestrator JSON parse failed: {s[:200]}")

    # Sanitize / clamp to known routes
    route = (plan.get("route") or "").strip().lower()
    if route not in {"workflow", "slash", "agent", "answer"}:
        raise RuntimeError(f"orchestrator returned invalid route: {route}")
    plan["route"] = route
    # Surface usage so the caller can record token spend in agent activity.
    usage = body.get("usageMetadata") or {}
    plan["_usage"] = {
        "tokens_in":  int(usage.get("promptTokenCount") or 0),
        "tokens_out": int(usage.get("candidatesTokenCount") or 0),
        "tokens_total": int(usage.get("totalTokenCount") or 0),
    }
    return plan


# ─────────────────────────────────────────────────────────────────────
# SSE plumbing — turn dicts into `data: ...\n\n` lines
# ─────────────────────────────────────────────────────────────────────

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# ─────────────────────────────────────────────────────────────────────
# Endpoint: POST /api/orchestrator/run (SSE)
# ─────────────────────────────────────────────────────────────────────

class OrchestratorRunRequest(BaseModel):
    session_id: str
    text: str
    smiles: Optional[str] = None
    pathogen: Optional[str] = None
    pdb_id: Optional[str] = None
    last_composite: Optional[float] = None
    n_candidates: int = 0
    # Recent visible chat messages for conversational grounding. The
    # orchestrator agent needs to see "what was the previous turn
    # about" to handle follow-ups like "check this one" or "now do
    # that for the other one." Frontend ships last ~12 visible
    # messages oldest→newest.
    recent_messages: Optional[list[dict]] = None


async def _orchestrator_loop(req: OrchestratorRunRequest, api_base: str) -> AsyncIterator[str]:
    started = time.time()
    run_id = uuid.uuid4().hex[:10]
    yield _sse({
        "event": "orchestrator.start",
        "run_id": run_id,
        "session_id": req.session_id,
        "user_text": req.text,
        "ts": started,
    })

    # Record the user prompt in session memory so future turns get
    # conversational context. Also record the current SMILES if known.
    session_memory.record(req.session_id, "user", {"text": req.text})
    if req.smiles:
        session_memory.record(req.session_id, "load", {"smiles": req.smiles})

    ctx = {
        "smiles": req.smiles,
        "pathogen": req.pathogen,
        "last_composite": req.last_composite,
        "n_candidates": req.n_candidates,
        "recent_messages": req.recent_messages or [],
    }

    # ── Pending-proposal fast path ──
    # If the user typed a short accept phrase and there's a queued
    # proposal from the agent (editor swap, etc.), route directly to
    # /load with that SMILES. No Gemini round-trip needed — the
    # proposal is ground truth. Pops the queue so the same accept
    # phrase doesn't re-fire the same load.
    plan: dict[str, Any]
    plan_source = "gemini"
    accept_re = re.compile(
        r"^(apply|apply that|apply it|do it|go ahead|then apply|"
        r"yes apply|yes do it|use that|use that one|make the change|"
        r"ship|ship it|ship the winner|ship this|lets ship|let's ship|"
        r"approved|accept|accept it|ok apply|ok ship)\.?\s*$",
        re.IGNORECASE,
    )
    if accept_re.match((req.text or "").strip()):
        pending = session_memory.pop_proposal(req.session_id or "")
        if pending and pending.get("smiles"):
            plan = {
                "route": "slash",
                "rationale": (
                    f"User accepted the pending {pending.get('source', 'agent')} "
                    f"proposal '{pending.get('swap_label') or 'swap'}'."
                ),
                "name": "/load",
                "inputs": {"smiles": pending["smiles"]},
            }
            plan_source = "pending-proposal-fastpath"

    if plan_source == "gemini":
        try:
            plan = await _gemini_route(req.text, ctx, session_id=req.session_id)
        except Exception as exc:
            log.warning("gemini routing failed (%s) — falling back to heuristic", exc)
            plan = _heuristic_route(req.text, ctx)
            plan_source = f"heuristic (gemini: {exc})"

    # Record the routing decision so future turns know what the
    # orchestrator did last time.
    session_memory.record(req.session_id, "workflow", {
        "name": plan.get("name") or plan.get("route") or "?",
        "route": plan.get("route"),
        "status": "started",
    })
    # Record an "orchestrator route" action so the Agents container
    # shows the orchestrator role lighting up immediately.
    usage = plan.get("_usage") or {}
    agent_activity.record(
        req.session_id, "orchestrator", "route",
        message=f"→ {plan.get('route')} :: {plan.get('name') or '∅'} — {plan.get('rationale', '')}"[:240],
        confidence=0.85,
        elapsed_ms=int((time.time() - started) * 1000),
        references={"plan_source": plan_source, "inputs": plan.get("inputs") or {}},
        tokens_in=int(usage.get("tokens_in") or 0),
        tokens_out=int(usage.get("tokens_out") or 0),
        triggered_by="user",
        parent_run_id=run_id,
        tags=["gemini", "routing"],
    )

    yield _sse({
        "event": "orchestrator.plan",
        "run_id": run_id,
        "plan": plan,
        "plan_source": plan_source,
    })

    route = plan.get("route")
    name = plan.get("name")
    inputs = plan.get("inputs") or {}

    # ─── Route 1: ANSWER (prose-only, no execution) ─────────────────
    if route == "answer":
        answer_text = (plan.get("answer") or "").strip()
        if not answer_text:
            answer_text = "I don't need to run any tools for this — but I also don't have a prepared answer. Try rephrasing."
        yield _sse({
            "event": "orchestrator.answer",
            "run_id": run_id,
            "text": answer_text,
        })
        yield _sse({
            "event": "orchestrator.done",
            "run_id": run_id,
            "elapsed_ms": int((time.time() - started) * 1000),
        })
        return

    # ─── Route 2: WORKFLOW ──────────────────────────────────────────
    if route == "workflow":
        if not name:
            yield _sse({"event": "orchestrator.error", "run_id": run_id,
                        "error": "workflow route picked but no workflow name"})
            yield _sse({"event": "orchestrator.done", "run_id": run_id,
                        "elapsed_ms": int((time.time() - started) * 1000)})
            return
        # Forward downstream SSE from /api/workflows/run, prefixing each
        # event with our run_id so the chat UI can hang sub-events under
        # the orchestrator card.
        async for line in _stream_post(
            f"{api_base}/api/workflows/run",
            {"session_id": req.session_id, "name": name, "inputs": inputs},
            run_id,
            "workflow",
        ):
            yield line
        yield _sse({"event": "orchestrator.done", "run_id": run_id,
                    "elapsed_ms": int((time.time() - started) * 1000)})
        return

    # ─── Route 3: AGENT (Gemini tool-calling loop) ──────────────────
    if route == "agent":
        async for line in _stream_post(
            f"{api_base}/api/agent/run",
            {
                "session_id": req.session_id,
                "text": req.text,
                "smiles": req.smiles,
                "pathogen": req.pathogen,
                "pdb_id": req.pdb_id,
            },
            run_id,
            "agent",
        ):
            yield line
        yield _sse({"event": "orchestrator.done", "run_id": run_id,
                    "elapsed_ms": int((time.time() - started) * 1000)})
        return

    # ─── Route 4: SLASH ─────────────────────────────────────────────
    if route == "slash":
        # The slash route is delivered AS-IS to the chat UI, which
        # already knows how to dispatch /score, /explain, /design, etc.
        # We emit a single `orchestrator.dispatch_slash` event with the
        # rendered command line; the frontend handler swaps the input
        # and submits.
        cmd_name = name or "/help"
        if not cmd_name.startswith("/"):
            cmd_name = f"/{cmd_name}"
        # Compose an arg string from inputs.
        if cmd_name in ("/score", "/harden") and inputs.get("smiles"):
            arg = inputs["smiles"]
        elif cmd_name == "/spectrum" and inputs.get("smiles"):
            arg = inputs["smiles"]
        elif cmd_name == "/explain" and inputs.get("target"):
            arg = inputs["target"]
        elif "raw" in inputs:
            arg = inputs["raw"]
        else:
            arg = " ".join(str(v) for v in inputs.values() if v)
        rendered = f"{cmd_name} {arg}".strip()
        yield _sse({
            "event": "orchestrator.dispatch_slash",
            "run_id": run_id,
            "command": cmd_name,
            "args": inputs,
            "rendered": rendered,
        })
        yield _sse({"event": "orchestrator.done", "run_id": run_id,
                    "elapsed_ms": int((time.time() - started) * 1000)})
        return

    yield _sse({"event": "orchestrator.error", "run_id": run_id,
                "error": f"unknown route '{route}'"})
    yield _sse({"event": "orchestrator.done", "run_id": run_id,
                "elapsed_ms": int((time.time() - started) * 1000)})


async def _stream_post(
    url: str,
    json_body: dict,
    run_id: str,
    sub_kind: str,
) -> AsyncIterator[str]:
    """Open a streamed POST to an internal SSE endpoint and yield each
    forwarded line as an `orchestrator.delegate` event so the frontend
    can graft the sub-events under the orchestrator card. Each
    forwarded event includes the parent run_id + sub_kind."""
    try:
        async with httpx.AsyncClient(timeout=None) as cx:
            async with cx.stream("POST", url, json=json_body) as r:
                if r.status_code != 200:
                    body = await r.aread()
                    yield _sse({
                        "event": "orchestrator.error",
                        "run_id": run_id,
                        "sub_kind": sub_kind,
                        "error": f"http {r.status_code}: {body[:200].decode('utf-8', 'replace')}",
                    })
                    return
                async for raw in r.aiter_lines():
                    if not raw:
                        continue
                    if raw.startswith("data: "):
                        try:
                            payload = json.loads(raw[6:])
                        except json.JSONDecodeError:
                            continue
                        yield _sse({
                            "event": "orchestrator.delegate",
                            "run_id": run_id,
                            "sub_kind": sub_kind,
                            "sub_event": payload,
                        })
    except Exception as exc:
        yield _sse({
            "event": "orchestrator.error",
            "run_id": run_id,
            "sub_kind": sub_kind,
            "error": f"stream exception: {exc}",
        })


@router.post("/run")
async def orchestrator_run(req: OrchestratorRunRequest) -> StreamingResponse:
    """Stream an orchestrator run as SSE."""
    api_base = os.getenv("LYSOS_INTERNAL_API_BASE", "http://127.0.0.1:7860")
    return StreamingResponse(
        _orchestrator_loop(req, api_base),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Endpoint: POST /api/orchestrator/route — non-streaming, single shot
# (returns the routing JSON without dispatching).  Useful when the
# frontend only wants to PREVIEW the orchestrator's plan.
# ─────────────────────────────────────────────────────────────────────

class RouteOnlyRequest(BaseModel):
    text: str
    smiles: Optional[str] = None
    pathogen: Optional[str] = None
    last_composite: Optional[float] = None
    n_candidates: int = 0
    session_id: Optional[str] = None
    # Recent chat history so 'apply that' / 'do it' can resolve which
    # SMILES the editor suggested last.
    recent_messages: Optional[list[dict]] = None


@router.post("/route")
async def route_only(req: RouteOnlyRequest) -> dict:
    ctx = {
        "smiles": req.smiles,
        "pathogen": req.pathogen,
        "last_composite": req.last_composite,
        "n_candidates": req.n_candidates,
        "recent_messages": req.recent_messages or [],
    }
    # Mirror the recording behavior of /run so /route also builds session
    # memory. Some preview/fast-path callers only use /route.
    if req.session_id:
        session_memory.record(req.session_id, "user", {"text": req.text})
        if req.smiles:
            session_memory.record(req.session_id, "load", {"smiles": req.smiles})

    # Pending-proposal fast path — see /run for full reasoning.
    accept_re = re.compile(
        r"^(apply|apply that|apply it|do it|go ahead|then apply|"
        r"yes apply|yes do it|use that|use that one|make the change|"
        r"ship|ship it|ship the winner|ship this|lets ship|let's ship|"
        r"approved|accept|accept it|ok apply|ok ship)\.?\s*$",
        re.IGNORECASE,
    )
    if accept_re.match((req.text or "").strip()):
        pending = session_memory.pop_proposal(req.session_id or "")
        if pending and pending.get("smiles"):
            return {
                "plan": {
                    "route": "slash",
                    "rationale": (
                        f"User accepted the pending "
                        f"{pending.get('source', 'agent')} proposal "
                        f"'{pending.get('swap_label') or 'swap'}'."
                    ),
                    "name": "/load",
                    "inputs": {"smiles": pending["smiles"]},
                },
                "source": "pending-proposal-fastpath",
            }

    try:
        plan = await _gemini_route(req.text, ctx, session_id=req.session_id)
        return {"plan": plan, "source": "gemini"}
    except Exception as exc:
        plan = _heuristic_route(req.text, ctx)
        return {"plan": plan, "source": f"heuristic (gemini: {exc})"}


class DecideRequest(BaseModel):
    session_id: str
    candidates: list[str]
    pathogen: Optional[str] = "MRSA"
    criteria: Optional[str] = ""


@router.post("/decide")
async def agent_decide(req: DecideRequest) -> dict:
    """Strategist picks one candidate from N options. Used by the
    ProposalCard's 'Let agent decide' button."""
    from . import debate as _debate
    res = await _debate.strategist_arbitrate(
        req.session_id, req.candidates,
        criteria=req.criteria or "", pathogen=req.pathogen or "MRSA",
    )
    return {
        "winner_smiles": res.raw.get("winner_smiles"),
        "runner_up_smiles": res.raw.get("runner_up_smiles"),
        "justification": res.raw.get("justification"),
        "next_action": res.raw.get("next_action"),
        "tokens_in": res.tokens_in,
        "tokens_out": res.tokens_out,
        "cost_usd": res.cost_usd,
        "elapsed_ms": res.elapsed_ms,
        "error": res.error,
    }


@router.get("/memory/{session_id}")
async def get_memory(session_id: str) -> dict:
    """Inspect the session memory layer — useful for debugging the
    cross-turn context the orchestrator + agent see."""
    return {
        "session_id": session_id,
        "events": session_memory.snapshot(session_id),
        "brief": session_memory.brief(session_id),
    }


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "model": os.getenv("LYSOS_ORCHESTRATOR_MODEL", "gemini-2.5-pro"),
        "n_workflows": len(_KNOWN_WORKFLOWS),
        "n_slash": len(_KNOWN_SLASH),
    }
