"""match_known — Tanimoto similarity vs the curated antibiotic reference set.

Tells the agent "this looks like Penicillin G with similarity 0.94" so
it can decide whether the candidate is novel or a known analog.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..base import tool


class MatchKnownInput(BaseModel):
    smiles: str = Field(..., description="Candidate SMILES to match")
    top_k: int = Field(3, description="Number of top matches to return")


@tool(
    name="match_known",
    description=(
        "Find the closest known antibiotic(s) to a candidate via Tanimoto "
        "on Morgan-2 fingerprints. Returns top_k matches with similarity "
        "in [0, 1] + an is_known flag (true when best similarity ≥ 0.95). "
        "Use to decide whether a candidate is novel or a known analog."
    ),
    category="chem_workbench",
    input_model=MatchKnownInput,
    expected_duration_ms=300,
    tags=("chemistry", "rdkit", "similarity", "library"),
)
def match_known(smiles: str, top_k: int = 3) -> Dict[str, Any]:
    from rdkit import Chem, DataStructs
    from rdkit.Chem import AllChem
    # Lazy-import the reference set to dodge circular deps.
    import sys, importlib
    if "workspace.api.workbench" in sys.modules:
        wb = sys.modules["workspace.api.workbench"]
    else:
        wb = importlib.import_module("workspace.api.workbench")
    ANTIBIOTIC_REFERENCE = getattr(wb, "ANTIBIOTIC_REFERENCE", [])

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError({"code": "unparseable_smiles", "message": f"unparseable SMILES: {smiles}"})
    cand_fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
    scored: List[tuple] = []
    for ref in ANTIBIOTIC_REFERENCE:
        rmol = Chem.MolFromSmiles(ref["smiles"])
        if rmol is None:
            continue
        rfp = AllChem.GetMorganFingerprintAsBitVect(rmol, 2, nBits=2048)
        sim = DataStructs.TanimotoSimilarity(cand_fp, rfp)
        scored.append((sim, ref))
    scored.sort(key=lambda x: x[0], reverse=True)
    matches = [
        {
            "name": ref["name"],
            "drug_class": ref["drug_class"],
            "mechanism": ref["mechanism"],
            "targets": ref["targets"],
            "year": ref["year"],
            "smiles": ref["smiles"],
            "similarity": round(sim, 4),
            "is_exact": sim >= 0.999,
        }
        for sim, ref in scored[:top_k]
    ]
    return {
        "matches": matches,
        "best": matches[0] if matches else None,
        "is_known": bool(matches and matches[0]["similarity"] >= 0.95),
        "candidate_smiles": smiles,
    }
