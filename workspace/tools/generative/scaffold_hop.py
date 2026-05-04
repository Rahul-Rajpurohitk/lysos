"""REINVENT 4-style scaffold hop — propose isosteric replacements."""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.generative.scaffold_hop")


# Common bioisosteric scaffold replacements
SCAFFOLD_HOPS: dict[str, list[str]] = {
    "phenyl": ["pyridine", "thiophene", "furan", "thiazole"],
    "carboxylic_acid": ["tetrazole", "sulfonamide", "acyl_sulfonamide"],
    "amide": ["sulfonamide", "ester", "ketone", "thiazole"],
    "ether": ["thioether", "sulfone"],
    "methyl": ["fluoro", "ethyl", "trifluoromethyl"],
    "halide": ["methyl", "trifluoromethyl", "cyano"],
}


class ScaffoldHopInput(BaseModel):
    smiles: str = Field(..., description="Source SMILES")
    n_alternatives: int = Field(5, ge=1, le=20)


class ScaffoldHopOutput(BaseModel):
    source_smiles: str
    alternatives: list[str]
    bioisostere_classes_tried: list[str]
    backend: str
    interpretation: str


@tool(
    description=(
        "Propose scaffold-hopped variants via bioisosteric replacement (REINVENT 4 "
        "scaffold-hop pattern). Returns N alternatives that preserve the "
        "pharmacophore while exploring novel chemical space."
    ),
    category="generative",
    input_model=ScaffoldHopInput,
    output_model=ScaffoldHopOutput,
    expected_duration_ms=200,
    tags=("generative", "scaffold_hop", "reinvent"),
)
def scaffold_hop(smiles: str, n_alternatives: int = 5) -> ScaffoldHopOutput:
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, rdChemReactions
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return ScaffoldHopOutput(
                source_smiles=smiles, alternatives=[],
                bioisostere_classes_tried=[], backend="rdkit_v0",
                interpretation="Source SMILES failed RDKit parsing.",
            )

        alternatives: set[str] = set()
        classes_tried: list[str] = []
        # Phenyl → pyridine/thiophene
        rxn_pairs = [
            ("c1ccccc1", "c1ccncc1", "phenyl→pyridine"),
            ("c1ccccc1", "c1ccsc1", "phenyl→thiophene"),
            ("[CH3]", "F", "methyl→fluoro"),
            ("[CH3]", "C(F)(F)F", "methyl→trifluoromethyl"),
            ("C(=O)O", "c1[nH]nnn1", "carboxyl→tetrazole"),
            ("C(=O)O", "S(=O)(=O)N", "carboxyl→sulfonamide"),
        ]
        for src, dst, label in rxn_pairs:
            try:
                rxn = rdChemReactions.ReactionFromSmarts(f"{src}>>{dst}")
                products = rxn.RunReactants((mol,))
                for ps in products:
                    for p in ps:
                        try:
                            Chem.SanitizeMol(p)
                            smi = Chem.MolToSmiles(p)
                            if smi and smi != smiles:
                                alternatives.add(smi)
                        except Exception:
                            continue
                classes_tried.append(label)
                if len(alternatives) >= n_alternatives:
                    break
            except Exception as exc:
                log.debug("scaffold-hop %s failed: %s", label, exc)

        alts_list = list(alternatives)[:n_alternatives]
        return ScaffoldHopOutput(
            source_smiles=smiles,
            alternatives=alts_list,
            bioisostere_classes_tried=classes_tried,
            backend="rdkit_v0",
            interpretation=(
                f"Proposed {len(alts_list)} bioisosteric scaffold-hop variants "
                f"using {len(classes_tried)} replacement classes. Real REINVENT 4 "
                f"would propose larger structural moves on Day 4."
            ),
        )
    except ImportError:
        return ScaffoldHopOutput(
            source_smiles=smiles, alternatives=[],
            bioisostere_classes_tried=[], backend="error",
            interpretation="RDKit not installed.",
        )
