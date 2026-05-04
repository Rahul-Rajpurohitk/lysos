"""Apply a deterministic structural transformation to a SMILES.

These are the small, named edit operations the Editor agent invokes after
the Critic agent identifies a weakness. Faster + more controllable than
full REINVENT 4 RL — RDKit reaction SMARTS for common transformations.

REINVENT 4 (Apache, github.com/MolecularAI/REINVENT4) handles bigger moves
(scaffold-hopping, R-group enumeration); we wrap that in a separate tool.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.generative.transform_structure")


TRANSFORM_OPS: dict[str, dict] = {
    "add_hydroxyl": {
        "description": "Add an -OH group to an aromatic carbon",
        "smarts_rxn": "[c:1][H:2]>>[c:1][OH]",
        "rationale": "Improves QED via H-bond donor; reduces logP",
    },
    "add_fluorine": {
        "description": "Replace aromatic H with F (bioisostere)",
        "smarts_rxn": "[c:1][H:2]>>[c:1]F",
        "rationale": "Improves metabolic stability; mild logP increase; common bioisostere",
    },
    "add_methyl": {
        "description": "Replace aromatic H with -CH3",
        "smarts_rxn": "[c:1][H:2]>>[c:1]C",
        "rationale": "Increases logP/lipophilicity; modest steric block",
    },
    "add_amine": {
        "description": "Replace aromatic H with -NH2",
        "smarts_rxn": "[c:1][H:2]>>[c:1]N",
        "rationale": "Adds H-bond donor + acceptor; lowers logP; basic at physiological pH",
    },
    "swap_chloro_to_fluoro": {
        "description": "Replace -Cl with -F",
        "smarts_rxn": "[Cl]>>[F]",
        "rationale": "Smaller halogen; reduces logP; preserves electronic effect",
    },
    "swap_fluoro_to_chloro": {
        "description": "Replace -F with -Cl",
        "smarts_rxn": "[F]>>[Cl]",
        "rationale": "Larger halogen; increases logP; more steric bulk",
    },
    "add_sulfonamide": {
        "description": "Cap an amine with a sulfonamide",
        "smarts_rxn": "[NH2:1]>>[N:1]S(=O)(=O)C",
        "rationale": "PABA-mimic warhead; reduces basicity; metabolic stability",
    },
    "add_carboxyl": {
        "description": "Add -COOH",
        "smarts_rxn": "[c:1][H:2]>>[c:1]C(=O)O",
        "rationale": "Adds anionic group; lowers logP; can engage cationic pocket residues",
    },
    "ring_close": {
        "description": "Close a 5-ring across two ortho positions (heuristic)",
        "smarts_rxn": "[c:1][CX4:2][CX4:3][c:4]>>[c:1]1[CX4:2][CX4:3][c:4]1",
        "rationale": "Reduces rotatable bonds; improves QED; locks geometry",
    },
    "remove_methyl": {
        "description": "Strip an aromatic -CH3",
        "smarts_rxn": "[c:1]C>>[c:1][H]",
        "rationale": "Reduces logP; opens steric room",
    },
}


class TransformInput(BaseModel):
    smiles: str = Field(..., description="Source SMILES")
    op: str = Field(
        ...,
        description=f"Transformation. One of: {', '.join(TRANSFORM_OPS.keys())}",
    )


class TransformOutput(BaseModel):
    source_smiles: str
    op: str
    op_description: str
    op_rationale: str
    products: list[str] = Field(..., description="Resulting SMILES (may be multiple)")
    success: bool
    note: Optional[str] = None


@tool(
    description=(
        "Apply a deterministic structural transformation to a SMILES via "
        "RDKit reaction SMARTS. 10 named operations: add/swap/remove "
        "functional groups, halogen swap, ring close. Returns the modified "
        "SMILES + rationale. The Editor agent calls this after the Critic "
        "agent identifies a weakness."
    ),
    category="generative",
    input_model=TransformInput,
    output_model=TransformOutput,
    expected_duration_ms=80,
    tags=("generative", "rdkit", "transformation", "core"),
)
def transform_structure(smiles: str, op: str) -> TransformOutput:
    if op not in TRANSFORM_OPS:
        return TransformOutput(
            source_smiles=smiles,
            op=op,
            op_description="unknown",
            op_rationale="",
            products=[],
            success=False,
            note=f"Unknown op '{op}'. Valid: {sorted(TRANSFORM_OPS)}",
        )

    op_info = TRANSFORM_OPS[op]
    products: list[str] = []
    note = None

    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, rdChemReactions

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return TransformOutput(
                source_smiles=smiles, op=op,
                op_description=op_info["description"],
                op_rationale=op_info["rationale"],
                products=[], success=False,
                note="RDKit could not parse source SMILES",
            )

        rxn = rdChemReactions.ReactionFromSmarts(op_info["smarts_rxn"])
        product_sets = rxn.RunReactants((mol,))
        seen = set()
        for products_tuple in product_sets:
            for p in products_tuple:
                try:
                    Chem.SanitizeMol(p)
                    smi_out = Chem.MolToSmiles(p)
                    if smi_out and smi_out not in seen:
                        seen.add(smi_out)
                        products.append(smi_out)
                except Exception:  # noqa: BLE001
                    continue

        # Cap to 5 products (variants are usually positional isomers)
        products = products[:5]
        success = len(products) > 0
        if not success:
            note = "Reaction matched no atoms in source — try a different op"
    except ImportError:
        success = False
        note = "RDKit not installed"
    except Exception as exc:  # noqa: BLE001
        success = False
        note = f"Transformation error: {exc}"

    return TransformOutput(
        source_smiles=smiles,
        op=op,
        op_description=op_info["description"],
        op_rationale=op_info["rationale"],
        products=products,
        success=success,
        note=note,
    )
