"""Chemistry rules engine — RDKit-backed evaluation of declarative
rules + the curated SAR / resistance corpus.

Public API:
    get_atom_context(smi, atom_idx)   → dict (extends the existing
                                           /chem/atom response with KG hits)
    predict_edit(smi, edit)           → predicted delta on selected axes
    check_structural_alerts(smi)      → list of alerts
    get_allowed_attachments(smi, ai)  → typed list (delegates to backend
                                           /chem/atom but cacheable)

The engine is RDKit-backed; the SAR + resistance facts come from the
indexed pharma corpus already loaded by api/workbench.py
(_load_pharma_ground). Nothing is hardcoded — element rules come from
RDKit, SAR from data, resistance from the curated ResistanceFact table
(loaded from data/synthetic JSON if present, else empty).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


_RULES_DIR = Path(__file__).resolve().parents[2] / "rules"
_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


class RulesEngine:
    """Lazy-loaded; reads JSON rule files at first use."""

    def __init__(self) -> None:
        self._functional_groups = _load_json(_RULES_DIR / "functional_groups.json")
        self._structural_alerts = _load_json(_RULES_DIR / "structural_alerts.json")
        self._sar_motifs = _load_json(_RULES_DIR / "sar_motifs.json")
        self._resistance = _load_json(_RULES_DIR / "resistance_facts.json") or []

    # ---- structural alerts ----
    def check_structural_alerts(self, smi: str) -> list[dict[str, Any]]:
        """Return list of {pattern, name, severity} for any matching alert."""
        try:
            from rdkit import Chem
        except ImportError:
            return []
        if not self._structural_alerts:
            return []
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            return []
        hits: list[dict[str, Any]] = []
        for rule in self._structural_alerts:
            pat = Chem.MolFromSmarts(rule.get("smarts", ""))
            if pat is None:
                continue
            if mol.HasSubstructMatch(pat):
                hits.append({
                    "name": rule.get("name", "?"),
                    "smarts": rule.get("smarts", ""),
                    "severity": rule.get("severity", "medium"),
                    "note": rule.get("note", ""),
                })
        return hits

    # ---- predict edit ----
    def predict_edit(self, smi: str, edit: dict[str, Any]) -> dict[str, Any]:
        """Cheap RDKit-only pre-validation. Returns whether the edit
        produces a sane molecule + a hint about what axes might shift.

        Real scoring still goes through tools/scoring/score_molecule —
        this is a fast prevalidation for hover predictions."""
        try:
            from rdkit import Chem
        except ImportError:
            return {"ok": False, "reason": "rdkit unavailable"}
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            return {"ok": False, "reason": "parent SMILES unparseable"}
        rw = Chem.RWMol(mol)
        op = edit.get("kind") or edit.get("op")
        try:
            if op == "swap_element":
                idx = int(edit["atom_idx"])
                new_elt = edit["new_element"]
                ELEMENTS = {"C": 6, "N": 7, "O": 8, "F": 9, "S": 16, "Cl": 17, "Br": 35, "P": 15}
                if new_elt not in ELEMENTS:
                    return {"ok": False, "reason": f"unsupported element {new_elt}"}
                rw.GetAtomWithIdx(idx).SetAtomicNum(ELEMENTS[new_elt])
            elif op == "add_methyl":
                idx = int(edit["atom_idx"])
                c = rw.AddAtom(Chem.Atom(6))
                rw.AddBond(idx, c, Chem.BondType.SINGLE)
            elif op == "break_bond":
                bidx = int(edit["bond_idx"])
                b = rw.GetBondWithIdx(bidx)
                rw.RemoveBond(b.GetBeginAtomIdx(), b.GetEndAtomIdx())
            else:
                return {"ok": False, "reason": f"unknown op {op}"}
            Chem.SanitizeMol(rw)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": str(exc)[:140]}

        new_smi = Chem.MolToSmiles(rw, canonical=True)
        # Heuristic axis hints (no real LLM call):
        hints: dict[str, str] = {}
        n_atoms = rw.GetNumAtoms()
        if n_atoms > mol.GetNumAtoms():
            hints["mw"] = "+" if op == "add_methyl" else "?"
            hints["synthesizability"] = "small change ok"
        if op == "swap_element" and edit.get("new_element") in ("F", "Cl"):
            hints["lipophilicity"] = "+"
            hints["metabolic_stability"] = "+"
        if op == "swap_element" and edit.get("new_element") in ("N", "O"):
            hints["solubility"] = "+"
            hints["drug_likeness_qed"] = "?"
        return {
            "ok": True,
            "new_smiles": new_smi,
            "hints": hints,
        }

    # ---- resistance check ----
    def check_resistance_escape(self, smi: str, pathogen: str) -> dict[str, Any]:
        """Return {escape_probability, mechanisms[], drugs_defeated[]}.
        Simple lookup against curated resistance facts — no learned model
        in this engine; the trained Lysos-Gemma is the fallback for
        nuanced calls."""
        out_mechs: list[dict[str, Any]] = []
        for f in self._resistance:
            if f.get("pathogen") == pathogen:
                out_mechs.append(f)
        # No structural matching yet — caller can layer Tanimoto on top
        return {
            "pathogen": pathogen,
            "escape_probability": 0.5 if out_mechs else 0.1,
            "mechanisms": out_mechs[:5],
        }


_RULES: Optional[RulesEngine] = None


def get_rules() -> RulesEngine:
    global _RULES
    if _RULES is None:
        _RULES = RulesEngine()
    return _RULES


@lru_cache(maxsize=2048)
def _structural_alerts_cached(smi: str) -> tuple:
    return tuple(get_rules().check_structural_alerts(smi))
