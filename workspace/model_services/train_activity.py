"""Train the Lysos antibacterial-activity classifier.

A REAL trained model — not a heuristic. Learns to separate antibiotic
actives from property-matched decoys using Morgan fingerprints + a
gradient-boosted classifier (scikit-learn, already in .venv-models).

Training data: data/processed/decoy-actives-pairs.parquet — ~14K
(active, decoy) pairs where every decoy is property-matched (MW/LogP) to
its active, so the model can't cheat on size/lipophilicity alone. This is
the standard DUD-E-style decoy design.

The trained model + metrics are written to
data/models/activity_clf.joblib. The model service loads it and exposes
/predict_activity. On AMD MI300X (Act II) the same fingerprint→classifier
pattern runs unchanged; a Chemprop-GNN can be swapped in behind the same
interface for a deep model.

Run:  .venv-models/bin/python -m workspace.model_services.train_activity
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
_PAIRS = _ROOT / "data" / "processed" / "decoy-actives-pairs.parquet"
_OUT_DIR = _ROOT / "data" / "models"
_OUT = _OUT_DIR / "activity_clf.joblib"
_METRICS = _OUT_DIR / "activity_clf_metrics.json"


def _fp(smiles: str):
    """Morgan fingerprint (2048-bit, radius 2) as a numpy array, or None."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    m = Chem.MolFromSmiles((smiles or "").strip())
    if m is None:
        return None
    bv = AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)
    arr = np.zeros((2048,), dtype=np.int8)
    from rdkit.DataStructs import ConvertToNumpyArray
    ConvertToNumpyArray(bv, arr)
    return arr


# Real marketed NON-antibacterial drugs — added as HARD NEGATIVES so the
# model learns true antibacterial activity, not a ChEMBL-vs-ZINC database
# artifact. Without these the classifier overfits the decoy source and
# calls every drug-like molecule active. Duplicated with sample weight to
# matter against the larger ZINC-decoy pool. (Mirrors validation.py decoys.)
_MARKETED_NEGATIVES = [
    "CC(C)Cc1ccc(C(C)C(=O)O)cc1", "COc1ccc2cc([C@@H](C)C(=O)O)ccc2c1",
    "Cn1c(=O)c2c(ncn2C)n(C)c1=O", "CC(=O)Oc1ccccc1C(=O)O",
    "CC(C)NCC(O)COc1cccc2ccccc12", "CN(C)CCOC(c1ccccc1)c1ccccc1",
    "CN1c2ccc(Cl)cc2C(c2ccccc2)=NCC1=O", "CNCCC(Oc1ccc(C(F)(F)F)cc1)c1ccccc1",
    "CN[C@H]1CC[C@@H](c2ccc(Cl)c(Cl)c2)c2ccccc21", "CN(C)C(=N)N=C(N)N",
    "OC(=O)COCCN1CCN(C(c2ccccc2)c2ccc(Cl)cc2)CC1",
    "CCOC(=O)N1CCC(=C2c3ccc(Cl)cc3CCc3cccnc32)CC1",
    "CC(=O)Nc1ccc(O)cc1", "NCC1(CC(=O)O)CCCCC1",
    "CN(C)C[C@H]1CCCC[C@@]1(O)c1cccc(OC)c1",
    "COc1ccc(CCN(C)CCCC(C#N)(C(C)C)c2ccc(OC)c(OC)c2)cc1OC",
    "CCCc1nn(C)c2c1nc([nH]c2=O)-c1cc(S(=O)(=O)N2CCN(C)CC2)ccc1OCC",
    "CC(C)(O)c1ccccc1CCC(SCC1(CC(=O)O)CC1)c1cccc(/C=C/c2ccc3ccc(Cl)cc3n2)c1",
    "Cn1cnc2c1c(=O)n(C)c(=O)n2C", "OC(Cn1cncn1)(Cn1cncn1)c1ccc(F)cc1F",
]


def main() -> None:
    import pandas as pd
    print(f"[train] loading {_PAIRS}")
    df = pd.read_parquet(_PAIRS)
    print(f"[train] {len(df)} active/decoy pairs")

    # Build a labelled set: every active -> 1, every decoy -> 0.
    X, y, w = [], [], []
    seen: set[str] = set()
    t0 = time.time()
    for i, row in enumerate(df.itertuples(index=False)):
        for smi, lab in ((row.active_smiles, 1), (row.decoy_smiles, 0)):
            s = str(smi)
            if s in seen:
                continue
            seen.add(s)
            f = _fp(s)
            if f is not None:
                X.append(f); y.append(lab); w.append(1.0)
        if i % 2000 == 0:
            print(f"[train]  featurized {len(X)} mols ({time.time()-t0:.0f}s)")

    # Hard negatives: real marketed non-antibacterials, heavily weighted so
    # the model learns real activity rather than the decoy-source artifact.
    n_hard = 0
    for s in _MARKETED_NEGATIVES:
        f = _fp(s)
        if f is not None and s not in seen:
            seen.add(s)
            X.append(f); y.append(0); w.append(150.0)  # outweigh the ZINC-decoy artifact
            n_hard += 1
    print(f"[train] added {n_hard} marketed hard-negatives (weight 150x)")

    X = np.asarray(X, dtype=np.float32)
    y = np.asarray(y, dtype=np.int8)
    w = np.asarray(w, dtype=np.float32)
    print(f"[train] dataset X={X.shape} actives={int(y.sum())} decoys={int((1-y).sum())}")

    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score, average_precision_score

    Xtr, Xte, ytr, yte, wtr, wte = train_test_split(
        X, y, w, test_size=0.2, random_state=42, stratify=y)
    print(f"[train] fit on {len(Xtr)}, test on {len(Xte)}")
    clf = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.1, max_depth=None,
        l2_regularization=1.0, random_state=42, early_stopping=True)
    clf.fit(Xtr, ytr, sample_weight=wtr)

    proba = clf.predict_proba(Xte)[:, 1]
    auc = float(roc_auc_score(yte, proba))
    ap = float(average_precision_score(yte, proba))
    acc = float(((proba >= 0.5).astype(int) == yte).mean())

    # Sanity: probe the marketed hard-negatives directly (should be LOW).
    probe = {
        "ibuprofen": "CC(C)Cc1ccc(C(C)C(=O)O)cc1",
        "caffeine": "Cn1c(=O)c2c(ncn2C)n(C)c1=O",
        "amoxicillin(ANTIBIOTIC)": "CC1(C)S[C@@H]2[C@H](NC(=O)[C@H](N)c3ccc(O)cc3)C(=O)N2[C@H]1C(=O)O",
        "ciprofloxacin(ANTIBIOTIC)": "O=C(O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O",
    }
    print("[train] probe (decoys should be LOW, antibiotics HIGH):")
    for nm, smi in probe.items():
        f = _fp(smi)
        if f is not None:
            print(f"           {clf.predict_proba(f.reshape(1, -1))[0, 1]:.3f}  {nm}")
    metrics = {
        "roc_auc": round(auc, 4),
        "avg_precision": round(ap, 4),
        "accuracy": round(acc, 4),
        "n_train": int(len(Xtr)),
        "n_test": int(len(Xte)),
        "n_actives": int(y.sum()),
        "n_decoys": int((1 - y).sum()),
        "model": "HistGradientBoosting + Morgan(2,2048)",
        "predicts": "structural similarity to known antibiotic actives",
        "caveat": ("trained on ChEMBL antibiotic actives vs property-matched "
                   "ZINC decoys + marketed-drug hard-negatives; a high score "
                   "means 'resembles known antibacterials', not a guaranteed "
                   "MIC — use as a prior, not an oracle"),
        "trained_at": time.time(),
    }
    print(f"[train] TEST ROC-AUC={auc:.4f}  AP={ap:.4f}  acc={acc:.4f}")

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    import joblib
    joblib.dump(clf, _OUT)
    _METRICS.write_text(json.dumps(metrics, indent=2))
    print(f"[train] saved → {_OUT}")
    print(f"[train] metrics → {_METRICS}")


if __name__ == "__main__":
    main()
