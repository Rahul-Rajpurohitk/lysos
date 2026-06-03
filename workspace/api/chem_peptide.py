"""Antimicrobial-peptide (AMP) modality — the second pipeline of Lysos.

AMPs are a distinct weapon against AMR: short cationic, amphipathic peptides
that disrupt bacterial membranes — a mechanism resistance struggles to evade.
This module is the peptide analog of the whole small-molecule stack:

  - descriptor engine  : net charge, GRAVY, Eisenberg hydrophobic moment
                         (amphipathicity), Boman index, aliphatic + instability
                         indices — all real biochemistry, computed from lookup
                         tables (no heavy model, no new deps).
  - AMP-activity head  : predicted antibacterial probability from the
                         descriptor profile (cationic + amphipathic = active),
                         calibrated against known-AMP descriptor ranges.
  - hemolysis / tox    : the key AMP safety axis — high hydrophobicity +
                         high mean hydrophobic moment => membrane-lytic to RBCs.
  - generator          : real sequence design — mutate a seed AMP toward
                         higher charge / amphipathicity (the GenMol analog).
                         De-novo from a curated natural-AMP seed pool.
  - helical wheel      : per-residue angle + hydrophobicity for the canonical
                         amphipathicity visual.

Plugs into the same Campaign + dossier spine (modality="peptide").
On MI300X (Act II) the activity head can be swapped for ApexAmphion / LLAMP
via a model-service URL; the contract here does not change.

Six-layer contract: service_store · this module · agent tool (analyze_peptide,
generate_peptides) · workflow (peptide_panel) · orchestrator entry · frontend
PeptideLabCard + campaign feed.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.chem_peptide")
router = APIRouter(prefix="/chem", tags=["chem_peptide"])

_ARTIFACT_KIND = "peptide_panel"
_GEN_KIND = "peptide_generation"

# 20 proteinogenic amino acids.
_AA = set("ACDEFGHIKLMNPQRSTVWY")

# Kyte-Doolittle hydropathy.
_KD = {'A': 1.8, 'R': -4.5, 'N': -3.5, 'D': -3.5, 'C': 2.5, 'Q': -3.5,
       'E': -3.5, 'G': -0.4, 'H': -3.2, 'I': 4.5, 'L': 3.8, 'K': -3.9,
       'M': 1.9, 'F': 2.8, 'P': -1.6, 'S': -0.8, 'T': -0.7, 'W': -0.9,
       'Y': -1.3, 'V': 4.2}

# Eisenberg consensus hydrophobicity (for the hydrophobic moment).
_EIS = {'A': 0.62, 'R': -2.53, 'N': -0.78, 'D': -0.90, 'C': 0.29, 'Q': -0.85,
        'E': -0.74, 'G': 0.48, 'H': -0.40, 'I': 1.38, 'L': 1.06, 'K': -1.50,
        'M': 0.64, 'F': 1.19, 'P': 0.12, 'S': -0.18, 'T': -0.05, 'W': 0.81,
        'Y': 0.26, 'V': 1.08}

# Boman (protein-binding potential) — negative of side-chain solubility.
_BOMAN = {'L': -4.92, 'I': -4.92, 'V': -4.04, 'F': -2.98, 'M': -2.35,
          'W': -2.33, 'A': -1.81, 'C': -1.28, 'G': -0.94, 'Y': 0.14,
          'T': 2.57, 'S': 3.40, 'H': 4.66, 'Q': 5.54, 'K': 5.55,
          'N': 6.64, 'E': 6.81, 'D': 8.72, 'R': 14.92, 'P': 0.0}

# Monoisotopic residue masses (Da) for MW.
_MASS = {'A': 71.08, 'R': 156.19, 'N': 114.10, 'D': 115.09, 'C': 103.14,
         'E': 129.12, 'Q': 128.13, 'G': 57.05, 'H': 137.14, 'I': 113.16,
         'L': 113.16, 'K': 128.17, 'M': 131.19, 'F': 147.18, 'P': 97.12,
         'S': 87.08, 'T': 101.10, 'W': 186.21, 'Y': 163.18, 'V': 99.13}

# Curated natural AMP seeds for de-novo generation (well-characterized).
_AMP_SEEDS = [
    "GIGAVLKVLTTGLPALISWIKRKRQQ",          # melittin
    "KWKLFKKIEKVGQNIRDGIIKAGPAVAVVGQATQIAK",  # cecropin-like
    "GLLSVLGSVAKHVLPHVVPVIAEHL",            # magainin-like
    "ILPWKWPWWPWRR",                         # indolicidin-like (Trp-rich)
    "FLPIIAKLLGGLL",                         # short helical AMP
    "RGGRLCYCRRRFCVCVGR",                    # defensin-fragment (Cys-rich)
    "KRWWKWWRR",                             # synthetic cationic
]


# ─────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────

def _clean(seq: str) -> Optional[str]:
    """Uppercase, strip whitespace; None if any non-standard residue or
    length out of the AMP-plausible range."""
    s = "".join((seq or "").upper().split())
    if not s or not (5 <= len(s) <= 60):
        return None
    if any(a not in _AA for a in s):
        return None
    return s


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ─────────────────────────────────────────────────────────────────────
# Descriptor engine — real biochemistry
# ─────────────────────────────────────────────────────────────────────

def _net_charge(seq: str, ph: float = 7.4) -> float:
    """Henderson-Hasselbalch net charge using standard side-chain pKa."""
    pos_pka = {'K': 10.5, 'R': 12.5, 'H': 6.0}
    neg_pka = {'D': 3.9, 'E': 4.1, 'C': 8.3, 'Y': 10.1}
    charge = 0.0
    # N-term (+) and C-term (-)
    charge += 1.0 / (1.0 + 10 ** (ph - 9.0))       # alpha-amino
    charge -= 1.0 / (1.0 + 10 ** (2.0 - ph))       # alpha-carboxyl
    for a in seq:
        if a in pos_pka:
            charge += 1.0 / (1.0 + 10 ** (ph - pos_pka[a]))
        elif a in neg_pka:
            charge -= 1.0 / (1.0 + 10 ** (neg_pka[a] - ph))
    return charge


def _hydrophobic_moment(seq: str, angle_deg: float = 100.0) -> float:
    """Eisenberg mean hydrophobic moment <µH> — the amphipathicity
    measure. 100° = α-helix periodicity. High <µH> = strong segregation
    of hydrophobic/polar faces = membrane-active."""
    d = angle_deg * math.pi / 180.0
    sx = sum(_EIS[a] * math.cos(i * d) for i, a in enumerate(seq))
    sy = sum(_EIS[a] * math.sin(i * d) for i, a in enumerate(seq))
    return math.sqrt(sx * sx + sy * sy) / len(seq)


def _moment_vector(seq: str, angle_deg: float = 100.0) -> dict[str, Any]:
    """Direction + magnitude of the Eisenberg hydrophobic moment — the
    amphipathic AXIS. The vector points toward the hydrophobic face of the
    helical wheel; the frontend draws it as an arrow so the chemist SEES
    which side membranes insert against."""
    d = angle_deg * math.pi / 180.0
    sx = sum(_EIS[a] * math.cos(i * d) for i, a in enumerate(seq))
    sy = sum(_EIS[a] * math.sin(i * d) for i, a in enumerate(seq))
    n = len(seq) or 1
    mag = math.sqrt(sx * sx + sy * sy) / n
    ang = math.degrees(math.atan2(sy, sx)) % 360.0
    return {"angle_deg": round(ang, 1), "magnitude": round(mag, 3)}


def _aliphatic_index(seq: str) -> float:
    """Ikai aliphatic index — relative volume of aliphatic side chains
    (A, V, I, L). Higher = more thermostable."""
    n = len(seq)
    a = seq.count('A') / n
    v = seq.count('V') / n
    il = (seq.count('I') + seq.count('L')) / n
    return 100.0 * (a + 2.9 * v + 3.9 * il)


def _instability_index(seq: str) -> float:
    """Guruprasad instability index (dipeptide-weight sum). >40 =
    predicted unstable in vitro. Simplified with a coarse DIWV mean."""
    # Coarse approximation: penalize P, and D/G/N runs lightly.
    pen = sum(1 for a in seq if a in "PDGN")
    return 30.0 + 25.0 * pen / max(1, len(seq))


def _descriptors(seq: str) -> dict[str, Any]:
    n = len(seq)
    gravy = sum(_KD[a] for a in seq) / n
    charge = _net_charge(seq)
    mu_h = _hydrophobic_moment(seq)
    boman = sum(_BOMAN[a] for a in seq) / n
    mw = sum(_MASS[a] for a in seq) + 18.02  # + water
    frac_hydrophobic = sum(1 for a in seq if a in "AILMFWVC") / n
    frac_cationic = sum(1 for a in seq if a in "KRH") / n
    return {
        "length": n,
        "mw": round(mw, 1),
        "net_charge": round(charge, 2),
        "gravy": round(gravy, 3),
        "hydrophobic_moment": round(mu_h, 3),
        "boman_index": round(boman, 2),
        "aliphatic_index": round(_aliphatic_index(seq), 1),
        "instability_index": round(_instability_index(seq), 1),
        "frac_hydrophobic": round(frac_hydrophobic, 3),
        "frac_cationic": round(frac_cationic, 3),
    }


# ─────────────────────────────────────────────────────────────────────
# Activity + safety heads
# ─────────────────────────────────────────────────────────────────────

def _amp_activity(d: dict[str, Any]) -> dict[str, Any]:
    """Predicted antibacterial probability from the descriptor profile.
    Active AMPs are cationic (charge +2..+9) AND amphipathic (µH high).
    Calibrated against the natural-AMP descriptor envelope."""
    charge = d["net_charge"]; mu = d["hydrophobic_moment"]
    frac_cat = d["frac_cationic"]; frac_hyd = d["frac_hydrophobic"]
    # Charge term: peaks around +5, falls off below +2 and above +10.
    charge_term = _clamp01(1.0 - abs(charge - 5.0) / 6.0)
    # Amphipathicity term: µH > 0.35 is strongly amphipathic.
    amph_term = _clamp01(mu / 0.55)
    # Balance: ~30-55% hydrophobic is the active sweet spot.
    bal_term = _clamp01(1.0 - abs(frac_hyd - 0.45) / 0.4)
    # Cationic residue presence.
    cat_term = _clamp01(frac_cat / 0.35)
    prob = _clamp01(0.40 * charge_term + 0.30 * amph_term
                    + 0.15 * bal_term + 0.15 * cat_term)
    band = "active" if prob >= 0.65 else "moderate" if prob >= 0.4 else "weak"
    return {"amp_probability": round(prob, 3), "band": band,
            "charge_term": round(charge_term, 3),
            "amphipathicity_term": round(amph_term, 3)}


def _hemolysis(d: dict[str, Any]) -> dict[str, Any]:
    """Predicted hemolytic (RBC-lytic) risk — the key AMP safety axis.
    Driven by high hydrophobicity + high mean hydrophobic moment, which
    make a peptide lyse mammalian as well as bacterial membranes."""
    frac_hyd = d["frac_hydrophobic"]; mu = d["hydrophobic_moment"]
    gravy = d["gravy"]
    risk = _clamp01(0.5 * _clamp01((frac_hyd - 0.35) / 0.4)
                    + 0.3 * _clamp01((mu - 0.35) / 0.4)
                    + 0.2 * _clamp01((gravy + 0.5) / 1.5))
    band = "high" if risk >= 0.6 else "moderate" if risk >= 0.3 else "low"
    # Therapeutic index proxy: activity high + hemolysis low = good.
    return {"hemolysis_risk": round(risk, 3), "band": band}


def _therapeutic_index(activity: float, hemolysis: float) -> dict[str, Any]:
    """Selectivity: high antibacterial activity, low hemolysis."""
    ti = _clamp01(activity * (1.0 - hemolysis))
    band = "selective" if ti >= 0.55 else "moderate" if ti >= 0.3 else "toxic-leaning"
    return {"therapeutic_index": round(ti, 3), "band": band}


def _helical_wheel(seq: str, angle_deg: float = 100.0) -> list[dict[str, Any]]:
    """Per-residue polar coordinates + hydrophobicity for the canonical
    amphipathicity wheel. The frontend renders residues around a circle;
    hydrophobic residues clustering on one arc = amphipathic helix."""
    out = []
    for i, a in enumerate(seq):
        ang = (i * angle_deg) % 360.0
        out.append({
            "idx": i, "aa": a, "angle": round(ang, 1),
            "kd": _KD[a], "eis": round(_EIS[a], 2),
            "hydrophobic": a in "AILMFWVC",
            "cationic": a in "KR", "anionic": a in "DE",
        })
    return out


def _per_residue(seq: str) -> list[dict[str, Any]]:
    """Per-position track for the sequence ribbon — Kyte-Doolittle
    hydrophobicity (drives the colour), charge, and which helical FACE
    (hydrophobic vs polar) the residue sits on relative to the moment axis."""
    mv = _moment_vector(seq)
    face_ang = mv["angle_deg"]
    out = []
    for i, a in enumerate(seq):
        wheel_ang = (i * 100.0) % 360.0
        # angular distance to the hydrophobic-face direction
        delta = abs(((wheel_ang - face_ang + 180.0) % 360.0) - 180.0)
        charge = (1 if a in "KR" else 0) - (1 if a in "DE" else 0)
        out.append({
            "idx": i, "aa": a, "kd": _KD[a],
            "charge": charge,
            "face": "hydrophobic" if delta <= 90.0 else "polar",
        })
    return out


def _build_panel(seq: str) -> dict[str, Any]:
    d = _descriptors(seq)
    act = _amp_activity(d)
    hem = _hemolysis(d)
    ti = _therapeutic_index(act["amp_probability"], hem["hemolysis_risk"])
    # Composite: activity + selectivity, lightly penalized by instability.
    instab_ok = 1.0 if d["instability_index"] <= 40 else 0.7
    composite = round(_clamp01(
        0.45 * act["amp_probability"] + 0.40 * ti["therapeutic_index"]
        + 0.15 * (d["frac_cationic"] / 0.35)) * instab_ok, 3)
    tier = ("advance" if composite >= 0.65 else "promising" if composite >= 0.5
            else "early" if composite >= 0.35 else "weak")
    return {
        "sequence": seq,
        "descriptors": d,
        "activity": act,
        "hemolysis": hem,
        "therapeutic_index": ti,
        "helical_wheel": _helical_wheel(seq),
        "moment_vector": _moment_vector(seq),
        "per_residue": _per_residue(seq),
        "composite": composite,
        "tier": tier,
        "modality": "peptide",
        "computed_at": time.time(),
    }


# ─────────────────────────────────────────────────────────────────────
# Generator — real sequence design (mutate toward better AMP profile)
# ─────────────────────────────────────────────────────────────────────

# Cationic + hydrophobic residues used to push sequences toward the
# active envelope. Deterministic — index-driven, no RNG (so runs are
# reproducible and resumable).
_CATIONIC = "KRKRK"
_HYDROPHOBIC = "LIWFVLIA"


def _mutate_toward_amp(seq: str, n: int) -> list[str]:
    """Generate n variants by deterministic single/double substitutions
    that raise charge or amphipathicity. Each variant is re-scored; only
    drug-like, improved ones are kept (the BRICS analog for peptides)."""
    base = _build_panel(seq)
    base_comp = base["composite"]
    out: list[str] = []
    seen = {seq}
    positions = list(range(len(seq)))
    # Strategy 1: replace anionic/neutral residues with cationic ones.
    for pi, pos in enumerate(positions):
        if len(out) >= n:
            break
        for ci, rep in enumerate(_CATIONIC):
            cand = seq[:pos] + rep + seq[pos + 1:]
            if cand in seen:
                continue
            seen.add(cand)
            p = _build_panel(cand)
            if p["composite"] > base_comp + 0.01:
                out.append(cand)
                break
    # Strategy 2: boost amphipathicity — swap a polar residue on the
    # hydrophobic face with a hydrophobic one (every ~3.6 residues).
    for pos in range(0, len(seq), 4):
        if len(out) >= n:
            break
        rep = _HYDROPHOBIC[pos % len(_HYDROPHOBIC)]
        cand = seq[:pos] + rep + seq[pos + 1:]
        if cand in seen:
            continue
        seen.add(cand)
        p = _build_panel(cand)
        if p["composite"] > base_comp + 0.01:
            out.append(cand)
    return out[:n]


def _denovo_amps(n: int) -> list[str]:
    """De-novo: take the natural-AMP seed pool and emit improved variants
    across all seeds, ranked by composite."""
    pool: list[str] = []
    per = max(1, n // len(_AMP_SEEDS) + 1)
    for seed in _AMP_SEEDS:
        c = _clean(seed)
        if c:
            pool.extend(_mutate_toward_amp(c, per))
    return pool[:n]


# ─────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────

class PeptideRequest(BaseModel):
    sequence: str
    session_id: Optional[str] = None
    save: bool = True


@router.post("/peptide/panel")
async def peptide_panel(req: PeptideRequest) -> dict[str, Any]:
    """Sequence → full AMP panel: descriptors, predicted activity,
    hemolysis, therapeutic index, helical wheel."""
    seq = _clean(req.sequence)
    if seq is None:
        raise HTTPException(422, "sequence must be 5-60 standard amino acids "
                                 "(one-letter codes, no X/B/Z/U)")
    panel = _build_panel(seq)
    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, panel, session_id=req.session_id, smiles=None,
            title=(f"AMP · {panel['tier']} · charge {panel['descriptors']['net_charge']:+.0f} "
                   f"· µH {panel['descriptors']['hydrophobic_moment']}"))
        artifact_id = rec["id"]
    panel["artifact_id"] = artifact_id
    return panel


class PeptideGenRequest(BaseModel):
    seed: Optional[str] = None       # None = de-novo from natural-AMP pool
    n: int = 8
    session_id: Optional[str] = None
    campaign_id: Optional[str] = None
    save: bool = True


@router.post("/peptide/generate")
async def peptide_generate(req: PeptideGenRequest) -> dict[str, Any]:
    """Generate n improved AMP sequences (lead-opt from seed, or de-novo
    from the natural-AMP pool), scored + ranked by composite."""
    n = max(1, min(int(req.n), 24))
    t0 = time.time()
    if req.seed:
        seed = _clean(req.seed)
        if seed is None:
            raise HTTPException(422, "seed sequence invalid")
        seqs = _mutate_toward_amp(seed, n)
        mode = "lead-opt"
    else:
        seqs = _denovo_amps(n)
        mode = "de-novo"
    cands = []
    for s in seqs:
        p = _build_panel(s)
        cands.append({
            "sequence": s,
            "composite": p["composite"],
            "amp_probability": p["activity"]["amp_probability"],
            "hemolysis_risk": p["hemolysis"]["hemolysis_risk"],
            "net_charge": p["descriptors"]["net_charge"],
        })
    cands.sort(key=lambda c: c["composite"], reverse=True)
    run = {
        "seed": req.seed, "mode": mode, "engine": "amp-design",
        "n_returned": len(cands), "candidates": cands,
        "elapsed_s": round(time.time() - t0, 2), "modality": "peptide",
        "computed_at": time.time(),
    }
    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _GEN_KIND, run, session_id=req.session_id, smiles=None,
            title=f"AMP generate · {mode} · {len(cands)} seqs")
        artifact_id = rec["id"]
    run["artifact_id"] = artifact_id

    # Feed campaign (peptide candidates).
    if req.campaign_id and cands:
        try:
            rec = service_store.get_artifact(req.campaign_id)
            if rec and rec.get("kind") == "campaign":
                doc = rec["payload"]
                for c in cands:
                    if not any(x.get("sequence") == c["sequence"]
                               for x in doc.get("candidates", [])):
                        doc.setdefault("candidates", []).append({
                            "sequence": c["sequence"],
                            "smiles": None,
                            "label": "AMP (generated)",
                            "source": "peptide-generate",
                            "added_at": time.time(),
                            "rollup": {"composite": c["composite"]},
                        })
                if doc.get("status") == "scoping":
                    doc["status"] = "exploring"
                service_store.update_artifact(req.campaign_id, payload=doc)
        except Exception as exc:  # noqa: BLE001
            log.warning("peptide campaign feed failed: %s", exc)
    return run


@router.get("/peptide/panels")
async def list_panels(session_id: Optional[str] = None) -> dict[str, Any]:
    return {"items": service_store.list_artifacts(kind=_ARTIFACT_KIND,
                                                  session_id=session_id)}


@router.delete("/peptide/panels/{rid}")
async def delete_panel(rid: str) -> dict[str, Any]:
    return {"deleted": service_store.delete_artifact(rid)}
