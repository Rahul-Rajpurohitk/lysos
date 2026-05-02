"""Structural-alert filters — graded validity beyond 'rdkit can parse'.

Rewards/Score a SMILES on chemical-development liability. Combines four
established alert sets (RDKit-bundled) plus property-based rules:

  - PAINS (pan-assay interference compounds)  — 480 SMARTS, RDKit FilterCatalog
  - BRENK (toxicophores + reactive groups)    — 76 SMARTS,  RDKit FilterCatalog
  - NIH (NIH MLSMR collection rejects)        — included via FilterCatalog
  - Lipinski Rule of 5                          — MW ≤ 500, logP ≤ 5, HBA ≤ 10, HBD ≤ 5
  - Veber rule                                  — RotBonds ≤ 10, TPSA ≤ 140

Returns a reward in [0, 1]:
  1.0   = passes all alerts
  -0.1 per PAINS hit (max -0.5)
  -0.1 per BRENK hit (max -0.4)
  -0.1 per Lipinski violation (max -0.3)
  -0.1 if Veber-fail
  Floor at 0.0.

This is meant to be COMPLEMENTARY to `validity.py` — that one is a hard
parse check; this is graded development-likeness.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from . import extract_smiles

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_filters():
    """Lazy-init the RDKit FilterCatalog. Returns None if rdkit missing."""
    try:
        from rdkit.Chem import FilterCatalog
    except ImportError:
        log.warning("rdkit FilterCatalog not available; structural_alerts=neutral")
        return None
    params = FilterCatalog.FilterCatalogParams()
    params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
    params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.BRENK)
    params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.NIH)
    return FilterCatalog.FilterCatalog(params)


def _check_lipinski_veber(mol):
    from rdkit.Chem import Crippen, Descriptors, Lipinski
    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    hba = Lipinski.NumHAcceptors(mol)
    hbd = Lipinski.NumHDonors(mol)
    rotb = Lipinski.NumRotatableBonds(mol)
    tpsa = Descriptors.TPSA(mol)
    lipinski_viol = sum([mw > 500, logp > 5, hba > 10, hbd > 5])
    veber_fail = (rotb > 10) or (tpsa > 140)
    return {
        "mw": mw, "logp": logp, "hba": hba, "hbd": hbd, "rotb": rotb,
        "tpsa": tpsa,
        "lipinski_violations": lipinski_viol,
        "veber_fail": bool(veber_fail),
    }


def structural_alerts_score(samples: list[str], **_) -> list[float]:
    """Reward in [0, 1]. Higher = cleaner chemistry (no PAINS, no toxicophores,
    drug-like by Lipinski + Veber)."""
    try:
        from rdkit import Chem, RDLogger
    except ImportError:
        return [1.0] * len(samples)
    RDLogger.DisableLog("rdApp.*")

    catalog = _get_filters()
    out: list[float] = []
    for sample in samples:
        smi = extract_smiles(sample)
        if not smi:
            out.append(0.0)
            continue
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            out.append(0.0)
            continue

        score = 1.0
        # Catalog hits (PAINS + BRENK + NIH). RDKit uses casing 'PAINS_A',
        # 'PAINS_B', 'PAINS_C', 'Brenk', 'NIH' — match case-insensitively.
        if catalog is not None:
            entries = catalog.GetMatches(mol)
            pains_hits = sum(
                1 for e in entries
                if "pains" in e.GetProp("FilterSet").lower()
            )
            brenk_hits = sum(
                1 for e in entries
                if e.GetProp("FilterSet").lower() == "brenk"
            )
            nih_hits = sum(
                1 for e in entries
                if e.GetProp("FilterSet").lower() == "nih"
            )
            score -= min(0.5, 0.10 * pains_hits)
            score -= min(0.4, 0.10 * brenk_hits)
            score -= min(0.3, 0.10 * nih_hits)

        # Property rules
        try:
            props = _check_lipinski_veber(mol)
            score -= min(0.3, 0.10 * props["lipinski_violations"])
            if props["veber_fail"]:
                score -= 0.10
        except Exception:  # noqa: BLE001
            pass

        out.append(max(0.0, min(1.0, score)))
    return out


def explain(smi: str) -> dict:
    """Return a structured report — for debugging / per-candidate explanation."""
    try:
        from rdkit import Chem, RDLogger
    except ImportError:
        return {"error": "rdkit missing"}
    RDLogger.DisableLog("rdApp.*")

    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return {"smiles": smi, "valid": False}

    out: dict = {"smiles": smi, "valid": True}
    catalog = _get_filters()
    if catalog is not None:
        entries = catalog.GetMatches(mol)
        out["alerts"] = [
            {"set": e.GetProp("FilterSet"),
             "scope": e.GetProp("Scope") if "Scope" in e.GetPropList() else "",
             "name": e.GetDescription()}
            for e in entries
        ]
    out.update(_check_lipinski_veber(mol))
    out["score"] = structural_alerts_score([f"SMILES: {smi}"])[0]
    return out
