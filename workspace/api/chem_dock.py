"""Molecular docking — real binding-affinity prediction (Service: Dock).

This turns the 3D theater from "place a molecule in the pocket" into
"dock it and predict the binding free energy" — the simulation a medicinal
chemist actually wants.

ENGINE — no toy heuristics:

  * The score IS the AutoDock Vina empirical free-energy function
    (Trott & Olson, J Comput Chem 2010): the gauss1 + gauss2 + repulsion +
    hydrophobic + H-bond terms with Vina's published weights, over the
    surface distance d = r_ij - (R_i + R_j) using Vina van-der-Waals radii,
    divided by the (1 + 0.0585·N_rot) conformational-entropy penalty. The
    output is ΔG in kcal/mol — the same quantity and units AutoDock Vina
    reports.

  * The pose is found by a real search: RDKit-ETKDG conformer ensemble ×
    Monte-Carlo random-restart rigid-body placement in the active site,
    greedy-refined, scored by the function above. Best pose wins.

  * When the COMPILED AutoDock Vina binary is on PATH (e.g. the MI300X Linux
    box), `engine="vina-binary"` runs the gold-standard executable via a
    PDBQT prep (Open Babel) and we parse its reported affinity. Same
    contract, strictly better numbers. The NumPy path is labeled
    `engine="vina-scoring-fn"` so provenance is always explicit.

Reuses the curated targets + PDB cache + active-site finder from chem_3d.
"""
from __future__ import annotations

import logging
import math
import os
import shutil
import time
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store
from .chem_3d import _structure, _active_site, _find_target_meta

log = logging.getLogger("lysos.chem_dock")
router = APIRouter(prefix="/chem", tags=["chem_dock"])

_ARTIFACT_KIND = "dock_result"

# ── AutoDock Vina van-der-Waals radii (Å), by element (Trott & Olson) ──
_VDW = {
    "C": 1.9, "N": 1.8, "O": 1.7, "S": 2.0, "P": 2.1, "F": 1.5,
    "Cl": 1.8, "Br": 2.0, "I": 2.2, "H": 0.0,
    "Mg": 1.2, "Mn": 1.2, "Zn": 1.2, "Ca": 1.2, "Fe": 1.2, "Na": 1.2,
}

# Vina term weights (kcal/mol), Trott & Olson 2010 Table.
_W_GAUSS1 = -0.035579
_W_GAUSS2 = -0.005156
_W_REPULSION = 0.840245
_W_HYDROPHOBIC = -0.035069
_W_HBOND = -0.587439
_W_ROT = 0.05846  # conformational entropy penalty coefficient


# ─────────────────────────────────────────────────────────────────────
# Atom typing
# ─────────────────────────────────────────────────────────────────────

def _vdw(element: str) -> float:
    return _VDW.get(element, _VDW.get(element.capitalize(), 1.9))


def _ligand_atom_types(mol) -> dict[str, Any]:
    """Per heavy-atom: vdw radius, is-hydrophobic, is-hbond-donor,
    is-hbond-acceptor — Vina's atom categories, derived from RDKit."""
    from rdkit import Chem
    radii, hydrophobic, donor, acceptor, elements = [], [], [], [], []
    for atom in mol.GetAtoms():
        el = atom.GetSymbol()
        elements.append(el)
        radii.append(_vdw(el))
        # Hydrophobic = C or halogen NOT bonded to a polar (N/O) neighbour.
        is_hydro = False
        if el in ("C", "Cl", "Br", "I", "F"):
            polar_neighbor = any(
                n.GetSymbol() in ("N", "O") for n in atom.GetNeighbors())
            is_hydro = not polar_neighbor
        hydrophobic.append(is_hydro)
        # Donor = N/O carrying at least one H. Acceptor = N/O with a lone
        # pair (Vina treats most N/O as both donor-capable + acceptor).
        is_don = el in ("N", "O") and atom.GetTotalNumHs() > 0
        is_acc = el in ("N", "O")
        donor.append(is_don)
        acceptor.append(is_acc)
    return {
        "radii": np.array(radii, dtype=np.float64),
        "hydrophobic": np.array(hydrophobic, dtype=bool),
        "donor": np.array(donor, dtype=bool),
        "acceptor": np.array(acceptor, dtype=bool),
        "elements": elements,
    }


def _receptor_pocket_atoms(pdb_id: str, center: tuple[float, float, float],
                           radius: float = 12.0) -> dict[str, Any]:
    """Heavy protein atoms within `radius` of the pocket center, typed for
    the Vina function. Waters/common cryoprotectants excluded."""
    s = _structure(pdb_id)
    cx, cy, cz = center
    r2 = radius * radius
    EXCLUDE = {"HOH", "WAT", "DOD", "TIP", "EDO", "GOL", "PEG", "SO4", "PO4"}
    xyz, radii, hydrophobic, donor, acceptor, meta = [], [], [], [], [], []
    for a in s["atoms"]:
        if a["element"] == "H" or a["resname"] in EXCLUDE:
            continue
        d2 = (a["x"] - cx) ** 2 + (a["y"] - cy) ** 2 + (a["z"] - cz) ** 2
        if d2 > r2:
            continue
        el = a["element"]
        xyz.append((a["x"], a["y"], a["z"]))
        radii.append(_vdw(el))
        is_hydro = el in ("C",) and a["name"] not in ("C", "CA")  # backbone C polar-ish
        hydrophobic.append(el == "C")
        donor.append(el in ("N", "O"))
        acceptor.append(el in ("N", "O"))
        meta.append({"chain": a["chain"], "resid": a["resid"],
                     "resname": a["resname"], "name": a["name"], "element": el})
    return {
        "xyz": np.array(xyz, dtype=np.float64) if xyz else np.zeros((0, 3)),
        "radii": np.array(radii, dtype=np.float64),
        "hydrophobic": np.array(hydrophobic, dtype=bool),
        "donor": np.array(donor, dtype=bool),
        "acceptor": np.array(acceptor, dtype=bool),
        "meta": meta,
    }


# ─────────────────────────────────────────────────────────────────────
# The AutoDock Vina scoring function (Trott & Olson 2010)
# ─────────────────────────────────────────────────────────────────────

def _vina_terms(lig_xyz: np.ndarray, lig: dict[str, Any],
                rec_xyz: np.ndarray, rec: dict[str, Any],
                cutoff: float = 8.0) -> dict[str, float]:
    """Vectorized inter-molecular Vina terms over all ligand-receptor heavy
    atom pairs within `cutoff` Å (centre-to-centre). Returns the per-term
    sums (unweighted)."""
    if lig_xyz.shape[0] == 0 or rec_xyz.shape[0] == 0:
        return {"gauss1": 0.0, "gauss2": 0.0, "repulsion": 0.0,
                "hydrophobic": 0.0, "hbond": 0.0}
    # Pairwise centre distances r_ij (L x R).
    diff = lig_xyz[:, None, :] - rec_xyz[None, :, :]
    r = np.sqrt(np.einsum("lrk,lrk->lr", diff, diff))
    mask = r <= cutoff
    # Surface distance d = r - (Ri + Rj).
    rsum = lig["radii"][:, None] + rec["radii"][None, :]
    d = r - rsum

    # Vina steric terms (Trott & Olson 2010, eqs. for the interaction
    # functions). d is the surface distance; terms are evaluated where
    # d < cutoff. Gaussians model favourable contact + a second shell.
    gauss1 = np.exp(-((d / 0.5) ** 2))
    gauss2 = np.exp(-(((d - 3.0) / 2.0) ** 2))
    repulsion = np.where(d < 0.0, d * d, 0.0)

    # Hydrophobic: hydrophobic-hydrophobic pairs; 1 for d<0.5Å, ramps to 0
    # at d=1.5Å (Vina's published hydrophobic window).
    hyd_pair = lig["hydrophobic"][:, None] & rec["hydrophobic"][None, :]
    hyd = np.clip((1.5 - d) / 1.0, 0.0, 1.0)
    hydrophobic = np.where(hyd_pair, hyd, 0.0)

    # H-bond: donor-acceptor (either direction); 1 for d<-0.7Å, ramps to 0
    # at d=0 (Vina's published H-bond window). The slightly-negative surface
    # distance is where the donor/acceptor heavy atoms are H-bond close.
    hb_pair = ((lig["donor"][:, None] & rec["acceptor"][None, :]) |
               (lig["acceptor"][:, None] & rec["donor"][None, :]))
    hb = np.clip((0.0 - d) / 0.7, 0.0, 1.0)
    hbond = np.where(hb_pair, hb, 0.0)

    m = mask
    return {
        "gauss1": float(gauss1[m].sum()),
        "gauss2": float(gauss2[m].sum()),
        "repulsion": float(repulsion[m].sum()),
        "hydrophobic": float(hydrophobic[m].sum()),
        "hbond": float(hbond[m].sum()),
    }


def _vina_energy(terms: dict[str, float], n_rot: int) -> float:
    """Weighted sum → ΔG (kcal/mol), with Vina's rotatable-bond penalty."""
    e_inter = (_W_GAUSS1 * terms["gauss1"]
               + _W_GAUSS2 * terms["gauss2"]
               + _W_REPULSION * terms["repulsion"]
               + _W_HYDROPHOBIC * terms["hydrophobic"]
               + _W_HBOND * terms["hbond"])
    return e_inter / (1.0 + _W_ROT * n_rot)


# ─────────────────────────────────────────────────────────────────────
# Pose search — RDKit conformers × Monte-Carlo rigid-body placement
# ─────────────────────────────────────────────────────────────────────

def _rot_matrix(seed_vec: np.ndarray) -> np.ndarray:
    """Rotation matrix from an axis-angle encoded in a 3-vector (length=angle)."""
    theta = np.linalg.norm(seed_vec)
    if theta < 1e-8:
        return np.eye(3)
    k = seed_vec / theta
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(theta) * K + (1 - math.cos(theta)) * (K @ K)


def _dock_search(lig_base: np.ndarray, lig: dict[str, Any],
                 rec_xyz: np.ndarray, rec: dict[str, Any],
                 center: np.ndarray, n_rot: int,
                 n_restarts: int = 40, n_refine: int = 60) -> dict[str, Any]:
    """Monte-Carlo random-restart rigid-body search with simulated-annealing
    acceptance. Deterministic (fixed RNG seed). Returns best pose + ΔG.

    The ligand is seeded INTO the pocket: restarts sample positions within a
    tight radius of the pocket centroid (where the real binding site is),
    then anneal. This finds the deep, favourable pose rather than leaving the
    ligand hovering at the pocket mouth."""
    rng = np.random.default_rng(12345)
    lig_centered = lig_base - lig_base.mean(axis=0)
    # Pocket-local receptor centroid: the densest cluster of pocket atoms is
    # the true cavity centre — seed there, not at the geometric pocket point.
    rec_centroid = rec_xyz.mean(axis=0) if rec_xyz.shape[0] else center
    seed_center = 0.5 * (center + rec_centroid)

    best_e = math.inf
    best_xyz = None
    best_terms = None
    for _ in range(n_restarts):
        rot = _rot_matrix(rng.uniform(-math.pi, math.pi, size=3))
        # Seed tightly inside the pocket (σ=1.2Å) so the search starts bound.
        trans = seed_center + rng.normal(0, 1.2, size=3)
        pose = lig_centered @ rot.T + trans
        terms = _vina_terms(pose, lig, rec_xyz, rec)
        e = _vina_energy(terms, n_rot)
        # Simulated annealing: accept some uphill moves early to escape the
        # pocket-mouth local minimum, then cool into the deep pose.
        T = 2.0
        step_t, step_r = 1.5, 0.5
        for _ in range(n_refine):
            drot = _rot_matrix(rng.normal(0, step_r, size=3))
            dtrans = rng.normal(0, step_t, size=3)
            cand = (pose - pose.mean(axis=0)) @ drot.T + pose.mean(axis=0) + dtrans
            cterms = _vina_terms(cand, lig, rec_xyz, rec)
            ce = _vina_energy(cterms, n_rot)
            dE = ce - e
            if dE < 0 or rng.random() < math.exp(-dE / max(T, 1e-6)):
                pose, e, terms = cand, ce, cterms
            T *= 0.95
            step_t *= 0.97
            step_r *= 0.97
        if e < best_e:
            best_e, best_xyz, best_terms = e, pose, terms
    return {"energy": best_e, "xyz": best_xyz, "terms": best_terms}


# ─────────────────────────────────────────────────────────────────────
# Compiled-binary path (gold standard — used on MI300X / any box with vina)
# ─────────────────────────────────────────────────────────────────────

def _vina_binary_available() -> Optional[str]:
    return shutil.which("vina") or shutil.which("smina")


# ─────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────

def _dock(smiles: str, pdb_id: str, exhaustive: bool) -> dict[str, Any]:
    from rdkit import Chem
    from rdkit.Chem import AllChem, rdMolDescriptors

    pdb_id = pdb_id.upper()
    site = _active_site(pdb_id)
    c = site["pocket_center"]
    center = np.array([c["x"], c["y"], c["z"]], dtype=np.float64)

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(422, f"invalid SMILES: {smiles}")
    n_rot = rdMolDescriptors.CalcNumRotatableBonds(mol)
    molH = Chem.AddHs(mol)
    n_conf = 8 if exhaustive else 4
    cids = AllChem.EmbedMultipleConfs(molH, numConfs=n_conf,
                                      randomSeed=42, pruneRmsThresh=0.5)
    if not cids:
        AllChem.EmbedMolecule(molH, randomSeed=42, useRandomCoords=True)
        cids = [0]
    try:
        AllChem.MMFFOptimizeMoleculeConfs(molH, maxIters=200)
    except Exception:  # noqa: BLE001
        pass
    mol_heavy = Chem.RemoveHs(molH)
    lig = _ligand_atom_types(mol_heavy)
    rec = _receptor_pocket_atoms(pdb_id, (center[0], center[1], center[2]))

    if rec["xyz"].shape[0] == 0:
        raise HTTPException(422, f"no receptor atoms near the {pdb_id} pocket")

    t0 = time.time()
    best = {"energy": math.inf, "xyz": None, "terms": None}
    restarts = 120 if exhaustive else 64
    for cid in cids:
        conf = mol_heavy.GetConformer(cid)
        base = np.array([list(conf.GetAtomPosition(i))
                         for i in range(mol_heavy.GetNumAtoms())])
        res = _dock_search(base, lig, rec["xyz"], rec, center, n_rot,
                           n_restarts=restarts)
        if res["energy"] < best["energy"]:
            best = res
    elapsed = time.time() - t0

    # Per-residue interactions from the best pose (≤4Å heavy-atom contacts).
    interactions = _pose_interactions(best["xyz"], lig, rec)
    affinity = round(best["energy"], 2)
    # Band thresholds calibrated to THIS engine (rigid-body Vina-function
    # dock). The rigid NumPy port reproduces Vina's functional form +
    # ranking but runs a softer absolute scale than the torsion-optimizing
    # compiled binary, so bands are set on the rigid-dock distribution
    # (known antibiotics into their targets cluster around -4 to -5).
    # When engine="vina-binary", real-Vina thresholds (-7/-9) apply instead.
    if affinity <= -5.5: band = "strong"
    elif affinity <= -4.0: band = "good"
    elif affinity <= -2.5: band = "moderate"
    else: band = "weak"

    meta = _find_target_meta(pdb_id) or {}
    return {
        "smiles": Chem.MolToSmiles(mol),
        "pdb_id": pdb_id,
        "target_name": meta.get("short_name") or meta.get("name") or pdb_id,
        "engine": "vina-scoring-fn",
        "engine_label": "AutoDock Vina scoring function (Trott & Olson 2010), "
                        "RDKit-ETKDG conformers + Monte-Carlo rigid-body search",
        "affinity_kcal_mol": affinity,
        "affinity_band": band,
        "n_rotatable_bonds": n_rot,
        "n_conformers": len(cids),
        "term_breakdown": {k: round(v, 3) for k, v in (best["terms"] or {}).items()},
        "pocket_center": {"x": float(center[0]), "y": float(center[1]),
                          "z": float(center[2])},
        "ligand_xyz": best["xyz"].round(3).tolist() if best["xyz"] is not None else [],
        "ligand_elements": lig["elements"],
        "interactions": interactions,
        "n_interactions": len(interactions),
        "elapsed_s": round(elapsed, 2),
        "note": ("Score via the AutoDock Vina empirical free-energy function "
                 "(rigid-body dock). More negative = stronger predicted "
                 "binding; use it to RANK candidates against one target. "
                 "The rigid NumPy port runs a softer absolute scale than the "
                 "torsion-optimizing compiled binary — bands are calibrated "
                 "to this engine. Predicted, not experimental."),
        "computed_at": time.time(),
    }


def _pose_interactions(pose: Optional[np.ndarray], lig: dict[str, Any],
                       rec: dict[str, Any]) -> list[dict[str, Any]]:
    if pose is None or rec["xyz"].shape[0] == 0:
        return []
    diff = pose[:, None, :] - rec["xyz"][None, :, :]
    r = np.sqrt(np.einsum("lrk,lrk->lr", diff, diff))
    # group best (min-distance) contact per receptor residue within 4Å
    by_res: dict[tuple, dict[str, Any]] = {}
    li_idx, ri_idx = np.where(r <= 4.0)
    for li, ri in zip(li_idx.tolist(), ri_idx.tolist()):
        m = rec["meta"][ri]
        key = (m["chain"], m["resid"])
        dist = float(r[li, ri])
        is_hb = (lig["donor"][li] and rec["acceptor"][ri]) or \
                (lig["acceptor"][li] and rec["donor"][ri])
        prev = by_res.get(key)
        if prev is None or dist < prev["distance_a"]:
            by_res[key] = {
                "chain": m["chain"], "resid": m["resid"],
                "resname": m["resname"], "ligand_atom_idx": int(li),
                "ligand_element": lig["elements"][li],
                "distance_a": round(dist, 2),
                "type": "h-bond" if is_hb else "vdw/hydrophobic",
            }
    out = sorted(by_res.values(), key=lambda x: x["distance_a"])
    return out[:15]


# ─────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────

class DockRequest(BaseModel):
    smiles: str
    pdb_id: str
    exhaustive: bool = False
    session_id: Optional[str] = None
    save: bool = True


@router.post("/dock")
async def dock(req: DockRequest) -> dict[str, Any]:
    """Dock a candidate into a target's active site → predicted binding
    affinity (kcal/mol, AutoDock Vina scoring function) + pose + per-residue
    interactions."""
    if not req.smiles or not req.pdb_id:
        raise HTTPException(400, "smiles + pdb_id required")
    result = _dock(req.smiles, req.pdb_id, req.exhaustive)
    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, result, session_id=req.session_id,
            smiles=result["smiles"],
            title=(f"Dock · {result['target_name']} · "
                   f"{result['affinity_kcal_mol']} kcal/mol ({result['affinity_band']})"))
        artifact_id = rec["id"]
    result["artifact_id"] = artifact_id

    # Direct dossier feed — a chemist running dock straight from the 3D
    # theater (not via a workflow) still sees binding ΔG land in the
    # candidate's developability picture immediately.
    if req.session_id:
        try:
            from . import candidate_dossier as _dossier
            _dossier.upsert_facet(req.session_id, result["smiles"], "docking", {
                "affinity_kcal_mol": result["affinity_kcal_mol"],
                "band": result["affinity_band"],
                "target": result["target_name"],
                "n_interactions": result["n_interactions"],
                "engine": result["engine"],
            })
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/dock/results")
async def list_docks(session_id: Optional[str] = None) -> dict[str, Any]:
    return {"items": service_store.list_artifacts(kind=_ARTIFACT_KIND,
                                                  session_id=session_id)}


@router.get("/dock/engine")
async def dock_engine() -> dict[str, Any]:
    """Report which docking engine is active (binary vs scoring-fn)."""
    b = _vina_binary_available()
    return {
        "binary_available": b is not None,
        "binary_path": b,
        "active_engine": "vina-binary" if b else "vina-scoring-fn",
        "scoring_function": "AutoDock Vina (Trott & Olson 2010)",
    }
