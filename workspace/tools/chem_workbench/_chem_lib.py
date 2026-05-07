"""Shared RDKit helpers for the chem_workbench tool category.

Single source of truth for: ELEMENTS dict, BOND_ORDERS, FG_TEMPLATES,
DEFAULT_VALENCE, FG_BOND_COST, BRANCHED_FGS, ANTIBIOTIC_REFERENCE.

The FastAPI endpoints in workbench.py and the @tool functions here both
import from this module so the operation semantics stay identical
across the two invocation paths (HTTP REST vs. function-call).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

ELEMENTS: Dict[str, int] = {
    "H": 1,  "He": 2,
    "Li": 3, "Be": 4, "B": 5,  "C": 6,  "N": 7,  "O": 8,  "F": 9,  "Ne": 10,
    "Na": 11, "Mg": 12, "Al": 13, "Si": 14, "P": 15, "S": 16, "Cl": 17, "Ar": 18,
    "K": 19, "Ca": 20,
    "Ti": 22, "V": 23, "Cr": 24, "Mn": 25, "Fe": 26, "Co": 27,
    "Ni": 28, "Cu": 29, "Zn": 30,
    "As": 33, "Se": 34, "Br": 35,
    "Mo": 42, "Ru": 44, "Rh": 45, "Pd": 46, "Ag": 47, "Cd": 48,
    "I": 53,
    "Pt": 78, "Au": 79, "Hg": 80,
}

DEFAULT_VALENCE: Dict[str, int] = {
    "H": 1, "B": 3, "C": 4, "N": 3, "O": 2, "F": 1,
    "Si": 4, "P": 3, "S": 2, "Cl": 1, "Br": 1, "I": 1,
    "Se": 2, "As": 3,
    "Li": 1, "Na": 1, "K": 1, "Mg": 2, "Ca": 2, "Al": 3,
    "Ti": 4, "V": 5, "Cr": 6, "Mn": 7, "Fe": 6, "Co": 6, "Ni": 6,
    "Cu": 4, "Zn": 4, "Mo": 6, "Ru": 6, "Pd": 4, "Ag": 4,
    "Pt": 6, "Au": 5, "Hg": 2,
}

FG_TEMPLATES: Dict[str, List[tuple]] = {
    "hydroxyl":   [("O", "single")],
    "methyl":     [("C", "single")],
    "amine":      [("N", "single")],
    "fluorine":   [("F", "single")],
    "chlorine":   [("Cl", "single")],
    "bromine":    [("Br", "single")],
    "iodine":     [("I", "single")],
    "thiol":      [("S", "single")],
    "carbonyl":   [("C", "single"), ("O", "double")],
    "aldehyde":   [("C", "single"), ("O", "double")],
    "carboxyl":   [("C", "single"), ("O", "double"), ("O", "single")],
    "ester":      [("O", "single"), ("C", "single"), ("O", "double"), ("C", "single")],
    "amide":      [("C", "single"), ("O", "double"), ("N", "single")],
    "nitro":      [("N", "single"), ("O", "double"), ("O", "single")],
    "sulfonyl":   [("S", "single"), ("O", "double"), ("O", "double")],
    "sulfonamide":[("S", "single"), ("O", "double"), ("O", "double"), ("N", "single")],
    "sulfide":    [("S", "single"), ("C", "single")],
    "phosphate":  [("O", "single"), ("P", "single"), ("O", "double"), ("O", "single"), ("O", "single")],
    "phosphonate":[("P", "single"), ("O", "double"), ("O", "single"), ("O", "single")],
    "cyano":      [("C", "single"), ("N", "triple")],
    "isocyano":   [("N", "single"), ("C", "triple")],
    "azido":      [("N", "single"), ("N", "double"), ("N", "double")],
    "trifluoromethyl": [("C", "single"), ("F", "single"), ("F", "single"), ("F", "single")],
    "trichloromethyl": [("C", "single"), ("Cl", "single"), ("Cl", "single"), ("Cl", "single")],
    "ethyl":      [("C", "single"), ("C", "single")],
    "vinyl":      [("C", "single"), ("C", "double")],
    "ethynyl":    [("C", "single"), ("C", "triple")],
    "methoxy":    [("O", "single"), ("C", "single")],
    "ethoxy":     [("O", "single"), ("C", "single"), ("C", "single")],
    "isopropyl":  [("C", "single"), ("C", "single"), ("C", "single")],
    "tert-butyl": [("C", "single"), ("C", "single"), ("C", "single"), ("C", "single")],
    "phenyl":     [("C", "single"), ("C", "aromatic"), ("C", "aromatic"),
                   ("C", "aromatic"), ("C", "aromatic"), ("C", "aromatic")],
}

BRANCHED_FGS = {
    "carbonyl", "carboxyl", "amide", "nitro", "sulfonyl",
    "sulfonamide", "phosphonate", "trifluoromethyl",
    "trichloromethyl", "isopropyl", "tert-butyl", "aldehyde",
}


def violation(code: str, message: str, **kwargs: Any) -> Dict[str, Any]:
    """Structured violation envelope (same shape as workbench.py)."""
    return {
        "code": code,
        "message": message,
        "hint": kwargs.get("hint", ""),
        "atom_idx": kwargs.get("atom_idx"),
        "bond_idx": kwargs.get("bond_idx"),
        "suggested_fix": kwargs.get("suggested_fix", ""),
    }


def get_bond_orders():
    """Returns RDKit BondType mapping. Imports lazily so this module is
    importable even when RDKit isn't installed (helpful for test envs)."""
    from rdkit import Chem
    return {
        "single":   Chem.BondType.SINGLE,
        "double":   Chem.BondType.DOUBLE,
        "triple":   Chem.BondType.TRIPLE,
        "aromatic": Chem.BondType.AROMATIC,
    }


def parse_and_kekulize(smiles: str):
    """Parse SMILES → RWMol with kekulization (so aromatic edits work)."""
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"unparseable SMILES: {smiles}")
    try:
        Chem.Kekulize(mol, clearAromaticFlags=True)
    except Exception:  # noqa: BLE001
        pass
    return Chem.RWMol(mol)


def sanitize_with_retry(rw) -> str:
    """Sanitize and return canonical SMILES. On valence violation, clear
    aromatic flags and retry. Raises on hard failure with a structured
    error message."""
    from rdkit import Chem
    try:
        Chem.SanitizeMol(rw)
    except Exception as exc:  # noqa: BLE001
        first_err = str(exc)
        try:
            for atom in rw.GetAtoms():
                atom.SetIsAromatic(False)
            for bond in rw.GetBonds():
                bond.SetIsAromatic(False)
                if bond.GetBondType() == Chem.BondType.AROMATIC:
                    bond.SetBondType(Chem.BondType.SINGLE)
            Chem.SanitizeMol(rw)
        except Exception as exc2:  # noqa: BLE001
            err_text = first_err.lower()
            if "valence" in err_text:
                code, hint, fix = "valence_violation", "Atom would exceed allowed valence.", "lower bond order or remove a neighbor"
            elif "aromatic" in err_text:
                code, hint, fix = "aromaticity_violation", "Aromatic constraint violated (Hückel rule).", "restore the ring or convert to non-aromatic"
            else:
                code, hint, fix = "chemistry_violation", "RDKit sanitize failed.", "undo this edit"
            raise ValueError({"code": code, "message": first_err, "hint": hint, "suggested_fix": fix, "retry_error": str(exc2)})
    return Chem.MolToSmiles(rw, canonical=True)
