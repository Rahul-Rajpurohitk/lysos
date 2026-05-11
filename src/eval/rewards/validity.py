"""Reward: SMILES validity.

A generated string scores 1.0 only if it parses AND represents a single
connected molecule with no stray solvent fragments. Disconnected pieces,
isolated atoms, or free water/ions drop the score proportionally.

User-reported bug: a broken structure (3 fragments + 2 isolated atoms +
free H₂O floating around — clearly visible in the 2D builder) was being
scored validity=1.00. The old check only ran `MolFromSmiles is not None`,
which happily parses `CC.O.O` as a "valid" molecule with two waters
attached. That's syntactically valid but chemically unusable as a drug.
"""

from __future__ import annotations

from . import extract_smiles


# Common solvents / counterions that should be stripped, not counted as
# real "fragments" against the candidate. Anything else with 2+ atoms is
# treated as a real disconnected fragment.
_SOLVENT_SMILES = {
    "O", "[H]O[H]",                # water
    "[Na+]", "[K+]", "[Cl-]", "[Br-]", "[I-]", "[F-]",  # ions
    "Cl", "Br", "I", "F",          # halogen acids (HX shorthand)
    "[OH-]", "[NH4+]",
    "C(=O)O",                      # formate
    "CC(=O)O",                     # acetate
}


def _score_one(smi: str) -> float:
    """Return a validity score in [0, 1] reflecting connectivity quality.

    1.0  — single connected molecule, no solvent.
    0.7  — main candidate + at least one solvent fragment (H₂O, ions).
    0.3  — multiple non-solvent fragments (split structure).
    0.0  — unparseable, empty, or only solvent.
    """
    from rdkit import Chem
    if not smi:
        return 0.0
    mol = Chem.MolFromSmiles(smi)
    if mol is None or mol.GetNumAtoms() == 0:
        return 0.0
    # Break the molecule into connected pieces.
    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False)
    if len(frags) == 1:
        return 1.0
    # Multi-fragment: classify each piece. Check solvent list FIRST
    # so a single oxygen `O` (water) is counted as solvent, not
    # isolated. Isolated = single non-solvent heavy atom floating.
    real_pieces = 0
    solvent_pieces = 0
    isolated_pieces = 0
    for f in frags:
        n = f.GetNumAtoms()
        try:
            frag_smi = Chem.MolToSmiles(f)
        except Exception:
            frag_smi = ""
        if frag_smi in _SOLVENT_SMILES:
            solvent_pieces += 1
        elif n <= 1:
            isolated_pieces += 1
        else:
            real_pieces += 1
    if real_pieces == 0:
        return 0.0  # nothing left after stripping solvent
    if real_pieces == 1 and isolated_pieces == 0:
        # One real molecule + only solvent fragments — still drug-like,
        # just dirty. Mid-tier score.
        return 0.7 if solvent_pieces > 0 else 1.0
    # Multiple disconnected real pieces OR floating atoms — structurally
    # broken. Drop hard.
    return 0.3 if isolated_pieces == 0 else 0.0


def smiles_valid(samples: list[str], **_) -> list[float]:
    """Tiered validity: connectivity-aware. See _score_one for tiers."""
    from rdkit import RDLogger
    RDLogger.DisableLog("rdApp.*")  # suppress noisy parse warnings

    out = []
    for sample in samples:
        smi = extract_smiles(sample)
        if smi is None:
            out.append(0.0)
            continue
        try:
            out.append(_score_one(smi))
        except Exception:
            out.append(0.0)
    return out
