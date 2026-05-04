"""Reward: resistance_robustness — heuristic predicted resistance evasion.

Heuristic for now (we don't have a trained resistance predictor): evaluates
whether a SMILES has structural features known to evade specific resistance
mechanisms for the named pathogen.

Returns 1.0 if the candidate evades ≥ `min_evaded_mechanisms`. The heuristic
is intentionally conservative — it gives partial credit so the gradient
doesn't binary-step.
"""
from __future__ import annotations

from . import extract_smiles


# Per-pathogen resistance mechanisms we want to evade. Each entry: (label,
# substructure_smarts that we DO want to AVOID — the mechanism's pharmacophore).
EVASION_HEURISTICS = {
    "MRSA": [
        # mecA escapes most β-lactams; allosteric-engagement scaffolds (5GC) evade
        # We give credit for 5GC-like extended thiadiazole tail
        ("evade_PBP2a", "c1nc(N)sc1"),  # aminothiadiazole anchor
    ],
    "Mtb": [
        # Avoid INH-scaffold dependence on katG (nitro/hydrazide of the INH class)
        ("not_INH_class", "[NH2]N=C[c,n]"),  # negative SMARTS — should NOT match
        # rpoB stable: avoid the rifampin macrocyclic naphthalenone signature
        ("not_RIF_class", "c1ccc2cc3c(c(=O)cc23)c1"),
    ],
    "EColi-CRE": [
        # KPC inhibitor: prefer DBO (diazabicyclooctane) like avibactam
        ("evade_KPC", "C1CN2CCCN2C1"),
    ],
    "KpneuCRE": [
        ("evade_KPC", "C1CN2CCCN2C1"),
    ],
    "Abaum": [
        ("evade_OXA23", "C1CN2CCCN2C1"),  # durlobactam-class
    ],
    "Paer": [
        ("evade_MexAB_efflux", "[O-,O+,O,N+,N-]"),  # rough negative-charge marker
    ],
    "VRE": [
        # avoid vancomycin-derivative D-Ala binding — design new MoA
        ("not_glycopeptide", "[OH]C[CH]([NH])C(=O)"),  # negative
    ],
    "NGono": [
        # avoid penA-mosaic-affected β-lactam pharmacophore
        ("evade_penA_mosaic", "c1nc(N)sc1"),  # extended thiadiazole as in 5GC
    ],
}


def robustness_score(samples: list[str],
                      target_pathogen: str = "MRSA",
                      min_evaded_mechanisms: int = 2,
                      **_) -> list[float]:
    from rdkit import Chem
    rules = EVASION_HEURISTICS.get(target_pathogen, [])
    if not rules:
        # No heuristic for this pathogen — return mid-value
        return [0.5] * len(samples)

    out = []
    for s in samples:
        smi = extract_smiles(s)
        if smi is None:
            out.append(0.0); continue
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            out.append(0.0); continue
        n_evaded = 0
        for label, smarts in rules:
            patt = Chem.MolFromSmarts(smarts)
            if patt is None: continue
            has_match = mol.HasSubstructMatch(patt)
            # If label starts with "not_" we want NO match (negative SMARTS)
            if label.startswith("not_"):
                if not has_match:
                    n_evaded += 1
            else:
                if has_match:
                    n_evaded += 1
        # Linear ramp + bonus when threshold met
        score = n_evaded / max(len(rules), 1)
        if n_evaded >= min_evaded_mechanisms:
            score = min(1.0, score + 0.2)
        out.append(score)
    return out
