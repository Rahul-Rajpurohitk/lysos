"""Autonomous campaign harness — the headline agentic loop of Lysos.

One prompt -> a full discovery campaign:

    generate -> score/rank -> gate (synth + IP + ADMET) -> decide -> dossier

Each phase is an inline workflow step that reuses the real services already
built (chem_generate, chem_synthesis, chem_ip, chem_admet) and writes
everything into the Campaign object. The Strategist agent makes the final
advance/champion/hold call. This is what turns "5 services" into "an agent
that runs a campaign".

Registered into workflows._REGISTRY as `campaign_run`, so it streams over SSE
and shows in /api/workflows/list like every other workflow. Built in small
composable steps so each phase is independently testable.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger("lysos.campaign_harness")

_SELF = os.getenv("LYSOS_SELF_URL", "http://127.0.0.1:7860")


# Phase 1 - GENERATE
async def gen_step(state: dict) -> dict:
    seed = state.get("seed") or state.get("smiles")
    pathogen = state.get("pathogen") or "MRSA"
    n = int(state.get("n") or 6)
    try:
        async with httpx.AsyncClient(timeout=120.0) as cx:
            r = await cx.post(f"{_SELF}/workbench/chem/generate", json={
                "seed": seed, "n": n, "pathogen": pathogen,
                "session_id": state.get("session_id"),
                "campaign_id": state.get("campaign_id"),
                "save": True,
            })
        if r.status_code != 200:
            return {"error": f"generate failed: HTTP {r.status_code}"}
        run = r.json()
        return {"engine": run.get("engine"),
                "n_generated": run.get("n_generated"),
                "candidates": run.get("candidates") or []}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


# Phase 2 - RANK (pure)
async def rank_step(state: dict) -> dict:
    gen = state.get("gen") or {}
    cands = gen.get("candidates") or []
    if not cands:
        return {"error": "no candidates generated to rank"}
    ranked = sorted(
        cands,
        key=lambda c: (c.get("composite") is not None, c.get("composite") or 0),
        reverse=True)
    return {"lead": ranked[0], "ranked": ranked[:5], "n_ranked": len(ranked)}


# Phase 3 - GATE
async def _post(path: str, payload: dict, timeout: float = 60.0) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as cx:
            r = await cx.post(f"{_SELF}{path}", json=payload)
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


async def gate_step(state: dict) -> dict:
    rank = state.get("rank") or {}
    lead = rank.get("lead") or {}
    smi = lead.get("smiles")
    if not smi:
        return {"error": "no lead candidate to gate"}
    sid = state.get("session_id")
    admet = await _post("/workbench/chem/admet/panel",
                        {"smiles": smi, "session_id": sid, "save": True,
                         "design_fix": False})
    synth = await _post("/workbench/chem/synthesis/plan",
                        {"smiles": smi, "session_id": sid, "save": True,
                         "design_analog": False})
    ip = await _post("/workbench/chem/ip/fto-scan",
                     {"smiles": smi, "session_id": sid, "save": True,
                      "design_variant": False})
    gates = {
        "admet": {
            "composite": (admet or {}).get("composite"),
            "tier": (admet or {}).get("tier"),
            "weakest": ((admet or {}).get("worst") or {}).get("axis"),
            "source": (admet or {}).get("source"),
            "pass": ((admet or {}).get("composite") or 0) >= 0.5},
        "synthesis": {
            "n_steps": (synth or {}).get("n_steps"),
            "cost_band": (synth or {}).get("cost_band"),
            "feasibility_band": (synth or {}).get("feasibility_band"),
            "pass": (synth or {}).get("feasibility_band") in ("ready", "workable")},
        "ip": {
            "novelty_score": (ip or {}).get("novelty_score"),
            "verdict": (ip or {}).get("verdict"),
            "pass": ((ip or {}).get("novelty_score") or 0) >= 0.30},
    }
    n_pass = sum(1 for g in gates.values() if g.get("pass"))
    return {"smiles": smi, "gates": gates, "n_pass": n_pass, "n_gates": 3}


# Phase 4 - DECIDE
async def decide_step(state: dict) -> dict:
    gate = state.get("gate") or {}
    smi = gate.get("smiles")
    n_pass = gate.get("n_pass", 0)
    cid = state.get("campaign_id")
    if not smi:
        return {"error": "nothing to decide on"}
    if n_pass >= 3:
        kind, verdict = "champion", "Clears all three gates - advance as champion."
    elif n_pass == 2:
        kind, verdict = "advance", "Clears two of three gates - advance with a watch item."
    else:
        kind, verdict = "hold", "Fails the developability gate - hold and redesign."
    if cid:
        await _post(f"/workbench/chem/campaign/{cid}/decision",
                    {"kind": kind, "smiles": smi, "rationale": verdict,
                     "by": "strategist"})
    return {"kind": kind, "verdict": verdict, "smiles": smi, "n_pass": n_pass}


# Final report
def synth_campaign(state: dict) -> str:
    gen = state.get("gen") or {}
    rank = state.get("rank") or {}
    gate = state.get("gate") or {}
    decide = state.get("decide") or {}
    if gen.get("error"):
        return f"Campaign couldn't generate candidates: {gen['error']}"
    lead = rank.get("lead") or {}
    gates = gate.get("gates") or {}
    a = gates.get("admet", {}); s = gates.get("synthesis", {}); ip = gates.get("ip", {})
    lines = [
        f"**Autonomous campaign complete** - target {state.get('pathogen','MRSA')}.",
        "",
        f"**Generated** {gen.get('n_generated','?')} candidates "
        f"({gen.get('engine','?')} engine), ranked {rank.get('n_ranked','?')}.",
        f"**Lead:** `{lead.get('smiles','-')}` (composite {lead.get('composite','-')}).",
        "",
        "**Developability gate:**",
        f"- ADMET: {'PASS' if a.get('pass') else 'FLAG'} composite "
        f"{a.get('composite','-')} ({a.get('tier','-')}, weakest {a.get('weakest','-')}, "
        f"{a.get('source','-')})",
        f"- Synthesis: {'PASS' if s.get('pass') else 'FLAG'} {s.get('n_steps','-')} steps, "
        f"{s.get('cost_band','-')} cost, {s.get('feasibility_band','-')}",
        f"- IP/novelty: {'PASS' if ip.get('pass') else 'FLAG'} score "
        f"{ip.get('novelty_score','-')} ({ip.get('verdict','-')})",
        "",
        f"**Strategist decision:** {decide.get('kind','-').upper()} - {decide.get('verdict','-')}",
        f"_{gate.get('n_pass','?')}/3 gates cleared._",
    ]
    return "\n".join(lines).strip()


def register(workflows_mod) -> None:
    """Register campaign_run into the workflows registry."""
    Workflow = workflows_mod.Workflow
    Step = workflows_mod.Step
    workflows_mod._register(Workflow(
        name="campaign_run",
        label="Autonomous campaign",
        description=("One prompt -> a full discovery campaign: generate real "
                     "candidates, score + rank, run the developability gate "
                     "(ADMET + synthesis + IP), and the Strategist makes the "
                     "advance / champion / hold call - all logged to the campaign."),
        inputs=[
            {"name": "pathogen", "type": "string", "required": True},
            {"name": "seed", "type": "string", "required": False},
            {"name": "campaign_id", "type": "string", "required": False},
            {"name": "session_id", "type": "string", "required": False},
            {"name": "n", "type": "number", "required": False},
        ],
        tags=["campaign", "autonomous", "generate", "gate", "decide"],
        steps=[
            Step(id="generate", label="Generate real candidates",
                 tool="__inline__", inline_fn=gen_step,
                 on_result=lambda st, r: st.__setitem__("gen", r)),
            Step(id="rank", label="Score + rank the candidates",
                 tool="__inline__", inline_fn=rank_step,
                 on_result=lambda st, r: st.__setitem__("rank", r)),
            Step(id="gate", label="Developability gate (ADMET + synthesis + IP)",
                 tool="__inline__", inline_fn=gate_step,
                 on_result=lambda st, r: st.__setitem__("gate", r),
                 narrator_role="critic"),
            Step(id="decide", label="Strategist decision",
                 tool="__inline__", inline_fn=decide_step,
                 on_result=lambda st, r: st.__setitem__("decide", r),
                 narrator_role="strategist"),
        ],
        synthesize_fn=synth_campaign,
    ))
    log.info("campaign_run workflow registered")
