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


@router.get("/knowledge/{pathogen}")
async def knowledge(pathogen: str) -> dict[str, Any]:
    """Unified per-pathogen knowledge brief (structured + markdown)."""
    return build_knowledge_brief(pathogen)


@router.post("/knowledge/{pathogen}/refresh")
async def knowledge_refresh(pathogen: str) -> dict[str, Any]:
    """Force a refresh — bust the cache and rebuild."""
    _brief_cache.pop(pathogen.upper(), None)
    return build_knowledge_brief(pathogen)
