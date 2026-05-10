"""Multi-agent debate primitives — Designer / Critic / Editor / Strategist
each as separate Gemini Pro calls with role-specific system prompts,
output schemas, and temperature.

Used by the `design_with_debate` workflow (workspace/api/workflows.py)
to produce a real visible debate in the chat:

  Round 1:
    Designer.propose(target, criteria, memory)
        → 3 candidate SMILES with rationale
    Critic.challenge(proposals, target)
        → per-proposal weakness verdict + suggested fix
    Editor.refine(proposal, critique)
        → refined SMILES + Δ rationale

  Round 2: same with refined proposals as seed

  Final:
    Strategist.decide(refined, criteria)
        → pick winner with justification
        → also flags second-best for the Compare panel

Every call returns structured JSON (responseMimeType=application/json),
records into agent_activity with real token counts + costs, and emits
a chat narration for the user to follow the debate.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from . import agent_activity, session_memory

log = logging.getLogger("api.debate")

# ─────────────────────────────────────────────────────────────────────
# Role prompts — kept terse so the JSON output budget isn't blown
# ─────────────────────────────────────────────────────────────────────

DESIGNER_PROMPT = """You are the Designer agent in a multi-agent antibiotic-discovery debate.

Your job: propose 2–3 NEW antimicrobial candidate SMILES tailored to the
target. You consider the pathogen, the binding pocket, prior session
memory, and any critique from previous rounds.

You think like a medicinal chemist — favor drug-like scaffolds with
balanced lipophilicity, polarity, and synthesizability. Avoid tiny
inert scaffolds (benzene, methane). Reach for known privileged
heterocycles (β-lactams, fluoroquinolones, oxazolidinones,
glycopeptides) but with novel substituents.

Output STRICT JSON:
{
  "thinking": "<one paragraph of your reasoning — design strategy, why these scaffolds, what gaps you're filling>",
  "proposals": [
    {"smiles": "<RDKit-valid SMILES>", "scaffold_class": "<e.g. β-lactam>", "rationale": "<one sentence why this candidate>"},
    ...2 more...
  ]
}

Rules:
- 2 to 3 proposals, no more.
- SMILES must parse with RDKit — keep them under ~40 atoms.
- If you got prior critique, ADDRESS it explicitly in the rationale.
"""

CRITIC_PROMPT = """You are the Critic agent in a multi-agent antibiotic-discovery debate.

Your job: review each Designer proposal and find the worst real-world
weakness. You think like an adversarial pharmacologist — what will
fail in the clinic? Resistance? Toxicity? Solubility? Target
mismatch?

Output STRICT JSON:
{
  "thinking": "<one paragraph: which proposal worries you most and why>",
  "critiques": [
    {"smiles": "<the proposal SMILES being critiqued>",
     "verdict": "accept" | "refine" | "reject",
     "weakness": "<one sentence — the single biggest concern>",
     "suggested_fix": "<one sentence — what the Editor should change>"},
    ...one per proposal...
  ]
}

Rules:
- Be SPECIFIC: name the atom / functional group / mechanism, not generalities.
- "accept" only if you genuinely have no objection.
- "reject" if the proposal is unsalvageable for the target.
"""

EDITOR_PROMPT = """You are the Editor agent in a multi-agent antibiotic-discovery debate.

Your job: take a Designer proposal + Critic's suggested_fix, and
produce a refined SMILES that addresses the critique while preserving
the scaffold's intent.

Output STRICT JSON:
{
  "thinking": "<one paragraph: how you applied the fix and what compromise you made>",
  "refined": [
    {"original_smiles": "<input>", "refined_smiles": "<your edit, RDKit-valid>",
     "delta": "<one sentence: what changed and why>"},
    ...one per input proposal...
  ]
}

Rules:
- ONLY edit if the critique was "refine" or "reject"; pass-through if "accept".
- Refined SMILES must still parse with RDKit.
- Don't make edits that lose the original scaffold's pharmacophore.
"""

CRITIC_PARETO_PROMPT = """You are the Critic agent narrating a Pareto frontier of antibiotic
candidates the team has been scoring. You receive structured Pareto
data (which candidates are non-dominated, dimension values per
candidate, axis names). Your job is to translate the frontier into
actionable strategy.

Output STRICT JSON:
{
  "thinking": "<one paragraph — what the frontier shape implies (knee point? clear leader? scattered?)>",
  "advance_smiles": "<SMILES of the candidate that should be advanced (clinical priority)>",
  "advance_reason": "<one sentence — why: the SPECIFIC numbers that justify advancing this one>",
  "secondary_smiles": "<SMILES of an A/B partner — different trade-off so the team learns from compare>",
  "secondary_reason": "<one sentence — why this is a useful A/B partner>",
  "drop_smiles": "<SMILES of a clearly dominated candidate that should be dropped>",
  "drop_reason": "<one sentence — name the dominator and the dimensions where it loses>",
  "trade_off_insight": "<one sentence — what trade-off is the frontier exposing? e.g. potency vs ADMET>",
  "next_action": "harden" | "score_missing" | "expand_set" | "ship"
}
"""


CRITIC_COMPARE_PROMPT = """You are the Critic agent narrating a side-by-side comparison of N
antibiotic candidates against the same target. You receive structured
resistance / scoring data; you do NOT redo the analysis. Your job is
to translate the numbers into a one-paragraph verdict that names the
winner, calls out the loser's specific weakness (which atom, which
escape vector, which residue), and recommends the next concrete action.

Output STRICT JSON:
{
  "thinking": "<one paragraph — what stood out in the numbers; why the winner wins>",
  "winner_smiles": "<SMILES of the candidate the team should advance>",
  "winner_reason": "<one sentence — the SPECIFIC numerical reason: e.g. 'highest robustness 0.95, only 1 escape vector vs 3+ for the others'>",
  "loser_smiles": "<SMILES of the worst candidate>",
  "loser_weakness": "<one sentence — name the actual weakness: low robustness, high escape count, common-residue vulnerability, etc.>",
  "common_pitfall": "<if common_weak_residues is non-empty, name the top residue and why it matters; else 'none — set is well-diversified'>",
  "next_action": "harden" | "ship" | "edit_runner_up" | "expand_set",
  "next_reason": "<one sentence — why this next action>"
}
"""


STRATEGIST_PROMPT = """You are the Strategist agent in a multi-agent antibiotic-discovery debate.

Your job: weigh the final refined candidates against the project goals
and pick a winner + a runner-up. The winner is the molecule the team
should advance; the runner-up is the candidate to compare against in
A/B for additional evidence.

Output STRICT JSON:
{
  "thinking": "<one paragraph: trade-offs you weighed, why winner beats runner-up>",
  "winner_smiles": "<the SMILES you advance>",
  "runner_up_smiles": "<the second-best SMILES>",
  "justification": "<one sentence — why winner wins on the criteria that matter most>",
  "next_action": "harden" | "score" | "compare" | "ship"
}

Pick "harden" if the winner is good but has resistance vulnerabilities.
Pick "score" if you want a fresh 12-axis read on the winner before deciding.
Pick "compare" if winner and runner-up are too close to call.
Pick "ship" if the winner clearly dominates on every relevant axis.
"""

# Pricing for cost tracking (Gemini Pro 2.5)
_PRICE_IN = 1.25 / 1e6
_PRICE_OUT = 10.0 / 1e6


@dataclass
class RoleResult:
    role: str
    raw: dict[str, Any]
    elapsed_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    error: Optional[str] = None


async def _gemini_call(
    role: str,
    system_prompt: str,
    user_text: str,
    *,
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> RoleResult:
    """Single Gemini call for a role. Returns parsed JSON + usage metadata.
    Best-effort; on failure returns a RoleResult with `error` set so the
    debate can decide to skip the role rather than crash the workflow."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return RoleResult(role=role, raw={}, elapsed_ms=0,
                          tokens_in=0, tokens_out=0, cost_usd=0.0,
                          error="GEMINI_API_KEY missing")
    model_id = os.getenv("LYSOS_DEBATE_MODEL", "gemini-2.5-pro")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
            "thinkingConfig": {"thinkingBudget": 1024, "includeThoughts": False},
        },
    }
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=45.0) as cx:
            r = await cx.post(url,
                              headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json=payload)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        return RoleResult(role=role, raw={}, elapsed_ms=int((time.perf_counter() - started) * 1000),
                          tokens_in=0, tokens_out=0, cost_usd=0.0, error=str(exc)[:200])

    if r.status_code != 200:
        return RoleResult(role=role, raw={}, elapsed_ms=elapsed_ms,
                          tokens_in=0, tokens_out=0, cost_usd=0.0,
                          error=f"http {r.status_code}: {r.text[:200]}")
    body = r.json()
    usage = body.get("usageMetadata") or {}
    tokens_in = int(usage.get("promptTokenCount") or 0)
    tokens_out = int(usage.get("candidatesTokenCount") or 0)
    cost = tokens_in * _PRICE_IN + tokens_out * _PRICE_OUT

    cands = body.get("candidates") or []
    if not cands:
        return RoleResult(role=role, raw={}, elapsed_ms=elapsed_ms,
                          tokens_in=tokens_in, tokens_out=tokens_out,
                          cost_usd=cost, error="no candidates from gemini")
    parts = (cands[0].get("content") or {}).get("parts") or []
    txt = "".join(p.get("text") or "" for p in parts).strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.M).strip()
    try:
        parsed = json.loads(txt)
    except json.JSONDecodeError as exc:
        return RoleResult(role=role, raw={}, elapsed_ms=elapsed_ms,
                          tokens_in=tokens_in, tokens_out=tokens_out,
                          cost_usd=cost,
                          error=f"json parse: {exc} :: {txt[:120]}")
    return RoleResult(role=role, raw=parsed, elapsed_ms=elapsed_ms,
                      tokens_in=tokens_in, tokens_out=tokens_out,
                      cost_usd=cost)


# ─────────────────────────────────────────────────────────────────────
# Role wrappers — each records into agent_activity automatically
# ─────────────────────────────────────────────────────────────────────

def _pathogen_brief(pathogen: str) -> str:
    """Inject the cached knowledge brief — gives every agent role a
    grounded view of the target pathogen (resistance threats, first-line
    therapy to avoid, validated targets) without re-prompting."""
    try:
        from . import knowledge as _kn
        brief = _kn.build_knowledge_brief(pathogen)
        md = brief.get("markdown_brief") or ""
        return f"\n\n--- KNOWLEDGE BRIEF ({pathogen}) ---\n{md}\n--- END BRIEF ---\n" if md else ""
    except Exception:  # noqa: BLE001 — agents must keep working if brief fails
        return ""


async def designer_propose(
    session_id: str, pathogen: str, target_pdb: str,
    criteria: str = "",
    prior_critique: str = "",
    n_proposals: int = 3,
) -> RoleResult:
    user = (
        f"Pathogen: **{pathogen}**\n"
        f"Target PDB: **{target_pdb}**\n"
        f"Criteria: {criteria or 'novel scaffold, drug-like, low resistance risk'}\n"
        f"\nPropose {n_proposals} candidate SMILES.\n"
        + (f"\nPrior critique to address:\n{prior_critique}" if prior_critique else "")
        + _pathogen_brief(pathogen)
        + "\n\n" + (session_memory.brief(session_id) or "")
    )
    res = await _gemini_call("designer", DESIGNER_PROMPT, user, temperature=0.65)
    msg = (res.raw.get("thinking") or "")[:200] + " · " + " / ".join(
        f"`{p.get('smiles', '?')}`" for p in (res.raw.get("proposals") or [])
    )
    agent_activity.record(
        session_id, "designer", "propose",
        message=msg or (res.error or "(no proposals)"),
        confidence=0.9 if not res.error else 0.0,
        elapsed_ms=res.elapsed_ms,
        status="error" if res.error else "ok",
        tokens_in=res.tokens_in, tokens_out=res.tokens_out,
        triggered_by="strategist",
        tags=["gemini", "design"],
    )
    return res


async def critic_challenge(
    session_id: str, proposals: list[dict], pathogen: str, target_pdb: str,
) -> RoleResult:
    proposals_block = "\n".join(
        f"  {i+1}. `{p.get('smiles')}` ({p.get('scaffold_class', '?')}) — {p.get('rationale', '')}"
        for i, p in enumerate(proposals)
    )
    user = (
        f"Pathogen: {pathogen} · Target: {target_pdb}\n\n"
        f"Designer proposals:\n{proposals_block}\n\n"
        f"Critique each one — find the single biggest weakness."
        + _pathogen_brief(pathogen)
    )
    res = await _gemini_call("critic", CRITIC_PROMPT, user, temperature=0.3)
    crits = res.raw.get("critiques") or []
    msg = (res.raw.get("thinking") or "")[:160]
    n_reject = sum(1 for c in crits if (c.get("verdict") or "").lower() == "reject")
    n_refine = sum(1 for c in crits if (c.get("verdict") or "").lower() == "refine")
    msg = f"reviewed {len(crits)} proposals · {n_reject} reject, {n_refine} refine. {msg}"
    agent_activity.record(
        session_id, "critic", "challenge",
        message=msg or (res.error or "(no critiques)"),
        confidence=0.85 if not res.error else 0.0,
        elapsed_ms=res.elapsed_ms,
        status="error" if res.error else "ok",
        tokens_in=res.tokens_in, tokens_out=res.tokens_out,
        triggered_by="designer",
        tags=["gemini", "critique"],
    )
    return res


async def editor_refine(
    session_id: str, proposals: list[dict], critiques: list[dict],
) -> RoleResult:
    pairs = []
    for p in proposals:
        smi = p.get("smiles")
        crit = next((c for c in critiques if c.get("smiles") == smi), {})
        pairs.append(
            f"  - SMILES: `{smi}` · verdict: {crit.get('verdict', '?')} · "
            f"weakness: {crit.get('weakness', '?')} · fix: {crit.get('suggested_fix', '?')}"
        )
    user = "Refine each proposal per the Critic's suggested_fix:\n" + "\n".join(pairs)
    res = await _gemini_call("editor", EDITOR_PROMPT, user, temperature=0.3)
    refined = res.raw.get("refined") or []
    diffs = " / ".join(
        f"`{r.get('original_smiles', '?')[:25]}` → `{r.get('refined_smiles', '?')[:25]}`"
        for r in refined
    )
    msg = f"refined {len(refined)} proposals. {diffs}"
    agent_activity.record(
        session_id, "editor", "refine",
        message=msg or (res.error or "(no refinements)"),
        confidence=0.8 if not res.error else 0.0,
        elapsed_ms=res.elapsed_ms,
        status="error" if res.error else "ok",
        tokens_in=res.tokens_in, tokens_out=res.tokens_out,
        triggered_by="critic",
        tags=["gemini", "refine"],
    )
    return res


async def critic_narrate_pareto(
    session_id: str, pareto: dict, pathogen: str = "MRSA",
) -> RoleResult:
    """Critic looks at a structured Pareto frontier (all_points + axis
    metadata) and produces an advance / A/B / drop recommendation with
    specific candidate-id and SMILES citations."""
    points = pareto.get("all_points") or []
    if not points:
        return RoleResult(role="critic", raw={}, elapsed_ms=0,
                          tokens_in=0, tokens_out=0, cost_usd=0.0,
                          error="no points in pareto frontier")
    # Filter to scored points only — the agent can't reason about None
    scored = [p for p in points if p.get("x_value") is not None and p.get("y_value") is not None]
    if not scored:
        return RoleResult(role="critic", raw={}, elapsed_ms=0,
                          tokens_in=0, tokens_out=0, cost_usd=0.0,
                          error="no scored candidates yet — kick score-missing first")
    x_meta = pareto.get("x_axis_meta") or {}
    y_meta = pareto.get("y_axis_meta") or {}
    x_label = x_meta.get("label") or pareto.get("x_axis", "x")
    y_label = y_meta.get("label") or pareto.get("y_axis", "y")
    rows_block = "\n".join(
        f"  - SMILES `{p.get('smiles')}` "
        f"(id {p.get('candidate_id', '')[:10]}, {p.get('created_by', '?')}): "
        f"{x_label} = {p.get('x_value'):.3f}, {y_label} = {p.get('y_value'):.3f}"
        f"{' [PARETO]' if p.get('on_pareto') else ''}"
        for p in scored[:10]
    )
    user = (
        f"Pathogen: {pathogen}\n"
        f"Pareto frontier on **{x_label}** vs **{y_label}**\n"
        f"Scored candidates ({len(scored)} of {len(points)} total; "
        f"{pareto.get('stats', {}).get('n_pareto', '?')} on the frontier):\n\n"
        f"{rows_block}\n\n"
        f"Pick: which to advance, which to A/B, which to drop. Be concrete with numbers."
        + _pathogen_brief(pathogen)
    )
    res = await _gemini_call("critic", CRITIC_PARETO_PROMPT, user, temperature=0.3, max_tokens=4096)
    msg = (
        f"narrated pareto · advance: `{res.raw.get('advance_smiles', '?')[:30]}…` · "
        f"trade-off: {(res.raw.get('trade_off_insight') or '')[:80]}"
    )
    agent_activity.record(
        session_id, "critic", "narrate_pareto",
        message=msg or (res.error or "(no narration)"),
        confidence=0.85 if not res.error else 0.0,
        elapsed_ms=res.elapsed_ms,
        status="error" if res.error else "ok",
        tokens_in=res.tokens_in, tokens_out=res.tokens_out,
        triggered_by="strategist",
        tags=["gemini", "pareto"],
    )
    return res


async def critic_narrate_compare(
    session_id: str, comparison: dict, pathogen: str = "MRSA",
) -> RoleResult:
    """Have the Critic look at a structured compare_resistance result
    (rows + best_idx + common_weak_residues) and produce a one-paragraph
    verdict naming winner / loser / next action with concrete numerical
    citations. Used by the deep compare_top_n workflow."""
    rows = comparison.get("rows") or []
    if not rows:
        return RoleResult(role="critic", raw={}, elapsed_ms=0,
                          tokens_in=0, tokens_out=0, cost_usd=0.0,
                          error="empty comparison rows")
    rows_block = "\n".join(
        f"  {i+1}. SMILES `{r.get('smiles')}` · "
        f"robustness {r.get('robustness_score', 0):.3f} · "
        f"escape_vectors {r.get('n_escape_vectors', 0)} · "
        f"contacts {r.get('n_residues_with_contacts', 0)} · "
        f"clinical_overlaps {r.get('n_clinical_overlaps', 0)}"
        + (" ⚠ ERROR: " + r.get("error") if r.get("error") else "")
        for i, r in enumerate(rows)
    )
    common = comparison.get("common_weak_residues") or []
    common_block = ""
    if common:
        common_block = "\nCommon weak residues across the set: " + ", ".join(
            f"{c.get('position')} (hits {c.get('n_candidates')}/{comparison.get('n_valid', '?')})"
            for c in common[:5]
        )
    user = (
        f"Pathogen: {pathogen} · Target PDB: {comparison.get('pdb_id')}\n"
        f"{len(rows)} candidates compared:\n\n{rows_block}\n"
        f"{common_block}\n\n"
        f"Backend's pick (highest robustness): index {comparison.get('best_idx')}.\n"
        f"Verify or contradict — pick the real winner and name the real loser's weakness."
        + _pathogen_brief(pathogen)
    )
    # Bump max_tokens beyond the default — the structured JSON has 7
    # fields and Gemini's thinking budget eats from the same pool.
    res = await _gemini_call("critic", CRITIC_COMPARE_PROMPT, user, temperature=0.3, max_tokens=4096)
    msg = (
        f"narrated {len(rows)}-candidate compare · winner: "
        f"`{res.raw.get('winner_smiles', '?')[:30]}…` · "
        f"next: {res.raw.get('next_action', '?')}"
    )
    agent_activity.record(
        session_id, "critic", "narrate_compare",
        message=msg or (res.error or "(no narration)"),
        confidence=0.85 if not res.error else 0.0,
        elapsed_ms=res.elapsed_ms,
        status="error" if res.error else "ok",
        tokens_in=res.tokens_in, tokens_out=res.tokens_out,
        triggered_by="strategist",
        tags=["gemini", "compare"],
    )
    return res


async def strategist_arbitrate(
    session_id: str, candidates: list[str], criteria: str = "",
    pathogen: str = "MRSA",
) -> RoleResult:
    """Pick one of N candidate SMILES the user has surfaced via a
    proposal card. Used by the /agent/decide endpoint when the user
    clicks 'Let agent decide'."""
    listing = "\n".join(f"  {i+1}. `{s}`" for i, s in enumerate(candidates))
    user = (
        f"Pathogen: {pathogen}\n"
        f"Criteria: {criteria or 'novel scaffold, drug-like, low resistance risk'}\n\n"
        f"User wants you to pick ONE of these {len(candidates)} candidates:\n{listing}\n\n"
        f"Use the format: winner_smiles, runner_up_smiles, justification, next_action."
        + _pathogen_brief(pathogen)
    )
    res = await _gemini_call("strategist", STRATEGIST_PROMPT, user, temperature=0.15)
    msg = (
        f"arbitrated · winner: `{res.raw.get('winner_smiles', '?')}` · "
        f"{res.raw.get('justification', '')[:120]}"
    )
    agent_activity.record(
        session_id, "strategist", "arbitrate",
        message=msg or (res.error or ""),
        confidence=0.9 if not res.error else 0.0,
        elapsed_ms=res.elapsed_ms,
        status="error" if res.error else "ok",
        tokens_in=res.tokens_in, tokens_out=res.tokens_out,
        triggered_by="user", tags=["gemini", "arbitrate"],
    )
    return res


async def strategist_decide(
    session_id: str, refined_proposals: list[dict], criteria: str,
) -> RoleResult:
    pairs = "\n".join(
        f"  {i+1}. `{r.get('refined_smiles', r.get('original_smiles', '?'))}` — Δ: {r.get('delta', '')}"
        for i, r in enumerate(refined_proposals)
    )
    user = (
        f"Criteria: {criteria or 'novel scaffold, drug-like, low resistance risk'}\n\n"
        f"Refined candidates:\n{pairs}\n\nPick winner + runner-up."
    )
    res = await _gemini_call("strategist", STRATEGIST_PROMPT, user, temperature=0.2)
    msg = (
        f"winner: `{res.raw.get('winner_smiles', '?')}` · "
        f"runner-up: `{res.raw.get('runner_up_smiles', '?')}` · "
        f"next: {res.raw.get('next_action', '?')}. "
        + (res.raw.get("justification") or "")[:120]
    )
    agent_activity.record(
        session_id, "strategist", "decide",
        message=msg or (res.error or "(no decision)"),
        confidence=0.9 if not res.error else 0.0,
        elapsed_ms=res.elapsed_ms,
        status="error" if res.error else "ok",
        tokens_in=res.tokens_in, tokens_out=res.tokens_out,
        triggered_by="editor",
        tags=["gemini", "decide"],
    )
    return res


# ─────────────────────────────────────────────────────────────────────
# Public: full debate runner — yields per-step result dicts so the
# caller (workflow executor) can stream into chat as it progresses.
# ─────────────────────────────────────────────────────────────────────

@dataclass
class DebateOutcome:
    proposals: list[dict] = field(default_factory=list)
    critiques: list[dict] = field(default_factory=list)
    refined: list[dict] = field(default_factory=list)
    winner: Optional[str] = None
    runner_up: Optional[str] = None
    next_action: str = "score"
    justification: str = ""
    rounds_log: list[dict] = field(default_factory=list)
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    elapsed_ms: int = 0


async def run_debate(
    session_id: str,
    pathogen: str,
    target_pdb: str = "1VQQ",
    criteria: str = "",
    n_rounds: int = 2,
    n_proposals: int = 3,
) -> DebateOutcome:
    """Run a full N-round debate. Returns DebateOutcome with all role
    contributions + winner. Used by the design_with_debate workflow."""
    started = time.perf_counter()
    out = DebateOutcome()
    prior_critique = ""

    for round_i in range(n_rounds):
        d = await designer_propose(
            session_id, pathogen, target_pdb,
            criteria=criteria, prior_critique=prior_critique,
            n_proposals=n_proposals,
        )
        out.total_tokens_in += d.tokens_in
        out.total_tokens_out += d.tokens_out
        out.total_cost_usd += d.cost_usd
        proposals = d.raw.get("proposals") or []
        if not proposals:
            out.rounds_log.append({"round": round_i + 1, "stage": "designer",
                                    "error": d.error or "no proposals"})
            break
        out.proposals = proposals  # last round's proposals

        c = await critic_challenge(session_id, proposals, pathogen, target_pdb)
        out.total_tokens_in += c.tokens_in
        out.total_tokens_out += c.tokens_out
        out.total_cost_usd += c.cost_usd
        critiques = c.raw.get("critiques") or []
        out.critiques = critiques

        e = await editor_refine(session_id, proposals, critiques)
        out.total_tokens_in += e.tokens_in
        out.total_tokens_out += e.tokens_out
        out.total_cost_usd += e.cost_usd
        refined = e.raw.get("refined") or []
        out.refined = refined

        # Build prior_critique block for next round so Designer can address it
        prior_critique = "\n".join(
            f"  - {c.get('weakness', '')} → fix: {c.get('suggested_fix', '')}"
            for c in critiques
        )
        out.rounds_log.append({
            "round": round_i + 1,
            "designer_thinking": d.raw.get("thinking", ""),
            "critic_thinking": c.raw.get("thinking", ""),
            "editor_thinking": e.raw.get("thinking", ""),
            "n_proposals": len(proposals),
            "n_critiques": len(critiques),
            "n_refined": len(refined),
        })

    # Final strategist decision
    if out.refined:
        s = await strategist_decide(session_id, out.refined, criteria)
        out.total_tokens_in += s.tokens_in
        out.total_tokens_out += s.tokens_out
        out.total_cost_usd += s.cost_usd
        out.winner = s.raw.get("winner_smiles")
        out.runner_up = s.raw.get("runner_up_smiles")
        out.next_action = (s.raw.get("next_action") or "score").lower()
        out.justification = s.raw.get("justification") or ""
        out.rounds_log.append({"stage": "strategist_decide",
                                "winner": out.winner,
                                "runner_up": out.runner_up,
                                "next_action": out.next_action})

    out.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return out
