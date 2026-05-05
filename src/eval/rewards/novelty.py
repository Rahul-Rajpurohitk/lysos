"""Reward: Tanimoto distance to nearest known antibiotic.

Computes ECFP4 (Morgan) fingerprint similarity of generated molecule to
the nearest known antibiotic in the reference set. Higher distance =
more novel.

A `threshold` controls how aggressively we reward novelty:
  - distance < threshold (too similar to known)  -> low reward
  - distance >= threshold                        -> rewards scale up

This prevents the model from just regurgitating known antibiotics OR
generating completely random structures with no antibacterial signal.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from . import extract_smiles

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_reference_fingerprints(reference_path: str):
    """Load reference SMILES once, compute ECFP4 fingerprints."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem

    RDLogger.DisableLog("rdApp.*")

    p = Path(reference_path)
    if not p.exists():
        log.warning("reference set not found at %s — novelty reward will return 1.0 always", p)
        return None

    fps = []
    # Support both .parquet (canonical, post-cleanup) and .smiles (legacy text)
    if p.suffix == ".parquet":
        import pandas as pd
        df = pd.read_parquet(p)
        smiles_iter = (s for s in df["smiles"] if isinstance(s, str))
    else:
        # Legacy text file path; tolerate non-UTF8 bytes via errors=replace
        def _smiles_from_text():
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    yield line.split()[0]
        smiles_iter = _smiles_from_text()

    for smi in smiles_iter:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            continue
        fps.append(AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048))
    log.info("loaded %d reference antibiotic fingerprints from %s", len(fps), p)
    return fps


def tanimoto_distance_to_known(
    samples: list[str],
    *,
    reference_set: str = "data/processed/known-antibiotics.smiles",
    threshold: float = 0.6,
    **_,
) -> list[float]:
    """Reward in [0, 1]. Higher = more novel vs known antibiotics.

    distance = 1 - max_tanimoto_similarity_to_reference

    If distance >= threshold, reward = distance.
    If distance < threshold, reward = distance * (distance / threshold)^2 — quadratic penalty.
    """
    from rdkit import Chem, DataStructs, RDLogger
    from rdkit.Chem import AllChem

    RDLogger.DisableLog("rdApp.*")

    fps = _load_reference_fingerprints(reference_set)
    if fps is None:
        # No reference — all samples count as novel
        return [1.0] * len(samples)

    out = []
    for sample in samples:
        smi = extract_smiles(sample)
        if smi is None:
            out.append(0.0)
            continue
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            out.append(0.0)
            continue
        try:
            qfp = AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048)
            sims = DataStructs.BulkTanimotoSimilarity(qfp, fps)
            max_sim = max(sims) if sims else 0.0
            distance = 1.0 - max_sim
            if distance >= threshold:
                reward = distance
            else:
                # Penalty: too similar
                reward = distance * (distance / threshold) ** 2
            out.append(float(reward))
        except Exception:  # noqa: BLE001
            out.append(0.0)
    return out
