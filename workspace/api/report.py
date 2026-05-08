"""Report container — snapshot all chem dashboards + assemble medchem deliverable.

Endpoints:
  POST /workbench/report/snapshot/{sid}        capture all container states
  GET  /workbench/report/{sid}/preview          render combined report
  GET  /workbench/report/{sid}/export?format=md|json    export final

Why this exists
  Without a deliverable the system feels like "chat that designs molecules".
  With this, the user clicks one button and gets a structured medchem report
  ready to share — judges, collaborators, paper draft. This is the artifact
  the workflow produces.

Snapshot pulls:
  - Top-3 candidates by composite reward (with full property + score breakdown)
  - For each: 3D pose data + resistance escape vulnerability + Pareto position
  - Workflow phase audit (every phase + tools called)
  - Agent rationale (key decisions per agent)
  - Pathogen context (resistome + closest known antibiotics)
  - Session metadata (started_at, duration, n_candidates, n_iterations)
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

log = logging.getLogger("api.report")
router = APIRouter(prefix="/report", tags=["report"])


@router.post("/snapshot/{sid}")
async def snapshot_session(sid: str) -> dict:
    """Capture a one-shot snapshot of every dashboard for the session.
    Returns a structured payload that the preview / export routes consume."""
    from workspace.playground.store import get_store
    store = get_store()

    # Session metadata
    mols = store.list_session_molecules(sid)
    if not mols:
        raise HTTPException(404, f"no candidates in session {sid}")

    actions = store.list_actions(sid, limit=2000)

    # Score each candidate, pick top-3 by composite
    scored = []
    for m in mols:
        score = store.latest_score(m.get("id"))
        if not score:
            continue
        scored.append({"mol": m, "score": score})
    scored.sort(key=lambda x: -(x["score"].get("composite") or 0))
    top3 = scored[:3]

    # Pathogen / target context — try first candidate's pathogen field, else session
    pathogen = mols[0].get("pathogen") or "MRSA"

    # ── Service 1 + 2 enrichment: for each top candidate, fetch fresh
    # pose + resistance data so the report carries the BIOLOGY context,
    # not just chemistry scores. Uses the same endpoints the workbench
    # cards consume. Failures are non-fatal — candidate falls back to
    # chemistry-only display.
    pdb_id = _preferred_pdb_for_pathogen(pathogen)
    top3_enriched: list[dict] = []
    for entry in top3:
        smi = entry["mol"].get("smiles")
        ext: dict = {"pose": None, "resistance": None, "pdb_id": pdb_id}
        if smi and pdb_id:
            try:
                from .chem_3d import place_in_pocket as _ep_pose, PlaceInPocketRequest
                pose = await _ep_pose(PlaceInPocketRequest(smiles=smi, pdb_id=pdb_id))
                ext["pose"] = {
                    "pose_score": pose.get("pose_score"),
                    "n_contacts": pose.get("n_contacts"),
                    "n_clashes": pose.get("n_clashes"),
                    "binding_atoms": pose.get("binding_atoms", [])[:12],
                    "clashing_atoms": pose.get("clashing_atoms", []),
                    "key_contacts": pose.get("key_contacts", [])[:6],
                }
            except Exception:
                pass
            try:
                from .chem_resistance import predict_resistance as _ep_res, PredictResistanceRequest
                res = await _ep_res(PredictResistanceRequest(smiles=smi, pdb_id=pdb_id))
                ext["resistance"] = {
                    "robustness_score": res.get("robustness_score"),
                    "n_escape_vectors": res.get("n_escape_vectors"),
                    "vulnerable_atoms": res.get("vulnerable_atoms", [])[:5],
                    "summary": res.get("summary"),
                    "target_name": res.get("target_name"),
                }
            except Exception:
                pass
        top3_enriched.append(ext)

    # Workflow phase summary (heuristic from /workflow logic, kept inline so
    # this module doesn't depend on workbench.py routing)
    n_candidates = len(mols)
    n_score_actions = sum(1 for a in actions if (a.get("action_type") or "").lower() in ("score", "score_molecule"))
    n_pocket = sum(1 for a in actions if "pocket" in (a.get("action_type") or "").lower() or "place_in_pocket" in (a.get("message_text") or ""))
    n_resistance = sum(1 for a in actions if "resistance" in (a.get("action_type") or "").lower() or "vulnerability" in (a.get("message_text") or "").lower())
    n_red_team = sum(1 for a in actions if "red_team" in (a.get("action_type") or "").lower() or "escape" in (a.get("action_type") or "").lower())

    # Tool-call counts by category
    tool_counts: dict[str, int] = {}
    for a in actions:
        atype = (a.get("action_type") or "").lower()
        if atype:
            tool_counts[atype] = tool_counts.get(atype, 0) + 1

    # Agent contributions
    agent_actions: dict[str, dict] = {}
    for a in actions:
        ag = (a.get("agent_name") or "system").lower()
        if ag not in agent_actions:
            agent_actions[ag] = {"n": 0, "examples": [], "last_message": ""}
        agent_actions[ag]["n"] += 1
        if a.get("message_text") and len(agent_actions[ag]["examples"]) < 3:
            agent_actions[ag]["examples"].append((a.get("message_text") or "")[:160])
        agent_actions[ag]["last_message"] = (a.get("message_text") or "")[:200]

    # Session timing
    if actions:
        first_ts = min((a.get("ts") or 0) for a in actions)
        last_ts = max((a.get("ts") or 0) for a in actions)
        duration_min = round((last_ts - first_ts) / 60.0, 1) if last_ts > first_ts else 0.0
    else:
        first_ts = last_ts = time.time()
        duration_min = 0.0

    return {
        "session_id": sid,
        "captured_at": time.time(),
        "pathogen": pathogen,
        "session": {
            "started_at": first_ts,
            "ended_at": last_ts,
            "duration_min": duration_min,
            "n_candidates": n_candidates,
            "n_score_actions": n_score_actions,
            "n_pocket_calls": n_pocket,
            "n_resistance_calls": n_resistance,
            "n_red_team_calls": n_red_team,
        },
        "top_candidates": [
            {
                "rank": i + 1,
                "id": x["mol"].get("id"),
                "smiles": x["mol"].get("smiles"),
                "created_by": x["mol"].get("created_by"),
                "composite": x["score"].get("composite"),
                "components": x["score"].get("components", {}),
                "model_used": x["score"].get("model_used"),
                # Biology context (Service 1 + 2)
                "pdb_target": top3_enriched[i].get("pdb_id"),
                "pose": top3_enriched[i].get("pose"),
                "resistance": top3_enriched[i].get("resistance"),
            }
            for i, x in enumerate(top3)
        ],
        "all_candidates_summary": {
            "total": n_candidates,
            "best_composite": top3[0]["score"].get("composite") if top3 else None,
            "agents_who_proposed": list({m.get("created_by", "user") for m in mols}),
        },
        "tool_calls": tool_counts,
        "agent_contributions": agent_actions,
        "workflow_phases_completed": _derive_phases_completed(
            n_candidates, n_score_actions, n_pocket, n_resistance, n_red_team,
        ),
    }


def _preferred_pdb_for_pathogen(pathogen: str) -> Optional[str]:
    """Mirror of the helper in graph.py — kept here to avoid circular import."""
    try:
        from .chem_3d import PATHOGEN_TARGETS
        targets = PATHOGEN_TARGETS.get(pathogen, [])
        if not targets:
            return None
        for t in targets:
            if t.get("preferred_default"):
                return t["pdb_id"]
        return targets[0]["pdb_id"]
    except Exception:
        return None


def _derive_phases_completed(n_cand: int, n_score: int, n_pocket: int,
                             n_resistance: int, n_red_team: int) -> list[str]:
    completed = []
    if n_cand > 0:
        completed.append("scope")
    if n_cand >= 1:
        completed.append("anchor")
    if n_score > 0:
        completed.append("design")
    if n_pocket > 0 or n_resistance > 0:
        completed.append("validate")
    if n_red_team > 0:
        completed.append("stress_test")
    return completed


@router.get("/{sid}/preview")
async def preview_report(sid: str, format: str = Query("html", regex="^(html|md|json)$")) -> Any:
    """Render the combined report. Default HTML for browser preview;
    md / json for downstream tooling."""
    snap = await snapshot_session(sid)

    if format == "json":
        return snap

    if format == "md":
        from fastapi.responses import PlainTextResponse
        md = _render_markdown(snap)
        return PlainTextResponse(md, media_type="text/markdown")

    # HTML
    from fastapi.responses import HTMLResponse
    html = _render_html(snap)
    return HTMLResponse(html)


@router.get("/{sid}/export")
async def export_report(sid: str, format: str = Query("md", regex="^(md|json)$")) -> Any:
    """Export the report as markdown or JSON for download.
    PDF export is browser-driven (User saves the HTML preview as PDF)."""
    snap = await snapshot_session(sid)
    from fastapi.responses import Response, JSONResponse

    if format == "json":
        return JSONResponse(snap)

    md = _render_markdown(snap)
    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="lysos-report-{sid[:12]}.md"'},
    )


def _render_markdown(snap: dict) -> str:
    """Render the snapshot as a structured medchem report in Markdown."""
    s = snap["session"]
    pathogen = snap["pathogen"]
    captured = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(snap["captured_at"]))

    parts = [
        f"# Lysos Drug-Discovery Report — {pathogen}",
        "",
        f"**Session**: `{snap['session_id']}`",
        f"**Captured**: {captured}",
        f"**Duration**: {s['duration_min']} min",
        f"**Candidates explored**: {s['n_candidates']}",
        "",
        "---",
        "",
        "## Workflow Audit",
        "",
        "| Phase | Status |",
        "|---|---|",
    ]
    PHASES = ["scope", "anchor", "design", "validate", "stress_test", "report"]
    completed = set(snap["workflow_phases_completed"])
    for p in PHASES:
        status = "✅ completed" if p in completed else ("⏳ active" if p == "report" and snap["top_candidates"] else "○ skipped")
        parts.append(f"| {p.replace('_', ' ').upper()} | {status} |")
    parts.extend([
        "",
        f"- Score actions: **{s['n_score_actions']}**",
        f"- 3D pose computations: **{s['n_pocket_calls']}**",
        f"- Resistance vulnerability checks: **{s['n_resistance_calls']}**",
        f"- Red-team escape predictions: **{s['n_red_team_calls']}**",
        "",
        "---",
        "",
        "## Top Candidates",
        "",
    ])

    for c in snap["top_candidates"]:
        parts.extend([
            f"### #{c['rank']} — composite {c['composite']:.3f}" if c['composite'] is not None else f"### #{c['rank']}",
            "",
            f"```",
            f"SMILES:     {c['smiles']}",
            f"Proposed by: {c['created_by']}",
            f"Model:      {c.get('model_used') or 'lysos-base-dpo'}",
            f"```",
            "",
            "**Score breakdown**:",
            "",
            "| Axis | Value |",
            "|---|---|",
        ])
        comps = c.get("components", {}) or {}
        for k, v in sorted(comps.items()):
            try:
                vstr = f"{float(v):.3f}"
            except (ValueError, TypeError):
                vstr = str(v)
            parts.append(f"| {k} | {vstr} |")

        # Biology block — Service 1 (pose) + Service 2 (resistance)
        pose = c.get("pose")
        if pose:
            parts.extend([
                "",
                f"**Target binding (vs `{c.get('pdb_target', '?')}`)**:",
                "",
                f"- pose_score: **{pose.get('pose_score')}** · contacts: {pose.get('n_contacts')} · clashes: {pose.get('n_clashes')}",
                f"- binding atoms: `{pose.get('binding_atoms', [])}`",
            ])
            if pose.get("clashing_atoms"):
                parts.append(f"- clashing atoms: `{pose.get('clashing_atoms')}`")
            kc = pose.get("key_contacts", [])
            if kc:
                parts.append("")
                parts.append("Key residue contacts:")
                for k in kc:
                    parts.append(
                        f"- `{k.get('residue')}` (chain {k.get('chain')}) ↔ "
                        f"atom {k.get('ligand_atom_idx')} ({k.get('ligand_element')}) — "
                        f"{k.get('distance_a')} Å"
                    )

        res = c.get("resistance")
        if res:
            parts.extend([
                "",
                "**Resistance escape**:",
                "",
                f"- robustness_score: **{res.get('robustness_score')}** · escape vectors: **{res.get('n_escape_vectors')}**",
                f"- {res.get('summary', '')}",
            ])
            vulns = res.get("vulnerable_atoms", [])
            if vulns:
                parts.append("")
                parts.append("Top clinical vulnerabilities:")
                for v in vulns[:3]:
                    m = v.get("top_mutation", {})
                    parts.append(
                        f"- atom **{v.get('atom_idx')}** → escape **{v.get('escape_score'):.2f}** "
                        f"via `{m.get('wt')}{m.get('position')}{m.get('mutant')}` "
                        f"({m.get('drug_class', '')[:30]})"
                    )
        parts.append("")

    parts.extend([
        "---",
        "",
        "## Agent Contributions",
        "",
        "| Agent | Actions | Sample message |",
        "|---|---|---|",
    ])
    for ag, info in sorted(snap["agent_contributions"].items()):
        sample = (info.get("examples") or [info.get("last_message", "")])[0]
        sample = sample.replace("|", "\\|").replace("\n", " ")[:120]
        parts.append(f"| {ag} | {info['n']} | {sample} |")

    parts.extend([
        "",
        "---",
        "",
        "## Tool-Call Distribution",
        "",
        "| Tool / action | Count |",
        "|---|---|",
    ])
    for tool, n in sorted(snap["tool_calls"].items(), key=lambda kv: -kv[1])[:20]:
        parts.append(f"| {tool} | {n} |")

    parts.extend([
        "",
        "---",
        "",
        "## Next Experiments",
        "",
        "Recommended wet-lab follow-up for the top candidate:",
        "",
        "1. **Synthesize** the top-1 candidate per the suggested route (see synthesis tools)",
        "2. **MIC assay** against the target pathogen (broth microdilution, CLSI M07)",
        "3. **Cytotoxicity** against HepG2 + HEK293 (CC50 ≥ 32× MIC for safety margin)",
        "4. **In silico ADMET re-confirmation** with a validated model (the proxy here is heuristic)",
        "5. **Resistance-evolution** experiment: serial passage at sub-MIC concentrations to validate the predicted escape vectors",
        "",
        "---",
        "",
        "*Generated by Lysos · trained on AMD MI300X · served on AMD MI300X · "
        "rahul24raj/lysos-base-dpo*",
    ])

    return "\n".join(parts)


def _render_html(snap: dict) -> str:
    """Render the snapshot as an HTML page (printable / save-as-PDF friendly)."""
    md = _render_markdown(snap)
    # Lightweight: render md → html via a tiny converter
    body_html = _md_to_html(md)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Lysos Report — {snap.get('pathogen', '')}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 880px; margin: 32px auto; padding: 0 24px; color: #1f2937; line-height: 1.55; }}
  h1 {{ color: #0f172a; border-bottom: 2px solid #0891b2; padding-bottom: 8px; }}
  h2 {{ color: #0f172a; margin-top: 36px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }}
  h3 {{ color: #0891b2; margin-top: 24px; }}
  code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.92em; }}
  pre {{ background: #f1f5f9; padding: 10px 14px; border-radius: 6px; overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #e5e7eb; padding: 6px 10px; text-align: left; }}
  th {{ background: #f8fafc; font-weight: 700; }}
  hr {{ border: 0; border-top: 1px solid #e5e7eb; margin: 28px 0; }}
  em {{ color: #6b7280; font-size: 0.92em; }}
  blockquote {{ color: #475569; border-left: 3px solid #0891b2; padding-left: 12px; }}
  @media print {{ body {{ font-size: 11pt; }} h1 {{ page-break-before: avoid; }} h2, h3 {{ page-break-after: avoid; }} }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""


def _md_to_html(md: str) -> str:
    """Minimal markdown → html (handles headings, tables, code, paragraphs).
    Avoids the python-markdown dependency for a tight build."""
    out_lines = []
    in_code = False
    in_table = False
    table_buffer: list[str] = []

    def flush_table() -> None:
        nonlocal in_table, table_buffer
        if not table_buffer:
            return
        # First row = header, second = separator, rest = data
        rows = [r for r in table_buffer if r.strip()]
        if len(rows) < 2:
            in_table = False
            table_buffer = []
            return
        header = [c.strip() for c in rows[0].strip("|").split("|")]
        body_rows = rows[2:]
        out_lines.append("<table>")
        out_lines.append("<thead><tr>" + "".join(f"<th>{h}</th>" for h in header) + "</tr></thead>")
        out_lines.append("<tbody>")
        for r in body_rows:
            cells = [c.strip() for c in r.strip("|").split("|")]
            out_lines.append("<tr>" + "".join(f"<td>{_md_inline(c)}</td>" for c in cells) + "</tr>")
        out_lines.append("</tbody></table>")
        in_table = False
        table_buffer = []

    for line in md.split("\n"):
        s = line.rstrip()
        if s.startswith("```"):
            if in_code:
                out_lines.append("</pre>")
                in_code = False
            else:
                out_lines.append("<pre>")
                in_code = True
            continue
        if in_code:
            out_lines.append(_html_escape(s))
            continue
        if s.startswith("|") and s.endswith("|") and "|" in s[1:-1]:
            in_table = True
            table_buffer.append(s)
            continue
        if in_table and not s.startswith("|"):
            flush_table()
        if s.startswith("# "):
            out_lines.append(f"<h1>{_md_inline(s[2:])}</h1>")
        elif s.startswith("## "):
            out_lines.append(f"<h2>{_md_inline(s[3:])}</h2>")
        elif s.startswith("### "):
            out_lines.append(f"<h3>{_md_inline(s[4:])}</h3>")
        elif s.startswith("---"):
            out_lines.append("<hr>")
        elif s.startswith("- "):
            out_lines.append(f"<li>{_md_inline(s[2:])}</li>")
        elif s.strip().startswith(tuple(f"{n}." for n in range(1, 10))):
            out_lines.append(f"<li>{_md_inline(s.split('.', 1)[1].strip())}</li>")
        elif s.startswith("*") and s.endswith("*") and len(s) > 2:
            out_lines.append(f"<p><em>{_md_inline(s[1:-1])}</em></p>")
        elif not s:
            out_lines.append("<br>")
        else:
            out_lines.append(f"<p>{_md_inline(s)}</p>")

    if in_table:
        flush_table()

    return "\n".join(out_lines)


def _md_inline(s: str) -> str:
    s = _html_escape(s)
    # Bold + code
    import re
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;")
              .replace("<", "&lt;")
              .replace(">", "&gt;"))
