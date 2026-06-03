"""Bioisostere Studio — real matched-molecular-pair lead optimization.

THE core daily workflow of a medicinal chemist: take a lead, swap a group for
a known bioisostere (a fragment with similar properties but different
liabilities), and see how every property moves. This is the most valuable
interactive surface in the platform — it ACTS on the molecule with real
chemistry and lets the chemist explore the design space systematically.

How it works (all real, no LLM in the loop):
  1. A curated library of ~24 literature bioisosteric transformations, each a
     (SMARTS pattern → replacement) pair with the medchem RATIONALE for why a
     chemist makes that swap (metabolic stability, permeability, potency,
     tox mitigation, IP novelty).
  2. RDKit ReplaceSubstructs applies every applicable rule to the lead →
     valid, canonical, deduped analogs (matched molecular pairs).
  3. Each analog is scored through the REAL engine stack (composite score +
     SAScore synthesizability) and compared to the parent → a DELTA matrix.
  4. The frontend renders an interactive grid: parent vs each analog, the
     transformation, the rationale, and the per-property deltas — click to
     apply any analog as the new candidate.

Six-layer contract: service_store · this module · agent tool · workflow ·
orchestrator · frontend BioisostereStudioCard + dossier.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from functools import lru_cache
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.bioisostere")
router = APIRouter(prefix="/chem", tags=["bioisostere"])

_ARTIFACT_KIND = "bioisostere_run"
_SELF = os.getenv("LYSOS_SELF_URL", "http://127.0.0.1:7860")

# ─────────────────────────────────────────────────────────────────────
# The bioisostere rule library — literature matched-molecular-pair swaps.
# Each: id, label, SMARTS to match, replacement SMILES, the property it
# targets, and the medchem rationale. Curated from classic bioisosterism
# reviews (Meanwell 2011/2018, Patani & LaVoie 1996).
# ─────────────────────────────────────────────────────────────────────

_RULES: list[dict[str, str]] = [
    # — carboxylic-acid surrogates (improve permeability / keep acidity) —
    {"id": "cooh_to_tetrazole", "label": "COOH → tetrazole",
     "smarts": "[CX3](=O)[OX2H1]", "repl": "c1n[nH]nn1",
     "axis": "permeability/IP", "rationale":
     "Classic acid bioisostere: similar pKa + H-bonding, better membrane "
     "permeability and a fresh IP position."},
    {"id": "cooh_to_acylsulfonamide", "label": "COOH → acylsulfonamide",
     "smarts": "[CX3](=O)[OX2H1]", "repl": "C(=O)NS(C)(=O)=O",
     "axis": "potency/PK", "rationale":
     "Acidic acylsulfonamide retains the anion for target contact while "
     "tuning logD and metabolic clearance."},
    {"id": "cooh_to_oxadiazolone", "label": "COOH → 1,2,4-oxadiazol-5-one",
     "smarts": "[CX3](=O)[OX2H1]", "repl": "C1=NC(=O)ON1",
     "axis": "metabolism", "rationale":
     "Acid surrogate resistant to glucuronidation — slows phase-II clearance."},
    # — phenol surrogates —
    {"id": "phenol_to_F", "label": "phenol OH → F",
     "smarts": "[OX2H;$([OX2H][cX3])]", "repl": "F",
     "axis": "metabolism", "rationale":
     "Removes a glucuronidation/sulfation soft spot; F blocks the position "
     "and adds modest lipophilicity."},
    {"id": "phenol_to_methoxy", "label": "phenol OH → OMe",
     "smarts": "[OX2H;$([OX2H][cX3])]", "repl": "OC",
     "axis": "metabolism", "rationale":
     "Caps the metabolically-labile phenol while keeping the H-bond acceptor."},
    # — amide / carbonyl —
    {"id": "amide_to_nitrile", "label": "primary amide → nitrile",
     "smarts": "[CX3](=O)[NX3H2]", "repl": "C#N",
     "axis": "permeability", "rationale":
     "Nitrile is a small linear amide bioisostere — cuts MW + HBD, boosts "
     "permeability, keeps a dipole for binding."},
    {"id": "amide_to_oxadiazole", "label": "amide → 1,2,4-oxadiazole",
     "smarts": "[CX3](=O)[NX3]", "repl": "c1nc(C)no1",
     "axis": "metabolism/IP", "rationale":
     "Heterocyclic amide surrogate resistant to amidase hydrolysis; common "
     "metabolic-stability + IP play."},
    {"id": "ester_to_amide", "label": "ester → amide",
     "smarts": "[CX3](=O)[OX2][CX4]", "repl": "C(=O)N",
     "axis": "metabolism", "rationale":
     "Amides resist esterase cleavage — the standard fix for a fast-hydrolyzed "
     "ester."},
    # — aromatic-ring isosteres —
    {"id": "phenyl_to_pyridine", "label": "phenyl → pyridine",
     "smarts": "c1ccccc1", "repl": "c1ccncc1",
     "axis": "solubility/PK", "rationale":
     "Adds a basic N for solubility + a new H-bond acceptor; classic ring-N "
     "walk to tune potency and clearance."},
    {"id": "phenyl_to_thiophene", "label": "phenyl → thiophene",
     "smarts": "c1ccccc1", "repl": "c1ccsc1",
     "axis": "potency", "rationale":
     "Bioisosteric ring swap — smaller, more lipophilic; often improves "
     "pocket fit (note: watch thiophene metabolic activation)."},
    # — halogen / alkyl —
    {"id": "methyl_to_cf3", "label": "CH3 → CF3",
     "smarts": "[CH3]", "repl": "C(F)(F)F",
     "axis": "metabolism", "rationale":
     "Blocks oxidative metabolism at the methyl while raising lipophilicity "
     "and metabolic stability — a workhorse swap."},
    {"id": "cl_to_cf3", "label": "Cl → CF3",
     "smarts": "[Cl;$([Cl][c])]", "repl": "C(F)(F)F",
     "axis": "potency/PK", "rationale":
     "Similar steric/electron-withdrawing profile, often better metabolic "
     "stability and a distinct IP position."},
    {"id": "h_to_F_aromatic", "label": "aromatic H → F",
     "smarts": "[cH1]", "repl": "F",
     "axis": "metabolism", "rationale":
     "Fluorine scan: block a metabolic soft spot, modulate pKa of neighbours, "
     "tune potency with minimal steric cost."},
    # — ether / linker —
    {"id": "ether_to_methylene", "label": "ether O → CH2",
     "smarts": "[#6][OX2][#6]", "repl": "C",
     "axis": "metabolism", "rationale":
     "Removes an O-dealkylation soft spot; raises lipophilicity, removes an "
     "H-bond acceptor."},
    {"id": "sulfide_to_sulfone", "label": "sulfide S → sulfone",
     "smarts": "[#6][SX2][#6]", "repl": "S(=O)(=O)",
     "axis": "metabolism", "rationale":
     "Pre-oxidizing the thioether to the sulfone removes a metabolic liability "
     "and changes the polarity/H-bonding profile."},
    # — nitrile acid surrogate —
    {"id": "nitrile_to_tetrazole", "label": "nitrile → tetrazole",
     "smarts": "[CX2]#[NX1]", "repl": "c1n[nH]nn1",
     "axis": "potency/IP", "rationale":
     "Nitrile-to-tetrazole installs an acidic anion bioisostere for a fresh "
     "salt-bridge contact and a new IP position."},
    # — ring-N / ring-heteroatom walks —
    {"id": "pyridine_to_pyrimidine", "label": "pyridine → pyrimidine",
     "smarts": "c1ccncc1", "repl": "c1ccncn1",
     "axis": "solubility/PK", "rationale":
     "A second ring-N lowers logP and adds an H-bond acceptor — a classic "
     "potency/solubility ring-walk."},
    {"id": "thiophene_to_furan", "label": "thiophene → furan",
     "smarts": "c1ccsc1", "repl": "c1ccoc1",
     "axis": "metabolism", "rationale":
     "Furan for thiophene removes the S-oxidation activation liability while "
     "keeping a small lipophilic 5-ring."},
    # — halogen walks —
    {"id": "aryl_cl_to_f", "label": "aryl Cl → F",
     "smarts": "[Cl;$([Cl][c])]", "repl": "F",
     "axis": "metabolism", "rationale":
     "Smaller halogen — trims MW and lipophilicity while still blocking the "
     "position from oxidation."},
    {"id": "aryl_br_to_cl", "label": "aryl Br → Cl",
     "smarts": "[Br;$([Br][c])]", "repl": "Cl",
     "axis": "PK/IP", "rationale":
     "Halogen walk down the group — lighter, less lipophilic, distinct IP."},
    {"id": "aryl_i_to_br", "label": "aryl I → Br",
     "smarts": "[I;$([I][c])]", "repl": "Br",
     "axis": "PK", "rationale":
     "Drops the heaviest halogen for bromine — lower MW, less polarizable, "
     "often cleaner PK."},
]


# ─────────────────────────────────────────────────────────────────────
# RDKit helpers
# ─────────────────────────────────────────────────────────────────────

def _canon(smiles: str) -> Optional[str]:
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles((smiles or "").strip())
        if m is None or m.GetNumAtoms() == 0:
            return None
        return Chem.MolToSmiles(m)
    except Exception:  # noqa: BLE001
        return None


# The physicochemical profile a med-chemist watches on every swap. All real
# RDKit descriptors (local, no model, no network) so the full property
# movement is computed for the parent and every analog — which is the whole
# point of a matched-molecular-pair: see how EVERY property moves, not just
# the composite. Integer-valued keys render without decimals on the frontend.
_DESC_KEYS = ["mw", "clogp", "tpsa", "hbd", "hba", "rotb", "qed",
              "fsp3", "aromatic_rings", "heavy"]
_DESC_INT = {"hbd", "hba", "rotb", "aromatic_rings", "heavy"}
# Which direction is "better" for ranking the property strip. None = neutral
# (context-dependent — shown but not coloured good/bad).
_DESC_GOOD_DOWN = {"mw", "tpsa", "hbd", "hba", "rotb"}  # lower usually better
_DESC_GOOD_UP = {"qed", "fsp3"}                          # higher usually better
_DESC_LABEL = {"mw": "MW", "clogp": "cLogP", "tpsa": "TPSA", "hbd": "HBD",
               "hba": "HBA", "rotb": "RotB", "qed": "QED", "fsp3": "Fsp³",
               "aromatic_rings": "ArR", "heavy": "Heavy"}


@lru_cache(maxsize=4096)
def _descriptors(smiles: str) -> dict[str, float]:
    """Full physchem vector for one molecule — real RDKit, cached."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors, QED, rdMolDescriptors
        m = Chem.MolFromSmiles(smiles)
        if m is None:
            return {}
        return {
            "mw": round(Descriptors.MolWt(m), 1),
            "clogp": round(Crippen.MolLogP(m), 2),
            "tpsa": round(rdMolDescriptors.CalcTPSA(m), 1),
            "hbd": rdMolDescriptors.CalcNumHBD(m),
            "hba": rdMolDescriptors.CalcNumHBA(m),
            "rotb": rdMolDescriptors.CalcNumRotatableBonds(m),
            "qed": round(QED.qed(m), 3),
            "fsp3": round(rdMolDescriptors.CalcFractionCSP3(m), 2),
            "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(m),
            "heavy": m.GetNumHeavyAtoms(),
        }
    except Exception:  # noqa: BLE001
        return {}


def _swap_atoms(parent_smiles: str, analog_smiles: str) -> dict[str, list[int]]:
    """Atom indices that DIFFER between parent and analog — the matched-pair
    variable part — found via maximum common substructure. Indices are in the
    atom order RDKit assigns when parsing each (canonical) SMILES, which is the
    same order the 2D renderer uses, so they map 1:1 onto Mol2DThumb
    highlights. This is what lets the chemist SEE where the swap happened."""
    try:
        from rdkit import Chem
        from rdkit.Chem import rdFMCS
        pm = Chem.MolFromSmiles(parent_smiles)
        am = Chem.MolFromSmiles(analog_smiles)
        if pm is None or am is None:
            return {"parent": [], "analog": []}
        res = rdFMCS.FindMCS(
            [pm, am], timeout=3,
            atomCompare=rdFMCS.AtomCompare.CompareElements,
            bondCompare=rdFMCS.BondCompare.CompareOrder,
            ringMatchesRingOnly=True, completeRingsOnly=False,
            matchValences=False)
        if res.canceled or res.numAtoms == 0:
            return {"parent": [], "analog": []}
        core = Chem.MolFromSmarts(res.smartsString)
        if core is None:
            return {"parent": [], "analog": []}
        pmatch = set(pm.GetSubstructMatch(core))
        amatch = set(am.GetSubstructMatch(core))
        return {
            "parent": [i for i in range(pm.GetNumAtoms()) if i not in pmatch],
            "analog": [i for i in range(am.GetNumAtoms()) if i not in amatch],
        }
    except Exception:  # noqa: BLE001
        return {"parent": [], "analog": []}


# Structural-alert SMARTS — common liabilities a swap might inadvertently
# introduce. We flag only alerts the analog has that the PARENT did not, i.e.
# liabilities the transformation ADDED. Curated subset of Brenk/PAINS-style
# alerts relevant to antibacterial lead-opt.
_LIABILITIES: list[tuple[str, str, str]] = [
    ("nitro", "[NX3](=O)=O", "nitro — mutagenicity / nitroreductase risk"),
    ("aldehyde", "[CX3H1]=O", "aldehyde — reactive carbonyl"),
    ("michael_acceptor", "[CX3]=[CX3]C=O", "Michael acceptor — covalent reactivity"),
    ("epoxide", "[OX2r3]1[#6r3][#6r3]1", "epoxide — alkylating liability"),
    ("thiol", "[SX2H]", "free thiol — oxidation / promiscuity"),
    ("hydrazine", "[NX3][NX3H,NX3H2]", "hydrazine — tox liability"),
    ("aniline", "[NX3H2][cX3]", "aniline — metabolic activation risk"),
    ("alkyl_halide", "[CX4][Cl,Br,I]", "alkyl halide — alkylating liability"),
    ("thiophene", "c1ccsc1", "thiophene — CYP metabolic activation (watch)"),
]
_LIAB_DESC = {name: desc for name, _smarts, desc in _LIABILITIES}


@lru_cache(maxsize=4096)
def _alerts(smiles: str) -> tuple[str, ...]:
    """Structural-alert names present in a molecule."""
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles(smiles)
        if m is None:
            return ()
        hits = []
        for name, smarts, _desc in _LIABILITIES:
            patt = Chem.MolFromSmarts(smarts)
            if patt is not None and m.HasSubstructMatch(patt):
                hits.append(name)
        return tuple(hits)
    except Exception:  # noqa: BLE001
        return ()


@lru_cache(maxsize=512)
def _compiled():
    from rdkit import Chem
    out = []
    for r in _RULES:
        patt = Chem.MolFromSmarts(r["smarts"])
        repl = Chem.MolFromSmiles(r["repl"])
        if patt is not None and repl is not None:
            out.append((r, patt, repl))
    return out


def _apply_rules(parent_smiles: str, max_per_rule: int = 1) -> list[dict[str, Any]]:
    """Apply every applicable bioisostere rule → unique, valid analogs."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    m = Chem.MolFromSmiles(parent_smiles)
    if m is None:
        return []
    parent_canon = Chem.MolToSmiles(m)
    seen = {parent_canon}
    analogs = []
    for r, patt, repl in _compiled():
        if not m.HasSubstructMatch(patt):
            continue
        try:
            prods = AllChem.ReplaceSubstructs(m, patt, repl, replaceAll=False)
        except Exception:  # noqa: BLE001
            continue
        added = 0
        for p in prods:
            if added >= max_per_rule:
                break
            try:
                Chem.SanitizeMol(p)
                smi = Chem.MolToSmiles(p)
            except Exception:  # noqa: BLE001
                continue
            if not smi or smi in seen or Chem.MolFromSmiles(smi) is None:
                continue
            seen.add(smi)
            added += 1
            analogs.append({
                "smiles": smi, "rule_id": r["id"], "transformation": r["label"],
                "axis": r["axis"], "rationale": r["rationale"],
            })
    return analogs


# ─────────────────────────────────────────────────────────────────────
# Scoring through the real engines
# ─────────────────────────────────────────────────────────────────────

async def _score(cx: httpx.AsyncClient, smiles: str, pathogen: str) -> dict[str, Any]:
    out: dict[str, Any] = {"composite": None, "sa_score": None, "activity": None}
    try:
        r = await cx.post(f"{_SELF}/workbench/score",
                          json={"smiles": smiles, "target_pathogen": pathogen})
        if r.status_code == 200:
            out["composite"] = r.json().get("composite")
    except Exception:  # noqa: BLE001
        pass
    try:
        r = await cx.get(f"{_SELF}/workbench/chem/synthesizability",
                         params={"smiles": smiles})
        if r.status_code == 200:
            out["sa_score"] = r.json().get("sa_score")
    except Exception:  # noqa: BLE001
        pass
    try:
        r = await cx.get(f"{_SELF}/workbench/chem/activity",
                         params={"smiles": smiles})
        if r.status_code == 200:
            out["activity"] = r.json().get("activity_probability")
    except Exception:  # noqa: BLE001
        pass
    return out


async def _run_studio(parent: str, pathogen: str, max_analogs: int) -> dict[str, Any]:
    t0 = time.time()
    parent_canon = _canon(parent)
    if parent_canon is None:
        raise HTTPException(422, f"unparseable SMILES: {parent}")
    analogs = _apply_rules(parent_canon)[:max_analogs]
    parent_desc = _descriptors(parent_canon)
    parent_alerts = set(_alerts(parent_canon))

    async with httpx.AsyncClient(timeout=45.0) as cx:
        # Score the parent + every analog CONCURRENTLY — turns ~36 serial
        # round-trips into one bounded fan-out, so the studio stays snappy.
        parent_score, *scored = await asyncio.gather(
            _score(cx, parent_canon, pathogen),
            *[_score(cx, a["smiles"], pathogen) for a in analogs])

    for a, s in zip(analogs, scored):
        a["scores"] = s
        # Deltas vs parent (None-safe).
        a["delta_composite"] = (
            round(s["composite"] - parent_score["composite"], 3)
            if s["composite"] is not None and parent_score["composite"] is not None
            else None)
        a["delta_sa"] = (
            round(s["sa_score"] - parent_score["sa_score"], 2)
            if s["sa_score"] is not None and parent_score["sa_score"] is not None
            else None)
        a["delta_activity"] = (
            round((s["activity"] or 0) - (parent_score["activity"] or 0), 3)
            if s["activity"] is not None and parent_score["activity"] is not None
            else None)
        # Full physchem profile + per-property delta vector (the MMP payload).
        desc = _descriptors(a["smiles"])
        a["descriptors"] = desc
        a["delta_props"] = {
            k: round(desc[k] - parent_desc[k], 3)
            for k in _DESC_KEYS if k in desc and k in parent_desc}
        # Where the swap happened — atoms to highlight in parent + analog.
        a["swap_atoms"] = _swap_atoms(parent_canon, a["smiles"])
        # Liabilities the transformation ADDED (not already in the parent).
        added = [n for n in _alerts(a["smiles"]) if n not in parent_alerts]
        a["new_alerts"] = [{"name": n, "note": _LIAB_DESC.get(n, n)} for n in added]
        # An analog "improves" if composite up meaningfully without synthesis
        # getting much harder; "clean" means it added no new liability.
        a["clean"] = not added
        a["improved"] = bool(
            a["delta_composite"] is not None and a["delta_composite"] > 0.02
            and (a["delta_sa"] is None or a["delta_sa"] < 1.0))

    # Rank: improved first, then by composite delta.
    analogs.sort(key=lambda a: (a.get("improved", False),
                                a.get("delta_composite") or -9), reverse=True)
    n_improved = sum(1 for a in analogs if a.get("improved"))
    n_clean = sum(1 for a in analogs if a.get("clean"))
    best = analogs[0] if analogs else None
    return {
        "parent": parent_canon,
        "pathogen": pathogen,
        "parent_scores": parent_score,
        "parent_descriptors": parent_desc,
        "parent_alerts": sorted(parent_alerts),
        "desc_keys": _DESC_KEYS,
        "desc_meta": {k: {"label": _DESC_LABEL[k], "is_int": k in _DESC_INT,
                          "good": ("down" if k in _DESC_GOOD_DOWN
                                   else "up" if k in _DESC_GOOD_UP else "neutral")}
                      for k in _DESC_KEYS},
        "n_analogs": len(analogs),
        "n_improved": n_improved,
        "n_clean": n_clean,
        "analogs": analogs,
        "best_improvement": best if (best and best.get("improved")) else None,
        "elapsed_s": round(time.time() - t0, 2),
        "n_rules": len(_RULES),
        "computed_at": time.time(),
        "note": ("Matched molecular pairs from real RDKit bioisosteric "
                 "transformations, each scored through the live engine stack "
                 "and profiled across 10 physicochemical descriptors. Deltas "
                 "are vs the parent — predicted, for ranking."),
    }


# ─────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────

class StudioRequest(BaseModel):
    smiles: str
    pathogen: str = "MRSA"
    max_analogs: int = 12
    session_id: Optional[str] = None
    save: bool = True


@router.post("/bioisostere/run")
async def bioisostere_run(req: StudioRequest) -> dict[str, Any]:
    """Generate + score bioisosteric analogs of a lead — the matched-
    molecular-pair optimization grid."""
    n = max(1, min(int(req.max_analogs), 20))
    result = await _run_studio(req.smiles, req.pathogen, n)
    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, result, session_id=req.session_id,
            smiles=result["parent"],
            title=(f"Bioisostere · {result['n_improved']}/{result['n_analogs']} "
                   f"improved"))
        artifact_id = rec["id"]
    result["artifact_id"] = artifact_id
    return result


@router.get("/bioisostere/rules")
async def bioisostere_rules() -> dict[str, Any]:
    """The bioisostere rule library (for the studio's rule browser)."""
    return {"n_rules": len(_RULES), "rules": [
        {k: r[k] for k in ("id", "label", "axis", "rationale")} for r in _RULES]}


@router.get("/bioisostere/runs")
async def list_runs(session_id: Optional[str] = None) -> dict[str, Any]:
    return {"items": service_store.list_artifacts(kind=_ARTIFACT_KIND,
                                                  session_id=session_id)}
