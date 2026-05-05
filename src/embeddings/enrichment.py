"""Shared enrichment template for Gemini Embedding 2.

Why this exists:
  Gemini Embedding 2 has an 8192-token input window. Embedding bare
  SMILES (~7 tokens) wastes 99% of the capacity. Enriching with name +
  source + stereochemistry + RDKit physicochemical descriptors gives the
  embedder real semantic context (~150 tokens / row).

Critical invariant:
  EVERY call site that embeds a molecule MUST use the same template,
  otherwise we mix rich-text and bare-SMILES embeddings in the same
  3072-d space and cosine similarity becomes meaningless.

  This module is the single source of truth. Callers:
    - scripts/precompute_embeddings.py    (corpus, 30K refs, one-time)
    - src/eval/rewards/embedding_novelty.py (per-candidate at training)
    - src/inference/retrieval.py          (RAG document + query)
    - scripts/dedup_with_embeddings.py    (corpus dedup)
    - scripts/build_known_antibiotics_index.py
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

log = logging.getLogger(__name__)


def build_document_text(row: Mapping[str, Any]) -> str:
    """Build the enriched embedding text for an indexed compound.

    Expected fields (all from `data/processed/known-antibiotics-canonical
    .parquet`):
      smiles, name, source, is_peptide, stereo_state, n_chiral_total,
      n_chiral_defined, inchi_key, mw, logp, hba, hbd, rotatable_bonds,
      ring_count, heavy_atoms, tpsa, qed
    """
    name = row.get("name") or "unnamed"
    source = row.get("source") or "unknown"
    smiles = row.get("smiles") or ""
    inchi_key = row.get("inchi_key") or ""
    is_peptide = bool(row.get("is_peptide"))

    parts: list[str] = [
        f"Drug: {name} (source: {source}).",
        f"Type: {'peptide' if is_peptide else 'small molecule'}.",
    ]

    stereo = row.get("stereo_state")
    if stereo and stereo != "achiral":
        n_def = int(row.get("n_chiral_defined") or 0)
        n_tot = int(row.get("n_chiral_total") or 0)
        parts.append(f"Stereochemistry: {stereo} ({n_def}/{n_tot} chiral defined).")

    if smiles:
        parts.append(f"SMILES: {smiles}")
    if inchi_key:
        parts.append(f"InChIKey: {inchi_key}")

    mw = _safe_float(row.get("mw"))
    logp = _safe_float(row.get("logp"))
    tpsa = _safe_float(row.get("tpsa"))
    qed = _safe_float(row.get("qed"))
    if any(v is not None for v in (mw, logp, tpsa, qed)):
        kvs = []
        if mw is not None:   kvs.append(f"MW {mw:.1f} Da")
        if logp is not None: kvs.append(f"logP {logp:.2f}")
        if tpsa is not None: kvs.append(f"TPSA {tpsa:.1f} A^2")
        if qed is not None:  kvs.append(f"QED {qed:.2f}")
        parts.append(f"Physicochemical: {', '.join(kvs)}.")

    hba = _safe_int(row.get("hba"))
    hbd = _safe_int(row.get("hbd"))
    rot = _safe_int(row.get("rotatable_bonds"))
    rings = _safe_int(row.get("ring_count"))
    heavy = _safe_int(row.get("heavy_atoms"))
    if any(v is not None for v in (hba, hbd, rot, rings, heavy)):
        kvs = []
        if hba is not None:   kvs.append(f"{hba} HBA")
        if hbd is not None:   kvs.append(f"{hbd} HBD")
        if rot is not None:   kvs.append(f"{rot} rotatable bonds")
        if rings is not None: kvs.append(f"{rings} rings")
        if heavy is not None: kvs.append(f"{heavy} heavy atoms")
        parts.append(f"Lipinski: {', '.join(kvs)}.")

    return " ".join(parts)


def build_query_text(smiles: str, *, name: str = "candidate",
                     source: str = "generated") -> str:
    """Build matching enriched text from a bare SMILES at query time.

    Computes the same RDKit descriptors used in the document-side template
    so the asymmetric retrieval (RETRIEVAL_DOCUMENT vs RETRIEVAL_QUERY)
    operates over the same semantic feature space.

    Falls back to bare-SMILES if RDKit can't parse — caller should treat
    such cases as low-quality.
    """
    if not smiles or not smiles.strip():
        return ""

    try:
        from rdkit import Chem, RDLogger
        from rdkit.Chem import AllChem, Crippen, Descriptors, rdMolDescriptors
        from rdkit.Chem import inchi as rdinchi
        from rdkit.Chem import QED
        RDLogger.DisableLog("rdApp.*")
    except ImportError:
        # No RDKit → only build the minimal envelope; embedder still gets
        # SMILES as semantic anchor.
        return (
            f"Drug: {name} (source: {source}). "
            f"Type: small molecule. "
            f"SMILES: {smiles}"
        )

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return f"Drug: {name} (source: {source}). SMILES: {smiles} [invalid]"

    # Match the document-side fields where computable
    row: dict[str, Any] = {
        "name": name,
        "source": source,
        "smiles": smiles,
        "is_peptide": False,  # query molecules are typically small-molecule SMILES
    }
    try:
        row["inchi_key"] = rdinchi.MolToInchiKey(mol)
    except Exception:
        row["inchi_key"] = ""

    # Stereochemistry summary
    chiral = Chem.FindMolChiralCenters(
        mol, includeUnassigned=True, useLegacyImplementation=False,
    )
    n_total = len(chiral)
    n_defined = sum(1 for _, t in chiral if t in ("R", "S"))
    if n_total == 0:
        row["stereo_state"] = "achiral"
    elif n_defined == n_total:
        row["stereo_state"] = "defined"
    elif n_defined == 0:
        row["stereo_state"] = "undefined"
    else:
        row["stereo_state"] = "partial"
    row["n_chiral_total"] = n_total
    row["n_chiral_defined"] = n_defined

    # Physicochemical
    row["mw"] = Descriptors.MolWt(mol)
    row["logp"] = Crippen.MolLogP(mol)
    row["tpsa"] = Descriptors.TPSA(mol)
    try:
        row["qed"] = QED.qed(mol)
    except Exception:
        row["qed"] = None
    row["hba"] = rdMolDescriptors.CalcNumHBA(mol)
    row["hbd"] = rdMolDescriptors.CalcNumHBD(mol)
    row["rotatable_bonds"] = rdMolDescriptors.CalcNumRotatableBonds(mol)
    row["ring_count"] = rdMolDescriptors.CalcNumRings(mol)
    row["heavy_atoms"] = mol.GetNumHeavyAtoms()

    return build_document_text(row)


# ── helpers ────────────────────────────────────────────────────────────


def _safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        i = int(v)
        return i
    except (TypeError, ValueError):
        return None


# Sanity-check helper — makes sure document- and query-side text shapes
# match for an indexed compound vs its plain SMILES.
def _selfcheck() -> None:
    sample_row = {
        "name": "amoxicillin", "source": "drugcentral", "is_peptide": False,
        "smiles": "CC1(C)S[C@@H]2[C@H](NC(=O)[C@@H](N)c3ccc(O)cc3)C(=O)N2[C@H]1C(=O)O",
        "inchi_key": "LSQZJLSUYDQPKJ-NJBDSQKTSA-N",
        "stereo_state": "defined", "n_chiral_total": 4, "n_chiral_defined": 4,
        "mw": 365.4, "logp": -1.1, "tpsa": 132.0, "qed": 0.55,
        "hba": 4, "hbd": 4, "rotatable_bonds": 4, "ring_count": 3, "heavy_atoms": 25,
    }
    doc = build_document_text(sample_row)
    qry = build_query_text(sample_row["smiles"], name="amoxicillin", source="drugcentral")
    print("DOC:", doc)
    print()
    print("QRY:", qry)


if __name__ == "__main__":
    _selfcheck()
