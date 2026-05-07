"""inspect_atom — get rich chemistry context for a single atom.

Mirrors GET /workbench/chem/atom/{smiles_b64}/{atom_idx}. Used by the
agent to understand an atom (element, hybridization, bonds, free
valence) before proposing an edit.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..base import tool


class InspectAtomInput(BaseModel):
    smiles: str = Field(..., description="Current SMILES")
    atom_idx: int = Field(..., description="Index of the atom to inspect")


class AtomNeighbor(BaseModel):
    idx: int
    element: str
    bond: str


class InspectAtomOutput(BaseModel):
    atom_idx: int
    element: str
    atomic_number: int
    atomic_mass: float
    formal_charge: int
    is_aromatic: bool
    in_ring: bool
    ring_size: int
    explicit_valence: int
    implicit_valence: int
    n_hydrogens: int
    hybridization: str
    degree: int
    total_degree: int
    free_valence: int
    is_chiral: bool
    cip_code: str
    neighbors: List[AtomNeighbor]


@tool(
    name="inspect_atom",
    description=(
        "Detailed chemistry context for one atom: element, atomic number/"
        "mass, formal charge, aromaticity, ring membership, valence "
        "(explicit/implicit/free), hybridization (sp/sp²/sp³/sp³d/sp³d²), "
        "heavy-atom degree, chirality (R/S CIP code), and a list of "
        "bonded neighbors with bond orders."
    ),
    category="chem_workbench",
    input_model=InspectAtomInput,
    output_model=InspectAtomOutput,
    expected_duration_ms=15,
    tags=("chemistry", "rdkit", "inspect"),
)
def inspect_atom(smiles: str, atom_idx: int) -> InspectAtomOutput:
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError({"code": "unparseable_smiles", "message": f"unparseable SMILES: {smiles}"})
    if atom_idx < 0 or atom_idx >= mol.GetNumAtoms():
        raise ValueError({"code": "atom_index_out_of_range",
                          "message": f"atom_idx {atom_idx} out of range",
                          "atom_idx": atom_idx})
    atom = mol.GetAtomWithIdx(atom_idx)

    # Hybridization
    hyb_map = {
        Chem.HybridizationType.S: "s",
        Chem.HybridizationType.SP: "sp",
        Chem.HybridizationType.SP2: "sp²",
        Chem.HybridizationType.SP3: "sp³",
        Chem.HybridizationType.SP3D: "sp³d",
        Chem.HybridizationType.SP3D2: "sp³d²",
    }
    hyb = hyb_map.get(atom.GetHybridization(), "unspecified")

    # CIP code
    cip = ""
    try:
        Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
        if atom.HasProp("_CIPCode"):
            cip = atom.GetProp("_CIPCode")
    except Exception:  # noqa: BLE001
        pass

    # Neighbors
    nbrs = []
    for nb in atom.GetNeighbors():
        bond = mol.GetBondBetweenAtoms(atom_idx, nb.GetIdx())
        bt = "single"
        if bond:
            t = bond.GetBondType()
            bt = "double" if t == Chem.BondType.DOUBLE else \
                 "triple" if t == Chem.BondType.TRIPLE else \
                 "aromatic" if t == Chem.BondType.AROMATIC else "single"
        nbrs.append(AtomNeighbor(idx=nb.GetIdx(), element=nb.GetSymbol(), bond=bt))

    # Ring info
    in_ring = atom.IsInRing()
    ring_size = 0
    for ring in mol.GetRingInfo().AtomRings():
        if atom_idx in ring:
            ring_size = len(ring)
            break

    n_h = atom.GetTotalNumHs()
    return InspectAtomOutput(
        atom_idx=atom_idx,
        element=atom.GetSymbol(),
        atomic_number=atom.GetAtomicNum(),
        atomic_mass=round(atom.GetMass(), 3),
        formal_charge=atom.GetFormalCharge(),
        is_aromatic=atom.GetIsAromatic(),
        in_ring=in_ring,
        ring_size=ring_size,
        explicit_valence=atom.GetExplicitValence(),
        implicit_valence=atom.GetImplicitValence(),
        n_hydrogens=n_h,
        hybridization=hyb,
        degree=atom.GetDegree(),
        total_degree=atom.GetTotalDegree(),
        free_valence=n_h,
        is_chiral=atom.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED,
        cip_code=cip,
        neighbors=nbrs,
    )
