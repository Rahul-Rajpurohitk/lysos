"""PocketXMol-style pocket-aware molecule proposer (Cell 2026).

Real PocketXMol requires a target PDB structure + the trained PocketXMol model
weights (~5GB). Pre-MI300X stub returns a panel of pocket-class-appropriate
SMILES drawn from the curated active-drug library; on Day 4 we wire real
PocketXMol inference.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.generative.propose_pocket_aware")


# Pocket-class → diverse SMILES seeds (real PocketXMol generates novel mols)
POCKET_SEEDS: dict[str, list[str]] = {
    "PBP_active_site": [
        "CC1(C)SC2C(NC(=O)Cc3ccccc3)C(=O)N2C1C(=O)O",  # penicillin G
        "CC1(C)SC2C(NC(=O)C(N)c3ccc(O)cc3)C(=O)N2C1C(=O)O",  # amoxicillin
        "CC1(C)C(O)N2C(=O)CC2(C)SC1=O",  # sulbactam
    ],
    "kinase_atp_pocket": [
        "Nc1ncnc2[nH]cnc12",  # adenine
        "O=C(O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O",  # ciprofloxacin (gyrase)
    ],
    "ribosome_50s": [
        "CC(=O)NCC1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1",  # linezolid
        "Cc1cc(C)c2c3oc(C)cc(C(=O)NC4C(O)C5OC(C)C(N(C)C)C5OC4)c3oc2c1",  # erythromycin-like
    ],
    "lipid_a": [
        "CCCCCCCCCC(=O)NCCC(N)C(=O)NCCC(N)C(=O)O",  # polymyxin-like
    ],
    "membrane_disrupt": [
        "CCCCCCCCCC(=O)NC(CC(=O)N)C(=O)NC(CC(=O)O)C(=O)O",  # daptomycin core
    ],
    "default": [
        "CC1=NC=C([N+](=O)[O-])N1CCO",  # metronidazole
        "Nc1nc2[nH]cnc2c(=O)[nH]1",  # purine
    ],
}


class ProposeInput(BaseModel):
    target_pdb: str = Field(..., description="Target PDB ID")
    pocket_class: Literal[
        "PBP_active_site", "kinase_atp_pocket", "ribosome_50s",
        "lipid_a", "membrane_disrupt", "default",
    ] = "default"
    n: int = Field(3, ge=1, le=10)


class ProposeOutput(BaseModel):
    target_pdb: str
    pocket_class: str
    proposals: list[str]
    backend: Literal["pocketxmol", "synthetic_dev"]
    interpretation: str


@tool(
    description=(
        "Propose pocket-aware candidate SMILES via PocketXMol (Cell 2026 — "
        "atom-level pocket-aware generation foundation model). Pass a target "
        "PDB ID + pocket class. Returns N candidate SMILES generated to fit "
        "the binding pocket geometry."
    ),
    category="generative",
    input_model=ProposeInput,
    output_model=ProposeOutput,
    expected_duration_ms=3000,
    needs_approval=True,
    tags=("generative", "pocketxmol", "novel"),
)
def propose_pocket_aware(target_pdb: str, pocket_class: str = "default", n: int = 3) -> ProposeOutput:
    seeds = POCKET_SEEDS.get(pocket_class, POCKET_SEEDS["default"])
    h = hashlib.sha256(target_pdb.encode()).digest()
    offset = int.from_bytes(h[:2], "big") % len(seeds)
    proposals = [seeds[(offset + i) % len(seeds)] for i in range(n)]
    return ProposeOutput(
        target_pdb=target_pdb,
        pocket_class=pocket_class,
        proposals=proposals,
        backend="synthetic_dev",
        interpretation=(
            f"Proposed {len(proposals)} candidate(s) for {target_pdb} pocket "
            f"({pocket_class}). Real PocketXMol on Day 4 will generate novel "
            f"atom-level designs; v0 returns curated seeds."
        ),
    )
