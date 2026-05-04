"""Find the most similar known antibiotics by Gemini Embedding 2 cosine.

Powers the "find similar known drugs" UI panel and gives the agent context
about which drug class a candidate resembles.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from typing import Optional
from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.scoring.find_similar_drugs")

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


class FindSimilarInput(BaseModel):
    smiles: str = Field(..., description="Query SMILES")
    k: int = Field(5, ge=1, le=20, description="Number of similar drugs to return")
    similarity_metric: str = Field(
        "embedding_cosine",
        description="'embedding_cosine' (Gemini-2) or 'tanimoto' (Morgan FP)",
    )


class SimilarDrug(BaseModel):
    name: str
    smiles: str
    similarity: float
    drug_class: Optional[str] = None
    note: Optional[str] = None


class FindSimilarOutput(BaseModel):
    query_smiles: str
    similarity_metric: str
    matches: list[SimilarDrug]
    interpretation: str


@tool(
    description=(
        "Find top-K most similar known antibiotics to a query SMILES using "
        "either Gemini Embedding 2 cosine (semantic, default) or Morgan FP "
        "Tanimoto (structural). Returns drug name + class + note."
    ),
    category="scoring",
    input_model=FindSimilarInput,
    output_model=FindSimilarOutput,
    expected_duration_ms=400,
    tags=("scoring", "similarity", "rag", "core"),
)
def find_similar_drugs(
    smiles: str,
    k: int = 5,
    similarity_metric: str = "embedding_cosine",
) -> FindSimilarOutput:
    matches: list[SimilarDrug] = []
    interpretation = ""

    if similarity_metric == "embedding_cosine":
        try:
            from src.inference.retrieval import find_similar_known_drugs
            results = find_similar_known_drugs(smiles, k=k)
            for r in results:
                matches.append(SimilarDrug(
                    name=r.get("name", "unknown"),
                    smiles=r.get("smiles", ""),
                    similarity=float(r.get("similarity", 0.0)),
                    drug_class=r.get("source"),
                ))
        except Exception as exc:  # noqa: BLE001
            log.warning("retrieval module failed: %s — falling back to Tanimoto", exc)
            similarity_metric = "tanimoto"

    if similarity_metric == "tanimoto" and not matches:
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem
            from rdkit.DataStructs import TanimotoSimilarity
            import pandas as pd

            df = pd.read_parquet("data/processed/known-antibiotics.parquet")
            qmol = Chem.MolFromSmiles(smiles)
            if qmol is None:
                return FindSimilarOutput(
                    query_smiles=smiles,
                    similarity_metric="tanimoto",
                    matches=[],
                    interpretation="Query SMILES failed RDKit parsing.",
                )
            qfp = AllChem.GetMorganFingerprintAsBitVect(qmol, 2, nBits=2048)

            scored = []
            for _, row in df.iterrows():
                rmol = Chem.MolFromSmiles(row["smiles"])
                if rmol is None:
                    continue
                rfp = AllChem.GetMorganFingerprintAsBitVect(rmol, 2, nBits=2048)
                sim = TanimotoSimilarity(qfp, rfp)
                scored.append((sim, row["name"], row["smiles"], row.get("source")))
            scored.sort(reverse=True)
            for sim, name, smi, src in scored[:k]:
                matches.append(SimilarDrug(
                    name=name, smiles=smi, similarity=float(sim), drug_class=src,
                ))
        except Exception as exc:  # noqa: BLE001
            log.warning("Tanimoto fallback also failed: %s", exc)
            return FindSimilarOutput(
                query_smiles=smiles,
                similarity_metric="error",
                matches=[],
                interpretation=f"Both similarity backends failed: {exc}",
            )

    if matches:
        top = matches[0]
        interpretation = (
            f"Closest known drug: {top.name} (similarity {top.similarity:.2f}, "
            f"class: {top.drug_class or 'unknown'}). "
        )
        if top.similarity >= 0.85:
            interpretation += "Very high similarity — candidate is essentially a known drug analog."
        elif top.similarity >= 0.5:
            interpretation += "Moderate similarity — same scaffold family, novel substitution."
        else:
            interpretation += "Low similarity — candidate explores novel chemical space."
    else:
        interpretation = "No similar drugs found in the indexed library."

    return FindSimilarOutput(
        query_smiles=smiles,
        similarity_metric=similarity_metric,
        matches=matches,
        interpretation=interpretation,
    )
