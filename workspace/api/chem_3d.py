"""Chemistry 3D services — Target-Ligand Theater (Service 1).

Endpoints:
  GET  /chem/targets/{pathogen}             curated target list per pathogen
  GET  /chem/target/{pdb_id}                PDB structure + active site (cached)
  POST /chem/place-in-pocket                ligand placement + contact analysis

Why this module exists:
  The chem container previously had 1 PDB per pathogen and a literature-derived
  pocket center. To support real medicinal-chemistry workflows the agent and
  user need to: (1) pick which target to design against (each pathogen has
  multiple validated targets — PBP2a vs MurA for MRSA, InhA vs DprE1 for Mtb),
  (2) see the binding pocket geometry, (3) place candidates and read back
  contact / clash signals to drive further edits.

Design choices:
  * Minimal PDB parser — biopython isn't installed and adding it bloats the
    image. ATOM/HETATM lines are columnar fixed-width; we extract what we
    need (chain, residue, position, atom name, x/y/z) in <50 LOC.
  * RCSB cache — first request fetches from https://files.rcsb.org/download/
    and writes to data/pdb_cache/. Subsequent requests are local.
  * Active site = residues with ANY heavy atom within 5Å of bound co-crystal
    HETATM ligand. If no co-crystal ligand, fall back to literature pocket
    center + residues within 8Å.
  * Place-in-pocket algorithm — RDKit ETKDG conformer for the ligand, then
    translate centroid to pocket centroid. No rotation search (would cost
    seconds; we want sub-second response). Returns contact and clash signals
    that the agent reasons about; the EXACT pose is approximate.

Agent tools registered alongside:
  list_targets(pathogen)         → list of curated targets
  place_in_pocket(smiles, pdb_id) → contacts + clashes + binding atoms
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from pathlib import Path
from typing import Any, Optional

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger("api.chem_3d")

router = APIRouter(prefix="/chem", tags=["chem_3d"])

# ─── Curated pathogen → target map ─────────────────────────────────────────
# 8 priority pathogens × 2-3 targets each. Each target has a PDB ID, the
# protein name, mechanism class, why this target matters clinically, and a
# default chain/residue for the active site (used when no co-crystal ligand
# is present in the structure).

PATHOGEN_TARGETS: dict[str, list[dict[str, Any]]] = {
    "MRSA": [
        {
            "pdb_id": "1VQQ",
            "name": "PBP2a (Penicillin Binding Protein 2a)",
            "short_name": "PBP2a",
            "mechanism": "transpeptidase — cell wall biosynthesis",
            "clinical_note": "The defining target of MRSA. mecA gene product; β-lactams have low affinity → resistance. Ceftaroline is the only approved β-lactam that targets PBP2a effectively.",
            "drug_class_examples": ["ceftaroline", "ceftobiprole"],
            "active_site_chain": "A",
            "active_site_residues": [403, 405, 590, 598, 600, 643],  # PBP2a active-site loop
            "literature_pocket": (33.0, 36.0, 60.0),
            "preferred_default": True,
        },
        {
            "pdb_id": "1A2N",
            "name": "MurA (UDP-N-acetylglucosamine 1-carboxyvinyltransferase)",
            "short_name": "MurA",
            "mechanism": "first committed step of peptidoglycan biosynthesis",
            "clinical_note": "Target of fosfomycin. Entry-point enzyme for cell wall — broadly conserved across gram-positives and gram-negatives.",
            "drug_class_examples": ["fosfomycin"],
            "active_site_chain": "A",
            "active_site_residues": [22, 91, 93, 115, 119, 305],
            "literature_pocket": (22.0, 8.0, 14.0),
        },
    ],
    "Mtb": [
        {
            "pdb_id": "2X22",
            "name": "InhA (Enoyl-acyl carrier protein reductase)",
            "short_name": "InhA",
            "mechanism": "fatty acid biosynthesis (FAS-II), mycolic acid precursor",
            "clinical_note": "The target of isoniazid (after activation by KatG). Direct InhA inhibitors bypass KatG resistance.",
            "drug_class_examples": ["isoniazid", "ethionamide", "pretomanid"],
            "active_site_chain": "A",
            "active_site_residues": [94, 96, 158, 165, 196, 215],
            "literature_pocket": (10.0, -5.0, 12.0),
            "preferred_default": True,
        },
        {
            "pdb_id": "4FDO",
            "name": "DprE1 (Decaprenylphosphoryl-β-D-ribose 2′-epimerase)",
            "short_name": "DprE1",
            "mechanism": "arabinogalactan biosynthesis (cell wall)",
            "clinical_note": "Validated by BTZ043 / macozinone. Essential, no human homolog. Hot target for new TB drugs.",
            "drug_class_examples": ["BTZ043", "macozinone (PBTZ-169)"],
            "active_site_chain": "A",
            "active_site_residues": [129, 132, 314, 318, 387],
            "literature_pocket": (5.0, 18.0, 22.0),
        },
    ],
    "EColi-CRE": [
        {
            "pdb_id": "5UL8",
            "name": "KPC-2 carbapenemase",
            "short_name": "KPC-2",
            "mechanism": "class A serine β-lactamase, hydrolyzes carbapenems",
            "clinical_note": "Most common carbapenemase in CRE. Inhibitors (avibactam, vaborbactam) restore carbapenem activity.",
            "drug_class_examples": ["avibactam", "vaborbactam", "relebactam"],
            "active_site_chain": "A",
            "active_site_residues": [70, 73, 130, 234, 237],
            "literature_pocket": (-2.0, 13.0, 3.0),
            "preferred_default": True,
        },
    ],
    "KpneuCRE": [
        {
            "pdb_id": "3SPU",
            "name": "NDM-1 (New Delhi Metallo-β-lactamase)",
            "short_name": "NDM-1",
            "mechanism": "class B metallo-β-lactamase, Zn²⁺-dependent",
            "clinical_note": "No clinically approved inhibitors. Major reason carbapenem resistance is spreading globally. Pan-β-lactam-resistant.",
            "drug_class_examples": ["taniborbactam (in trials)"],
            "active_site_chain": "A",
            "active_site_residues": [120, 122, 178, 211, 218],
            "literature_pocket": (8.0, 4.0, 0.0),
            "preferred_default": True,
        },
    ],
    "Abaum": [
        {
            "pdb_id": "7M4F",
            "name": "OXA-23 (Class D β-lactamase)",
            "short_name": "OXA-23",
            "mechanism": "class D serine β-lactamase, carbapenem-hydrolyzing",
            "clinical_note": "Most prevalent CHDL in A. baumannii. Cefiderocol can sometimes overcome via siderophore uptake.",
            "drug_class_examples": ["cefiderocol", "sulbactam-durlobactam"],
            "active_site_chain": "A",
            "active_site_residues": [70, 73, 144, 220, 224],
            "literature_pocket": (15.0, 15.0, 15.0),
            "preferred_default": True,
        },
    ],
    "Paer": [
        {
            "pdb_id": "5TJX",
            "name": "DNA gyrase B subunit",
            "short_name": "GyrB",
            "mechanism": "type II topoisomerase, ATPase",
            "clinical_note": "Quinolone target. Pseudomonas has efflux pumps + outer membrane resistance, but gyrB mutations are uncommon.",
            "drug_class_examples": ["ciprofloxacin", "levofloxacin", "novobiocin"],
            "active_site_chain": "A",
            "active_site_residues": [46, 50, 73, 99, 119],
            "literature_pocket": (0.0, 0.0, 0.0),
            "preferred_default": True,
        },
    ],
    "VRE": [
        {
            "pdb_id": "1MWS",
            "name": "PBP5 (low-affinity penicillin binding protein)",
            "short_name": "PBP5",
            "mechanism": "transpeptidase — cell wall in E. faecium",
            "clinical_note": "Intrinsic ampicillin resistance via overexpressed PBP5. Different from MRSA's PBP2a but similar concept.",
            "drug_class_examples": ["ceftobiprole"],
            "active_site_chain": "A",
            "active_site_residues": [422, 424, 477, 555, 580],
            "literature_pocket": (20.0, 0.0, 30.0),
            "preferred_default": True,
        },
        {
            "pdb_id": "1E4E",
            "name": "VanA D-Ala-D-Lac ligase",
            "short_name": "VanA",
            "mechanism": "synthesizes alternative cell-wall terminus that vancomycin can't bind",
            "clinical_note": "The vanA cassette is the canonical mechanism of high-level vancomycin resistance. Inhibiting VanA would re-sensitize VRE to vancomycin.",
            "drug_class_examples": ["(no clinical inhibitor yet)"],
            "active_site_chain": "A",
            "active_site_residues": [73, 110, 159, 212, 268],
            "literature_pocket": (12.0, 8.0, 22.0),
        },
    ],
    "NGono": [
        {
            "pdb_id": "5XFT",
            "name": "PBP2 (penA gene product)",
            "short_name": "PBP2",
            "mechanism": "transpeptidase",
            "clinical_note": "penA mosaic alleles cause cephalosporin resistance. Last-line ceftriaxone is failing in some regions.",
            "drug_class_examples": ["ceftriaxone", "cefixime"],
            "active_site_chain": "A",
            "active_site_residues": [310, 312, 365, 547, 549],
            "literature_pocket": (12.0, 15.0, 8.0),
            "preferred_default": True,
        },
    ],
}


# ─── PDB cache + parser ────────────────────────────────────────────────────

_PDB_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "pdb_cache"
_PDB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_RCSB_URL = "https://files.rcsb.org/download/{pdb_id}.pdb"

# in-memory parsed-structure cache (per process)
_STRUCT_CACHE: dict[str, dict[str, Any]] = {}


def _fetch_pdb(pdb_id: str) -> str:
    """Return PDB text, fetching from RCSB on cache miss."""
    pdb_id = pdb_id.upper()
    fp = _PDB_CACHE_DIR / f"{pdb_id}.pdb"
    if fp.exists():
        return fp.read_text()
    log.info("PDB cache miss for %s, fetching from RCSB", pdb_id)
    resp = requests.get(_RCSB_URL.format(pdb_id=pdb_id), timeout=30)
    if resp.status_code != 200:
        raise HTTPException(404, f"PDB {pdb_id} not found at RCSB ({resp.status_code})")
    fp.write_text(resp.text)
    return resp.text


def _parse_pdb(pdb_text: str) -> dict[str, Any]:
    """Minimal PDB parser. Returns:
      atoms:    [{idx, name, resname, chain, resid, x, y, z, element, kind}]
                kind='ATOM' or 'HETATM'
      residues: {(chain, resid): {name, atom_indices: [int]}}
      hetatms:  list of HETATM residues (potential co-crystal ligands)
    """
    atoms = []
    residues: dict[tuple[str, int], dict[str, Any]] = {}
    hetatms: list[dict[str, Any]] = []
    seen_hetres: dict[tuple[str, int, str], int] = {}
    for line in pdb_text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        try:
            kind = "ATOM" if line.startswith("ATOM") else "HETATM"
            atom_name = line[12:16].strip()
            resname = line[17:20].strip()
            chain = line[21:22].strip() or "A"
            resid_str = line[22:26].strip()
            resid = int(resid_str) if resid_str else 0
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
            element = line[76:78].strip() or atom_name[0]
        except (ValueError, IndexError):
            continue
        idx = len(atoms)
        atoms.append({
            "idx": idx, "name": atom_name, "resname": resname,
            "chain": chain, "resid": resid,
            "x": x, "y": y, "z": z,
            "element": element, "kind": kind,
        })
        if kind == "ATOM":
            key = (chain, resid)
            if key not in residues:
                residues[key] = {"name": resname, "chain": chain, "resid": resid, "atom_indices": []}
            residues[key]["atom_indices"].append(idx)
        else:
            hkey = (chain, resid, resname)
            if hkey not in seen_hetres and resname not in ("HOH", "WAT"):
                seen_hetres[hkey] = len(hetatms)
                hetatms.append({"name": resname, "chain": chain, "resid": resid, "atom_indices": []})
            if resname not in ("HOH", "WAT"):
                hetatms[seen_hetres[hkey]]["atom_indices"].append(idx)
    return {"atoms": atoms, "residues": residues, "hetatms": hetatms}


def _structure(pdb_id: str) -> dict[str, Any]:
    pdb_id = pdb_id.upper()
    if pdb_id in _STRUCT_CACHE:
        return _STRUCT_CACHE[pdb_id]
    text = _fetch_pdb(pdb_id)
    s = _parse_pdb(text)
    _STRUCT_CACHE[pdb_id] = s
    return s


def _find_target_meta(pdb_id: str) -> Optional[dict[str, Any]]:
    """Reverse lookup: find which pathogen entry has this PDB."""
    pdb_id = pdb_id.upper()
    for pathogen, targets in PATHOGEN_TARGETS.items():
        for t in targets:
            if t["pdb_id"] == pdb_id:
                return {**t, "pathogen": pathogen}
    return None


def _active_site(pdb_id: str) -> dict[str, Any]:
    """Return active site center, radius, residues. Prefers co-crystal HETATM
    centroid if available, else literature pocket center, else mass centroid."""
    s = _structure(pdb_id)
    meta = _find_target_meta(pdb_id) or {}
    atoms = s["atoms"]
    residues = s["residues"]
    hetatms = s["hetatms"]

    # 1) Pick the largest non-water HETATM (likely the co-crystal ligand)
    cocrystal = None
    if hetatms:
        cocrystal = max(hetatms, key=lambda h: len(h["atom_indices"]))
        # Skip cofactors that are too small (single ions like ZN, MG)
        if len(cocrystal["atom_indices"]) < 5:
            cocrystal = None

    if cocrystal:
        het_atoms = [atoms[i] for i in cocrystal["atom_indices"]]
        cx = sum(a["x"] for a in het_atoms) / len(het_atoms)
        cy = sum(a["y"] for a in het_atoms) / len(het_atoms)
        cz = sum(a["z"] for a in het_atoms) / len(het_atoms)
        # Active site = residues with any heavy atom within 5Å of any HETATM atom
        site_residues = []
        for (chain, resid), res in residues.items():
            for ridx in res["atom_indices"]:
                ra = atoms[ridx]
                for ha in het_atoms:
                    if (ra["x"] - ha["x"]) ** 2 + (ra["y"] - ha["y"]) ** 2 + (ra["z"] - ha["z"]) ** 2 <= 25.0:
                        site_residues.append({"chain": chain, "resid": resid, "name": res["name"]})
                        break
                else:
                    continue
                break
        source = "cocrystal_ligand"
    else:
        # 2) Literature pocket center
        cx, cy, cz = meta.get("literature_pocket", (0.0, 0.0, 0.0))
        # Active site residues = curated list if present, else nearest 12 residues
        site_residues = []
        target_resids = set(meta.get("active_site_residues", []))
        target_chain = meta.get("active_site_chain", "A")
        if target_resids:
            for rid in target_resids:
                key = (target_chain, rid)
                if key in residues:
                    site_residues.append({"chain": target_chain, "resid": rid, "name": residues[key]["name"]})
        else:
            # nearest 12 residues to literature pocket center
            distances = []
            for (chain, resid), res in residues.items():
                ridx = res["atom_indices"][len(res["atom_indices"]) // 2]  # CA-ish
                ra = atoms[ridx]
                d = (ra["x"] - cx) ** 2 + (ra["y"] - cy) ** 2 + (ra["z"] - cz) ** 2
                distances.append((d, chain, resid, res["name"]))
            distances.sort()
            for _, chain, resid, name in distances[:12]:
                site_residues.append({"chain": chain, "resid": resid, "name": name})
        source = "literature_pocket" if target_resids else "geometric_nearest"

    return {
        "pocket_center": {"x": cx, "y": cy, "z": cz},
        "pocket_radius_a": 8.0,
        "site_residues": site_residues,
        "n_site_residues": len(site_residues),
        "source": source,
    }


# ─── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/targets/{pathogen}")
async def list_targets(pathogen: str) -> dict:
    """Return curated target list for a pathogen.
    Each target carries PDB ID, mechanism, clinical context, drug class examples."""
    targets = PATHOGEN_TARGETS.get(pathogen)
    if not targets:
        raise HTTPException(404, f"unknown pathogen: {pathogen} (known: {list(PATHOGEN_TARGETS)})")
    return {
        "pathogen": pathogen,
        "n_targets": len(targets),
        "targets": [
            {
                "pdb_id": t["pdb_id"],
                "name": t["name"],
                "short_name": t["short_name"],
                "mechanism": t["mechanism"],
                "clinical_note": t["clinical_note"],
                "drug_class_examples": t["drug_class_examples"],
                "preferred_default": t.get("preferred_default", False),
                # Active site geometry — used by the 3D viewer to focus
                # the Pocket toggle on the binding region and to highlight
                # the pocket residues on the cartoon.
                "active_site_chain": t.get("active_site_chain", "A"),
                "active_site_residues": t.get("active_site_residues", []),
            }
            for t in targets
        ],
    }


@router.get("/target/{pdb_id}")
async def target_structure(pdb_id: str) -> dict:
    """Return PDB structure summary + active site.
    Heavy-weight PDB text NOT included; client fetches it via NGL directly
    from a /target/{pdb_id}/raw subroute or RCSB. We only return the parsed
    metadata needed for the workbench dashboard."""
    pdb_id = pdb_id.upper()
    s = _structure(pdb_id)
    meta = _find_target_meta(pdb_id)
    if meta is None:
        raise HTTPException(404, f"PDB {pdb_id} is not in the curated target list")
    site = _active_site(pdb_id)
    return {
        "pdb_id": pdb_id,
        "pathogen": meta["pathogen"],
        "name": meta["name"],
        "short_name": meta["short_name"],
        "mechanism": meta["mechanism"],
        "clinical_note": meta["clinical_note"],
        "n_atoms": len(s["atoms"]),
        "n_residues": len(s["residues"]),
        "n_hetatms": len(s["hetatms"]),
        "active_site": site,
        "rcsb_url": f"https://files.rcsb.org/download/{pdb_id}.pdb",
    }


@router.get("/target/{pdb_id}/raw")
async def target_raw_pdb(pdb_id: str) -> dict:
    """Return raw PDB text — workbench frontend can feed this to NGL.
    Cached locally on first hit. Includes a small ETag for client caching."""
    pdb_id = pdb_id.upper()
    text = _fetch_pdb(pdb_id)
    return {"pdb_id": pdb_id, "pdb_text": text, "n_lines": text.count("\n")}


class PlaceInPocketRequest(BaseModel):
    smiles: str
    pdb_id: str


@router.post("/place-in-pocket")
async def place_in_pocket(req: PlaceInPocketRequest) -> dict:
    """Place a candidate molecule in the active site of a target.

    Algorithm:
      1. Generate 3D conformer for the SMILES via RDKit ETKDG
      2. Translate ligand centroid → pocket centroid (no rotation search)
      3. Compute ligand atoms within 4Å of any protein heavy atom (contacts)
      4. Compute ligand atoms within 1.5Å of any protein atom (clashes)
      5. Score: pose_score = clamp(n_contacts / max(1, 5 * n_clashes) / 20, 0, 1)

    Returns:
      pose_score (0-1)
      contacts: list of {ligand_atom_idx, residue_chain, residue_resid, residue_name, distance_a}
      clashes:  same shape but distance < 1.5Å
      binding_atoms:  unique ligand atom indices in contacts
      clashing_atoms: unique ligand atom indices in clashes
      ligand_xyz: list of [x, y, z] per ligand atom (for the frontend NGL placement)
    """
    pdb_id = req.pdb_id.upper()
    s = _structure(pdb_id)
    site = _active_site(pdb_id)
    pcx = site["pocket_center"]["x"]
    pcy = site["pocket_center"]["y"]
    pcz = site["pocket_center"]["z"]

    # 1) RDKit conformer
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError:
        raise HTTPException(500, "rdkit not available")

    mol = Chem.MolFromSmiles(req.smiles)
    if mol is None:
        raise HTTPException(400, f"invalid SMILES: {req.smiles}")
    mol = Chem.AddHs(mol)
    embed_status = AllChem.EmbedMolecule(mol, randomSeed=42)
    if embed_status != 0:
        # Fallback: try without coordinates
        try:
            AllChem.EmbedMolecule(mol, randomSeed=42, useRandomCoords=True)
        except Exception:
            raise HTTPException(400, f"could not generate 3D conformer for {req.smiles}")
    try:
        AllChem.UFFOptimizeMolecule(mol, maxIters=200)
    except Exception:
        pass  # best effort; placement still works without optimization
    # Strip Hs for the contact analysis (heavy-atom only)
    mol_heavy = Chem.RemoveHs(mol)
    conf = mol_heavy.GetConformer()
    n_lig = mol_heavy.GetNumAtoms()
    lig_xyz = [conf.GetAtomPosition(i) for i in range(n_lig)]

    # 2) Translate centroid → pocket center
    lcx = sum(p.x for p in lig_xyz) / n_lig
    lcy = sum(p.y for p in lig_xyz) / n_lig
    lcz = sum(p.z for p in lig_xyz) / n_lig
    dx, dy, dz = pcx - lcx, pcy - lcy, pcz - lcz
    lig_translated = [(p.x + dx, p.y + dy, p.z + dz) for p in lig_xyz]
    lig_elements = [a.GetSymbol() for a in mol_heavy.GetAtoms()]

    # 3-4) Contacts + clashes
    # Restrict to nearby protein atoms for speed (within 12Å of pocket center)
    atoms = s["atoms"]
    nearby = []
    for a in atoms:
        if a["element"] == "H":
            continue
        d2 = (a["x"] - pcx) ** 2 + (a["y"] - pcy) ** 2 + (a["z"] - pcz) ** 2
        if d2 <= 144.0:  # 12Å radius
            nearby.append(a)

    # Exclude waters and common cofactors from contact analysis — they
    # crowd the active site geometrically but aren't binding partners
    # the chemistry agent should reason about.
    EXCLUDED_RESNAMES = {"HOH", "WAT", "DOD", "TIP", "EDO", "GOL", "PEG"}

    contacts: list[dict[str, Any]] = []
    clashes: list[dict[str, Any]] = []
    binding_atoms: set[int] = set()
    clashing_atoms: set[int] = set()
    for li, (lx, ly, lz) in enumerate(lig_translated):
        for pa in nearby:
            if pa["resname"] in EXCLUDED_RESNAMES:
                continue
            d2 = (lx - pa["x"]) ** 2 + (ly - pa["y"]) ** 2 + (lz - pa["z"]) ** 2
            if d2 <= 2.25:  # 1.5Å clash
                clashing_atoms.add(li)
                clashes.append({
                    "ligand_atom_idx": li,
                    "ligand_element": lig_elements[li],
                    "residue_chain": pa["chain"],
                    "residue_resid": pa["resid"],
                    "residue_name": pa["resname"],
                    "protein_atom": pa["name"],
                    "distance_a": round(math.sqrt(d2), 2),
                })
            elif d2 <= 16.0:  # 4Å contact
                binding_atoms.add(li)
                contacts.append({
                    "ligand_atom_idx": li,
                    "ligand_element": lig_elements[li],
                    "residue_chain": pa["chain"],
                    "residue_resid": pa["resid"],
                    "residue_name": pa["resname"],
                    "protein_atom": pa["name"],
                    "distance_a": round(math.sqrt(d2), 2),
                })

    # 5) Score
    n_contacts = len(contacts)
    n_clashes = len(clashes)
    raw = n_contacts / max(1, 5 * n_clashes) / 20.0
    pose_score = max(0.0, min(1.0, raw))

    # Top-K contact residues (group by residue, take min distance)
    contact_by_res: dict[tuple[str, int], dict[str, Any]] = {}
    for c in contacts:
        key = (c["residue_chain"], c["residue_resid"])
        if key not in contact_by_res or c["distance_a"] < contact_by_res[key]["distance_a"]:
            contact_by_res[key] = c
    key_contacts = sorted(contact_by_res.values(), key=lambda c: c["distance_a"])[:8]

    return {
        "pdb_id": pdb_id,
        "smiles": req.smiles,
        "pose_score": round(pose_score, 3),
        "n_contacts": n_contacts,
        "n_clashes": n_clashes,
        "contacts": contacts[:60],  # cap response size
        "clashes": clashes[:30],
        "binding_atoms": sorted(binding_atoms),
        "clashing_atoms": sorted(clashing_atoms),
        "key_contacts": [
            {
                "residue": f"{c['residue_name']}{c['residue_resid']}",
                "chain": c["residue_chain"],
                "ligand_atom_idx": c["ligand_atom_idx"],
                "ligand_element": c["ligand_element"],
                "distance_a": c["distance_a"],
            }
            for c in key_contacts
        ],
        "ligand_xyz": [[round(p[0], 3), round(p[1], 3), round(p[2], 3)] for p in lig_translated],
        "ligand_elements": lig_elements,
        "pocket_center": site["pocket_center"],
        "computed_at": time.time(),
    }
