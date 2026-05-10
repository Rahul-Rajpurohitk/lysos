"""Knowledge brief endpoint — unified per-pathogen "command center" data.

One endpoint serves two consumers:
  1. Frontend KnowledgeHubCard — structured panels (top targets, top
     resistance genes, drug-class pressure, validated PDBs, scoring
     guidance).
  2. Agents (Designer / Critic / Editor / Strategist) — receive a
     markdown brief injected into their prompt as static context so
     every reasoning call is grounded in the same domain knowledge
     instead of rediscovering MRSA/Mtb basics each turn.

The brief is intentionally compact (~ 400-700 tokens) and stable
within a session — caches per-pathogen for 5 minutes so workflows
that fire 4 agent calls don't re-render four times.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

log = logging.getLogger("api.knowledge")
router = APIRouter(prefix="/workbench", tags=["knowledge"])

# 5-minute cache: pathogen → (timestamp, payload)
_brief_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_S = 300.0


def _cached_brief(pathogen: str) -> Optional[dict[str, Any]]:
    rec = _brief_cache.get(pathogen)
    if not rec:
        return None
    ts, payload = rec
    if time.time() - ts > _CACHE_TTL_S:
        _brief_cache.pop(pathogen, None)
        return None
    return payload


def _store_brief(pathogen: str, payload: dict[str, Any]) -> None:
    _brief_cache[pathogen] = (time.time(), payload)


_CANONICAL_PATHOGENS = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
                        "Abaum", "Paer", "VRE", "NGono"]


def _normalize_pathogen(p: str) -> str:
    """Map a free-form input to the canonical key used by the registry.
    Tries case-insensitive match against the canonical set, then falls
    back to the input as-given (the registry will 404 if invalid)."""
    p = (p or "MRSA").strip()
    for canon in _CANONICAL_PATHOGENS:
        if canon.lower() == p.lower():
            return canon
    return p


def build_knowledge_brief(pathogen: str) -> dict[str, Any]:
    """Build the complete per-pathogen knowledge brief. Cached per
    pathogen for 5 minutes — exposed as a module-level fn so the
    agent harness can call it directly without going through HTTP."""
    pathogen = _normalize_pathogen(pathogen)
    cached = _cached_brief(pathogen)
    if cached:
        return cached

    from tools import registry  # local import — avoid bootstrap cycle
    from workspace.tools.amr.get_pathogen_resistome import EMPIRICAL_GUIDANCE

    rt = registry.get("get_pathogen_resistome")
    if not rt:
        raise HTTPException(503, "tool registry not initialized")
    rec = rt.call({"pathogen": pathogen})
    result = rec.get("result") or {}
    if not result:
        raise HTTPException(404, f"pathogen {pathogen} not in registry")

    # Structured payload for the UI
    full_name = result.get("full_name", pathogen)
    intrinsic = result.get("intrinsic_features", []) or []
    resistome = result.get("resistome", []) or []
    syndromes = result.get("common_syndromes", []) or []
    first_line = result.get("first_line_therapy", []) or []

    # Top resistance threats (already ordered in the registry, take 8)
    top_resistance = []
    for g in resistome[:8]:
        if isinstance(g, dict):
            top_resistance.append({
                "gene": g.get("gene") or g.get("name") or "?",
                "mechanism": g.get("mechanism") or "",
                "drug_classes_affected": g.get("drug_classes_affected") or g.get("affects") or [],
                "prevalence": g.get("prevalence") or g.get("freq") or None,
            })
        else:
            top_resistance.append({"gene": str(g), "mechanism": "", "drug_classes_affected": []})

    # Drug-class pressure: count how many resistance genes affect each class
    class_pressure: dict[str, int] = {}
    for g in resistome:
        if not isinstance(g, dict):
            continue
        for cls in (g.get("drug_classes_affected") or g.get("affects") or []):
            class_pressure[cls] = class_pressure.get(cls, 0) + 1
    class_pressure_sorted = sorted(class_pressure.items(), key=lambda x: -x[1])[:8]

    # Empirical-therapy / scoring context
    guidance = EMPIRICAL_GUIDANCE.get(pathogen, {}) or {}
    empirical = {
        "first_line": guidance.get("first_line", first_line),
        "syndromes": guidance.get("syndromes", syndromes),
        "context": guidance.get("context", ""),
    }

    # Targets — pull from validated PDB targets if registry has them
    validated_targets: list[dict[str, Any]] = []
    try:
        from workspace.api.chem_3d import PATHOGEN_TARGETS  # type: ignore
        for t in (PATHOGEN_TARGETS.get(pathogen) or [])[:6]:
            validated_targets.append({
                "name": t.get("name"), "pdb_id": t.get("pdb_id"),
                "description": t.get("description") or t.get("note") or "",
            })
    except Exception:  # noqa: BLE001
        pass

    # Build the markdown brief — agents consume this as static context.
    md_lines = [
        f"# {full_name} ({pathogen}) — pathogen brief",
        "",
        f"_Common syndromes_: {', '.join(syndromes[:5]) if syndromes else 'unspecified'}",
        "",
    ]
    if intrinsic:
        md_lines.append("**Intrinsic features**: " + "; ".join(intrinsic[:5]))
        md_lines.append("")
    if empirical["context"]:
        md_lines.append(f"**Clinical context**: {empirical['context']}")
        md_lines.append("")
    if empirical["first_line"]:
        md_lines.append("**First-line therapy** (avoid me-too compounds in this space):")
        for d in empirical["first_line"][:6]:
            md_lines.append(f"  - {d}")
        md_lines.append("")
    if top_resistance:
        md_lines.append("**Top resistance threats** (your candidate must escape these mechanisms):")
        for g in top_resistance[:6]:
            classes = ", ".join(g["drug_classes_affected"][:3])
            md_lines.append(f"  - **{g['gene']}** — {g['mechanism']}"
                            + (f" (hits: {classes})" if classes else ""))
        md_lines.append("")
    if class_pressure_sorted:
        md_lines.append("**Drug-class pressure** (how many resistance genes hit each class):")
        for cls, count in class_pressure_sorted[:6]:
            md_lines.append(f"  - {cls}: {count} resistance gene(s)")
        md_lines.append("")
    if validated_targets:
        md_lines.append("**Validated targets** (PDBs with curated pockets):")
        for t in validated_targets[:5]:
            md_lines.append(f"  - **{t['name']}** ({t['pdb_id']}) — {t['description']}")
        md_lines.append("")

    md_lines.extend([
        "---",
        "",
        "**Reasoning rules for this pathogen** — when you propose / critique / refine a SMILES:",
        "  1. Avoid scaffolds that overlap with first-line drugs above (cross-resistance risk).",
        "  2. Anticipate the top resistance mechanisms — bake escape into your design.",
        "  3. Prefer drug classes with low pressure scores.",
        "  4. Cite the specific resistance gene by name when justifying a critique.",
    ])

    payload = {
        "pathogen": pathogen,
        "full_name": full_name,
        "common_syndromes": syndromes,
        "intrinsic_features": intrinsic,
        "empirical": empirical,
        "top_resistance": top_resistance,
        "class_pressure": [{"drug_class": k, "n_genes": v} for k, v in class_pressure_sorted],
        "validated_targets": validated_targets,
        "n_total_resistance_genes": len(resistome),
        "markdown_brief": "\n".join(md_lines),
        "generated_ts": time.time(),
    }
    _store_brief(pathogen, payload)
    return payload


@router.get("/knowledge/matrix")
async def knowledge_matrix() -> dict[str, Any]:
    """Pathogen × drug-class pressure matrix.

    Iterates the 8 priority pathogens and for each, computes how many
    resistance genes hit each drug class. Rolls up into a single
    matrix the frontend renders as a heatmap (rows = pathogens,
    columns = top N drug classes union-aggregated across all)."""
    out_rows: list[dict[str, Any]] = []
    class_universe: dict[str, int] = {}  # class → total n_genes across all pathogens
    for p in _CANONICAL_PATHOGENS:
        try:
            brief = build_knowledge_brief(p)
        except HTTPException:
            continue
        cls_map: dict[str, int] = {}
        for entry in brief.get("class_pressure", []):
            k = entry.get("drug_class")
            v = entry.get("n_genes") or 0
            if not k:
                continue
            cls_map[k] = v
            class_universe[k] = class_universe.get(k, 0) + v
        out_rows.append({
            "pathogen": p,
            "full_name": brief.get("full_name"),
            "class_pressure": cls_map,
            "n_total_genes": brief.get("n_total_resistance_genes", 0),
            "first_line_count": len(brief.get("empirical", {}).get("first_line", [])),
            "validated_target_count": len(brief.get("validated_targets", [])),
        })
    # Pick the top 12 drug classes universe-wide for the columns
    top_classes = sorted(class_universe.items(), key=lambda kv: -kv[1])[:12]
    columns = [c for c, _ in top_classes]
    return {
        "rows": out_rows,
        "columns": columns,
        "column_totals": {c: class_universe[c] for c in columns},
        "n_pathogens": len(out_rows),
    }


@router.get("/knowledge/champions/all")
async def knowledge_champions_all() -> dict[str, Any]:
    """All 8 pathogen champions in one call — drives the champion vault
    card. Each entry: pathogen name + reigning best (or null) + brief
    headline."""
    from . import champions as _champ
    out: list[dict[str, Any]] = []
    for p in _CANONICAL_PATHOGENS:
        c = _champ.get(p)
        try:
            brief = build_knowledge_brief(p)
            full_name = brief.get("full_name")
        except HTTPException:
            full_name = p
        out.append({
            "pathogen": p,
            "full_name": full_name,
            "champion": c,
            "has_champion": bool(c),
        })
    return {
        "vault": out,
        "n_with_champion": sum(1 for e in out if e["has_champion"]),
        "n_total": len(out),
    }


@router.get("/knowledge/mutations/{pdb_id}")
async def knowledge_mutations(pdb_id: str) -> dict[str, Any]:
    """Known clinical mutations for a PDB target — used by the mutation
    atlas card on the Knowledge tab. Routes through the existing
    chem_resistance endpoint and returns the same shape."""
    from . import chem_resistance as _cr
    try:
        rec = await _cr.known_mutations(pdb_id.upper())
        return rec
    except HTTPException as exc:
        # No curated set — return empty shell so the frontend renders a
        # graceful "no mutations" state instead of a 404 popup.
        if exc.status_code == 404:
            return {"pdb_id": pdb_id.upper(), "target_name": "",
                    "pathogen": "", "n_mutations": 0, "mutations": []}
        raise


@router.get("/knowledge/network/{pathogen}")
async def knowledge_network(pathogen: str) -> dict[str, Any]:
    """Build a pathogen → gene → class graph for the resistance network
    visualization. Returns nodes + edges suitable for a force-directed
    or hierarchical layout."""
    pathogen = _normalize_pathogen(pathogen)
    brief = build_knowledge_brief(pathogen)

    nodes: list[dict[str, Any]] = [{"id": pathogen, "kind": "pathogen",
                                    "label": brief.get("full_name", pathogen),
                                    "tier": 0}]
    edges: list[dict[str, Any]] = []
    seen_classes: set[str] = set()

    for g in brief.get("top_resistance", []):
        gene_id = f"gene::{g.get('gene')}"
        nodes.append({
            "id": gene_id, "kind": "gene",
            "label": g.get("gene"), "mechanism": g.get("mechanism"),
            "tier": 1,
        })
        edges.append({"source": pathogen, "target": gene_id, "kind": "carries"})
        for cls in (g.get("drug_classes_affected") or []):
            cls_id = f"class::{cls}"
            if cls not in seen_classes:
                seen_classes.add(cls)
                nodes.append({"id": cls_id, "kind": "drug_class",
                              "label": cls, "tier": 2})
            edges.append({"source": gene_id, "target": cls_id, "kind": "blocks"})

    # First-line drugs as a fourth tier (what we should advance against)
    for drug in (brief.get("empirical", {}).get("first_line") or [])[:6]:
        drug_id = f"drug::{drug}"
        nodes.append({"id": drug_id, "kind": "first_line",
                      "label": drug, "tier": 3})

    return {
        "pathogen": pathogen,
        "full_name": brief.get("full_name"),
        "nodes": nodes,
        "edges": edges,
        "n_genes": sum(1 for n in nodes if n["kind"] == "gene"),
        "n_classes": sum(1 for n in nodes if n["kind"] == "drug_class"),
        "n_first_line": sum(1 for n in nodes if n["kind"] == "first_line"),
    }


# Path-with-variable LAST so the literal `/matrix`, `/champions/all`,
# `/mutations/{pdb_id}`, `/network/{pathogen}` routes get a chance to
# match before the catch-all {pathogen} parameter.

@router.get("/knowledge/{pathogen}")
async def knowledge(pathogen: str) -> dict[str, Any]:
    """Unified per-pathogen knowledge brief (structured + markdown)."""
    return build_knowledge_brief(pathogen)


@router.post("/knowledge/{pathogen}/refresh")
async def knowledge_refresh(pathogen: str) -> dict[str, Any]:
    """Force a refresh — bust the cache and rebuild."""
    _brief_cache.pop(_normalize_pathogen(pathogen), None)
    return build_knowledge_brief(pathogen)
