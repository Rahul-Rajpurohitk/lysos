"""Single-pass chemistry-corpus cleanup.

Closes audit gaps #1, #4, #13:
  #1  Peptide-as-SMILES contamination (DRAMP/DBAASP rows have AA sequences)
  #4  Stereo-undefined chiral centers (~20% of corpus, silent noise)
  #13 Tautomer state arbitrariness (ChEMBL deposits in random tautomers)

Pipeline per row:
  1. Detect amino-acid one-letter sequences via regex.
     - If len ≥ 5 and matches ^[ACDEFGHIKLMNPQRSTVWY]+$ → tag as peptide.
     - Try to convert to SMILES via Chem.MolFromSequence (proper backbone).
       If success → use the converted SMILES + tag stereo_state=peptide.
       If fail   → drop the row (cannot rescue).
  2. RDKit parse + sanitize. Drop on failure.
  3. Tautomer canonicalize via MolVS (rdMolStandardize.CanonicalTautomer).
  4. Stereo handling:
     - find chiral centers + record n_chiral_total / n_chiral_defined
     - if n_chiral_total > 0 and n_chiral_defined == 0 → stereo_state=undefined
     - else stereo_state = defined | partial | racemic | peptide
  5. Re-canonicalize SMILES via Chem.MolToSmiles (canonical=True, isomeric=True).
  6. Compute InChI key for cross-source dedup.

Inputs:
  data/processed/known-antibiotics.parquet            (39,748 rows, dirty)

Outputs:
  data/processed/known-antibiotics-canonical.parquet   (cleaned, canonicalized)
  data/processed/peptide-actives-canonical.parquet     (separated peptide rows)
  data/processed/known-antibiotics-cleanup-report.json (audit summary)

Run:
  /tmp/lysos_venv/bin/python scripts/clean_chemistry_corpus.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, inchi, Descriptors, Crippen, Lipinski, MolSurf, QED, rdMolDescriptors
from rdkit.Chem.MolStandardize import rdMolStandardize

# Silence noisy RDKit warnings
RDLogger.DisableLog("rdApp.*")

ROOT = Path(__file__).resolve().parents[1]
IN_PARQUET = ROOT / "data" / "processed" / "known-antibiotics.parquet"
OUT_SMALL  = ROOT / "data" / "processed" / "known-antibiotics-canonical.parquet"
OUT_PEP    = ROOT / "data" / "processed" / "peptide-actives-canonical.parquet"
OUT_REPORT = ROOT / "data" / "processed" / "known-antibiotics-cleanup-report.json"

PEPTIDE_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")

# Reusable singletons (constructing these on every call kills throughput)
_TAUT_ENUM = rdMolStandardize.TautomerEnumerator()
_NORMALIZER = rdMolStandardize.Normalizer()
_UNCHARGER = rdMolStandardize.Uncharger()
_CHOOSER = rdMolStandardize.LargestFragmentChooser()


def is_peptide_sequence(s: str) -> bool:
    """True if string is a likely amino-acid one-letter sequence."""
    if not isinstance(s, str): return False
    s = s.strip()
    if len(s) < 5 or len(s) > 200: return False
    if not PEPTIDE_RE.match(s): return False
    # Heuristic: real peptides have at least 3 distinct residues
    if len(set(s)) < 3: return False
    return True


def peptide_to_smiles(seq: str) -> str | None:
    """Convert an amino-acid one-letter sequence to a SMILES via RDKit."""
    try:
        mol = Chem.MolFromSequence(seq)
        if mol is None: return None
        return Chem.MolToSmiles(mol, isomericSmiles=True, canonical=True)
    except Exception:
        return None


def standardize_mol(mol: Chem.Mol) -> Chem.Mol | None:
    """Apply standardization pipeline: largest fragment → uncharge → normalize → tautomer canon."""
    try:
        mol = _CHOOSER.choose(mol)
        mol = _UNCHARGER.uncharge(mol)
        mol = _NORMALIZER.normalize(mol)
        # Tautomer canonicalization can be slow; cap molecule size
        if mol.GetNumHeavyAtoms() <= 80:
            mol = _TAUT_ENUM.Canonicalize(mol)
        return mol
    except Exception:
        return None


def stereo_state(mol: Chem.Mol) -> tuple[str, int, int]:
    """Return (state_label, n_chiral_total, n_chiral_defined)."""
    chiral = Chem.FindMolChiralCenters(mol, includeUnassigned=True, useLegacyImplementation=False)
    total = len(chiral)
    defined = sum(1 for _, c in chiral if c != "?")
    if total == 0:
        return ("achiral", 0, 0)
    if defined == total:
        return ("defined", total, defined)
    if defined == 0:
        return ("undefined", total, defined)
    return ("partial", total, defined)


def process_row(name: str, smiles: str, source: str) -> dict | None:
    """Single-row pipeline. Returns canonical record or None to drop."""
    record = {
        "original_smiles": smiles,
        "name": name,
        "source": source,
    }
    # Step 1: peptide detection
    if is_peptide_sequence(smiles):
        pep_smiles = peptide_to_smiles(smiles)
        if pep_smiles is None:
            return {"_drop_reason": "peptide_unconvertible", **record}
        record["peptide_sequence"] = smiles
        record["smiles"] = pep_smiles
        # Continue through the pipeline using the peptide's converted SMILES
        smiles = pep_smiles
    else:
        record["peptide_sequence"] = None

    # Step 2: parse + sanitize
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"_drop_reason": "invalid_smiles", **record}

    # Step 3-5: standardize + canonicalize
    mol = standardize_mol(mol)
    if mol is None:
        return {"_drop_reason": "standardize_failed", **record}

    # Step 4: stereo
    state, n_chiral_total, n_chiral_defined = stereo_state(mol)
    if record.get("peptide_sequence"):
        state = "peptide"

    canonical_smiles = Chem.MolToSmiles(mol, isomericSmiles=True, canonical=True)

    # Step 6: InChI key
    try:
        inchi_key = inchi.MolToInchiKey(mol)
    except Exception:
        inchi_key = None

    def _safe(fn, default=None):
        try:
            return fn()
        except Exception:
            return default

    return {
        "smiles": canonical_smiles,
        "original_smiles": record["original_smiles"],
        "name": name,
        "source": source,
        "stereo_state": state,
        "n_chiral_total": n_chiral_total,
        "n_chiral_defined": n_chiral_defined,
        "is_peptide": record.get("peptide_sequence") is not None,
        "peptide_sequence": record.get("peptide_sequence"),
        "inchi_key": inchi_key,
        "mw": _safe(lambda: Descriptors.MolWt(mol)),
        "logp": _safe(lambda: Crippen.MolLogP(mol)),
        "hba": _safe(lambda: Lipinski.NumHAcceptors(mol)),
        "hbd": _safe(lambda: Lipinski.NumHDonors(mol)),
        "rotatable_bonds": _safe(lambda: Lipinski.NumRotatableBonds(mol)),
        "ring_count": _safe(lambda: rdMolDescriptors.CalcNumRings(mol)),
        "heavy_atoms": mol.GetNumHeavyAtoms(),
        "tpsa": _safe(lambda: MolSurf.TPSA(mol)),
        "qed": _safe(lambda: QED.qed(mol)),
    }


def main():
    print(f"Loading {IN_PARQUET}")
    df = pd.read_parquet(IN_PARQUET)
    print(f"  rows: {len(df):,}")
    print(f"  source breakdown: {df['source'].value_counts().to_dict()}")

    rows: list[dict] = []
    drops: dict[str, int] = Counter()
    n_peptides = 0
    n_progress = 0

    for r in df.to_dict(orient="records"):
        out = process_row(r.get("name"), r.get("smiles"), r.get("source"))
        if out is None:
            drops["null_return"] += 1
        elif "_drop_reason" in out:
            drops[out["_drop_reason"]] += 1
        else:
            if out.get("is_peptide"):
                n_peptides += 1
            rows.append(out)
        n_progress += 1
        if n_progress % 5000 == 0:
            print(f"  progress: {n_progress:,}/{len(df):,} kept={len(rows):,} dropped={sum(drops.values()):,}")

    print(f"\nDone. kept={len(rows):,} dropped={sum(drops.values()):,}")
    print(f"  peptides recovered to SMILES: {n_peptides:,}")
    print(f"  drop reasons:")
    for k, v in drops.most_common():
        print(f"    {k:25s} {v:>6,}")

    # Stereo-state distribution
    state_dist = Counter(r["stereo_state"] for r in rows)
    print(f"\nStereo-state distribution:")
    for s, n in state_dist.most_common():
        print(f"  {s:10s} {n:>6,}")

    # Source distribution after cleanup
    src_dist = Counter(r["source"] for r in rows)
    print(f"\nSource distribution after cleanup:")
    for s, n in src_dist.most_common():
        print(f"  {s:15s} {n:>6,}")

    # InChI dedup audit (cross-source duplicates)
    ik_dup = Counter()
    for r in rows:
        if r.get("inchi_key"):
            ik_dup[r["inchi_key"]] += 1
    n_dups = sum(1 for c in ik_dup.values() if c > 1)
    print(f"\nUnique InChI keys: {len(ik_dup):,}")
    print(f"Cross-source dup keys: {n_dups:,}")

    # Split into peptide and small-molecule outputs
    sm_df = pd.DataFrame([r for r in rows if not r["is_peptide"]])
    pep_df = pd.DataFrame([r for r in rows if r["is_peptide"]])

    sm_df.to_parquet(OUT_SMALL, index=False)
    pep_df.to_parquet(OUT_PEP, index=False)

    report = {
        "input_rows": len(df),
        "kept_rows": len(rows),
        "small_molecule_rows": len(sm_df),
        "peptide_rows": len(pep_df),
        "dropped_rows": sum(drops.values()),
        "drop_reasons": dict(drops),
        "stereo_state_distribution": dict(state_dist),
        "source_distribution_after_cleanup": dict(src_dist),
        "unique_inchi_keys": len(ik_dup),
        "cross_source_duplicate_keys": n_dups,
    }
    OUT_REPORT.write_text(json.dumps(report, indent=2))

    print(f"\nWrote {OUT_SMALL}  ({len(sm_df):,} rows)")
    print(f"Wrote {OUT_PEP}    ({len(pep_df):,} rows)")
    print(f"Wrote {OUT_REPORT}")


if __name__ == "__main__":
    sys.exit(main())
