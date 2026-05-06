"""SQLite-backed playground store — append-only event log + materialized
projections for sessions, molecules, atoms, bonds, edits, scores, agent
actions, jobs, layouts. WAL mode for concurrent reads.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Optional


DEFAULT_DB = Path.home() / ".lysos" / "playground.sqlite"


@dataclass
class Molecule:
    id: str
    session_id: str
    parent_id: Optional[str]
    smiles: str
    canonical_smiles: str
    formula: str
    mw: float
    logp: Optional[float]
    composite_score: float
    pareto_rank: int
    role: str
    created_at: float
    created_by: str


@dataclass
class Atom:
    molecule_id: str
    atom_idx: int
    element: str
    formal_charge: int
    n_hydrogens: int
    free_valence: int
    is_aromatic: bool
    in_ring: bool
    ring_size: int
    x: float
    y: float
    z: float


@dataclass
class Bond:
    molecule_id: str
    bond_idx: int
    atom_a_idx: int
    atom_b_idx: int
    bond_type: str
    in_ring: bool


@dataclass
class MoleculeEdit:
    id: str
    ts: float
    session_id: str
    parent_molecule_id: Optional[str]
    child_molecule_id: Optional[str]
    actor: str
    actor_kind: str
    op: str
    atom_idx: Optional[int]
    bond_idx: Optional[int]
    params: dict[str, Any]
    result_smiles: Optional[str]
    composite_before: Optional[float]
    composite_after: Optional[float]
    delta: Optional[float]
    client_op_id: Optional[str]


@dataclass
class ScoreSnapshot:
    id: str
    molecule_id: str
    ts: float
    composite: float
    components: dict[str, float]
    weakest: str
    strongest: str
    model_used: str


@dataclass
class AgentAction:
    id: str
    session_id: str
    ts: float
    agent_name: str
    action_type: str
    target_molecule_id: Optional[str]
    target_atom_idx: Optional[int]
    message_text: str
    confidence: float
    references: dict[str, Any]


@dataclass
class Job:
    id: str
    session_id: str
    kind: str
    status: str
    payload: dict[str, Any]
    result: dict[str, Any]
    error_text: str
    created_at: float
    started_at: Optional[float]
    finished_at: Optional[float]
    worker_id: str


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, user_id TEXT, target_pathogen TEXT,
    mode TEXT, autonomy TEXT, created_at REAL,
    terminated INTEGER DEFAULT 0, termination_reason TEXT
);

CREATE TABLE IF NOT EXISTS molecules (
    id TEXT PRIMARY KEY, session_id TEXT, parent_id TEXT,
    smiles TEXT NOT NULL, canonical_smiles TEXT, formula TEXT,
    mw REAL, logp REAL, composite_score REAL DEFAULT 0,
    pareto_rank INTEGER DEFAULT 0, role TEXT DEFAULT 'active',
    created_at REAL, created_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_molecules_session ON molecules(session_id);
CREATE INDEX IF NOT EXISTS idx_molecules_parent  ON molecules(parent_id);

CREATE TABLE IF NOT EXISTS atoms (
    molecule_id TEXT, atom_idx INTEGER,
    element TEXT, formal_charge INTEGER, n_hydrogens INTEGER, free_valence INTEGER,
    is_aromatic INTEGER, in_ring INTEGER, ring_size INTEGER,
    x REAL, y REAL, z REAL,
    PRIMARY KEY (molecule_id, atom_idx)
);

CREATE TABLE IF NOT EXISTS bonds (
    molecule_id TEXT, bond_idx INTEGER,
    atom_a_idx INTEGER, atom_b_idx INTEGER, bond_type TEXT, in_ring INTEGER,
    PRIMARY KEY (molecule_id, bond_idx)
);

CREATE TABLE IF NOT EXISTS molecule_edits (
    id TEXT PRIMARY KEY, ts REAL, session_id TEXT,
    parent_molecule_id TEXT, child_molecule_id TEXT,
    actor TEXT, actor_kind TEXT, op TEXT,
    atom_idx INTEGER, bond_idx INTEGER, params TEXT, result_smiles TEXT,
    composite_before REAL, composite_after REAL, delta REAL,
    client_op_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_edits_session ON molecule_edits(session_id, ts);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_edits_clientop
    ON molecule_edits(session_id, client_op_id) WHERE client_op_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS score_snapshots (
    id TEXT PRIMARY KEY, molecule_id TEXT, ts REAL,
    composite REAL, components TEXT, weakest TEXT, strongest TEXT, model_used TEXT
);
CREATE INDEX IF NOT EXISTS idx_scores_mol ON score_snapshots(molecule_id, ts);

CREATE TABLE IF NOT EXISTS agent_actions (
    id TEXT PRIMARY KEY, session_id TEXT, ts REAL,
    agent_name TEXT, action_type TEXT,
    target_molecule_id TEXT, target_atom_idx INTEGER,
    message_text TEXT, confidence REAL, references_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_actions_session ON agent_actions(session_id, ts);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, session_id TEXT, kind TEXT, status TEXT,
    payload TEXT, result TEXT, error_text TEXT,
    created_at REAL, started_at REAL, finished_at REAL, worker_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS playground_layouts (
    session_id TEXT, user_id TEXT,
    layout_json TEXT, viewport_json TEXT, updated_at REAL,
    PRIMARY KEY (session_id, user_id)
);
"""


class PlaygroundStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(os.environ.get("LYSOS_PLAYGROUND_DB", db_path or DEFAULT_DB))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- raw helpers ----
    def _q(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def _commit(self) -> None:
        with self._lock:
            self._conn.commit()

    # ---- sessions ----
    def create_session(self, sid: str, user_id: str, target_pathogen: str,
                       mode: str = "design", autonomy: str = "copilot") -> None:
        self._q(
            "INSERT OR IGNORE INTO sessions(id, user_id, target_pathogen, mode, autonomy, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (sid, user_id, target_pathogen, mode, autonomy, time.time()),
        )
        self._commit()

    # ---- molecules + atoms + bonds ----
    def upsert_molecule(self, mol: Molecule, atoms: Iterable[Atom],
                        bonds: Iterable[Bond]) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO molecules"
                "(id, session_id, parent_id, smiles, canonical_smiles, formula, mw, logp,"
                " composite_score, pareto_rank, role, created_at, created_by) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (mol.id, mol.session_id, mol.parent_id, mol.smiles, mol.canonical_smiles,
                 mol.formula, mol.mw, mol.logp, mol.composite_score, mol.pareto_rank,
                 mol.role, mol.created_at, mol.created_by),
            )
            cur.execute("DELETE FROM atoms WHERE molecule_id = ?", (mol.id,))
            cur.executemany(
                "INSERT INTO atoms(molecule_id, atom_idx, element, formal_charge, n_hydrogens,"
                " free_valence, is_aromatic, in_ring, ring_size, x, y, z) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(a.molecule_id, a.atom_idx, a.element, a.formal_charge, a.n_hydrogens,
                  a.free_valence, int(a.is_aromatic), int(a.in_ring), a.ring_size,
                  a.x, a.y, a.z) for a in atoms],
            )
            cur.execute("DELETE FROM bonds WHERE molecule_id = ?", (mol.id,))
            cur.executemany(
                "INSERT INTO bonds(molecule_id, bond_idx, atom_a_idx, atom_b_idx, bond_type, in_ring) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                [(b.molecule_id, b.bond_idx, b.atom_a_idx, b.atom_b_idx, b.bond_type,
                  int(b.in_ring)) for b in bonds],
            )
            self._conn.commit()

    def get_molecule(self, mid: str) -> Optional[dict[str, Any]]:
        row = self._q("SELECT * FROM molecules WHERE id = ?", (mid,)).fetchone()
        return dict(row) if row else None

    def get_atoms(self, mid: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q(
            "SELECT * FROM atoms WHERE molecule_id = ? ORDER BY atom_idx", (mid,)).fetchall()]

    def get_bonds(self, mid: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q(
            "SELECT * FROM bonds WHERE molecule_id = ? ORDER BY bond_idx", (mid,)).fetchall()]

    def list_session_molecules(self, sid: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q(
            "SELECT * FROM molecules WHERE session_id = ? ORDER BY created_at", (sid,)).fetchall()]

    # ---- edits ----
    def append_edit(self, e: MoleculeEdit) -> None:
        try:
            self._q(
                "INSERT INTO molecule_edits"
                "(id, ts, session_id, parent_molecule_id, child_molecule_id, actor, actor_kind, op,"
                " atom_idx, bond_idx, params, result_smiles, composite_before, composite_after, delta,"
                " client_op_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (e.id, e.ts, e.session_id, e.parent_molecule_id, e.child_molecule_id, e.actor,
                 e.actor_kind, e.op, e.atom_idx, e.bond_idx, json.dumps(e.params),
                 e.result_smiles, e.composite_before, e.composite_after, e.delta, e.client_op_id),
            )
            self._commit()
        except sqlite3.IntegrityError:
            pass

    def list_edits(self, sid: str, since_ts: float = 0.0, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self._q(
            "SELECT * FROM molecule_edits WHERE session_id = ? AND ts > ? ORDER BY ts LIMIT ?",
            (sid, since_ts, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["params"] = json.loads(d["params"]) if d.get("params") else {}
            except Exception:
                d["params"] = {}
            out.append(d)
        return out

    # ---- scores ----
    def append_score(self, s: ScoreSnapshot) -> None:
        self._q(
            "INSERT INTO score_snapshots"
            "(id, molecule_id, ts, composite, components, weakest, strongest, model_used) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (s.id, s.molecule_id, s.ts, s.composite, json.dumps(s.components),
             s.weakest, s.strongest, s.model_used),
        )
        self._q("UPDATE molecules SET composite_score = ? WHERE id = ?", (s.composite, s.molecule_id))
        self._commit()

    def latest_score(self, molecule_id: str) -> Optional[dict[str, Any]]:
        row = self._q(
            "SELECT * FROM score_snapshots WHERE molecule_id = ? ORDER BY ts DESC LIMIT 1",
            (molecule_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["components"] = json.loads(d["components"])
        except Exception:
            d["components"] = {}
        return d

    # ---- agent actions ----
    def append_action(self, a: AgentAction) -> None:
        self._q(
            "INSERT INTO agent_actions"
            "(id, session_id, ts, agent_name, action_type, target_molecule_id, target_atom_idx,"
            " message_text, confidence, references_json) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (a.id, a.session_id, a.ts, a.agent_name, a.action_type, a.target_molecule_id,
             a.target_atom_idx, a.message_text, a.confidence, json.dumps(a.references)),
        )
        self._commit()

    def list_actions(self, sid: str, since_ts: float = 0.0, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._q(
            "SELECT * FROM agent_actions WHERE session_id = ? AND ts > ? ORDER BY ts LIMIT ?",
            (sid, since_ts, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["references"] = json.loads(d.get("references_json") or "{}")
            except Exception:
                d["references"] = {}
            out.append(d)
        return out

    # ---- jobs ----
    def enqueue_job(self, j: Job) -> None:
        self._q(
            "INSERT INTO jobs"
            "(id, session_id, kind, status, payload, result, error_text, created_at,"
            " started_at, finished_at, worker_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (j.id, j.session_id, j.kind, j.status, json.dumps(j.payload), json.dumps(j.result),
             j.error_text, j.created_at, j.started_at, j.finished_at, j.worker_id),
        )
        self._commit()

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = []
        for k, v in fields.items():
            if k in ("payload", "result"):
                v = json.dumps(v)
            vals.append(v)
        vals.append(job_id)
        self._q(f"UPDATE jobs SET {cols} WHERE id = ?", tuple(vals))
        self._commit()

    def list_jobs(self, sid: str, status: Optional[str] = None) -> list[dict[str, Any]]:
        if status:
            rows = self._q(
                "SELECT * FROM jobs WHERE session_id = ? AND status = ? ORDER BY created_at DESC",
                (sid, status),
            ).fetchall()
        else:
            rows = self._q(
                "SELECT * FROM jobs WHERE session_id = ? ORDER BY created_at DESC", (sid,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("payload", "result"):
                try:
                    d[k] = json.loads(d.get(k) or "{}")
                except Exception:
                    d[k] = {}
            out.append(d)
        return out

    # ---- layouts ----
    def save_layout(self, sid: str, user_id: str, layout: dict, viewport: dict) -> None:
        self._q(
            "INSERT OR REPLACE INTO playground_layouts"
            "(session_id, user_id, layout_json, viewport_json, updated_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (sid, user_id, json.dumps(layout), json.dumps(viewport), time.time()),
        )
        self._commit()

    def get_layout(self, sid: str, user_id: str) -> Optional[dict[str, Any]]:
        row = self._q(
            "SELECT * FROM playground_layouts WHERE session_id = ? AND user_id = ?",
            (sid, user_id),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["layout"] = json.loads(d.get("layout_json") or "{}")
            d["viewport"] = json.loads(d.get("viewport_json") or "{}")
        except Exception:
            pass
        return d


# ---------------------------------------------------------------------------
# Materializer — SMILES → Molecule + Atom[] + Bond[] via RDKit
# ---------------------------------------------------------------------------

def materialize_from_smiles(smi: str, session_id: str, parent_id: Optional[str],
                            created_by: str = "user", role: str = "active",
                            mol_id: Optional[str] = None) -> tuple[Molecule, list[Atom], list[Bond]]:
    from rdkit import Chem
    from rdkit.Chem import AllChem, Descriptors, rdMolDescriptors

    raw = Chem.MolFromSmiles(smi)
    if raw is None:
        raise ValueError(f"unparseable SMILES: {smi}")
    Chem.SanitizeMol(raw)
    canon = Chem.MolToSmiles(raw, canonical=True)
    AllChem.Compute2DCoords(raw)
    formula = rdMolDescriptors.CalcMolFormula(raw)
    mw = Descriptors.MolWt(raw)
    try:
        logp = Descriptors.MolLogP(raw)
    except Exception:
        logp = None

    mid = mol_id or "mol_" + uuid.uuid4().hex[:12]
    mol = Molecule(
        id=mid, session_id=session_id, parent_id=parent_id,
        smiles=smi, canonical_smiles=canon, formula=formula, mw=mw, logp=logp,
        composite_score=0.0, pareto_rank=0, role=role,
        created_at=time.time(), created_by=created_by,
    )

    atoms: list[Atom] = []
    conf = raw.GetConformer()
    ring_info = raw.GetRingInfo()
    for a in raw.GetAtoms():
        idx = a.GetIdx()
        ring_size = 0
        for ring in ring_info.AtomRings():
            if idx in ring:
                ring_size = len(ring)
                break
        pos = conf.GetAtomPosition(idx)
        atoms.append(Atom(
            molecule_id=mid, atom_idx=idx,
            element=a.GetSymbol(),
            formal_charge=a.GetFormalCharge(),
            n_hydrogens=a.GetTotalNumHs(),
            free_valence=a.GetTotalNumHs(),
            is_aromatic=a.GetIsAromatic(),
            in_ring=a.IsInRing(),
            ring_size=ring_size,
            x=float(pos.x), y=float(pos.y), z=float(pos.z),
        ))

    bonds: list[Bond] = []
    for b in raw.GetBonds():
        bt = b.GetBondType()
        if bt == Chem.BondType.SINGLE:    bond_type = "single"
        elif bt == Chem.BondType.DOUBLE:  bond_type = "double"
        elif bt == Chem.BondType.TRIPLE:  bond_type = "triple"
        elif bt == Chem.BondType.AROMATIC: bond_type = "aromatic"
        else:                             bond_type = "other"
        bonds.append(Bond(
            molecule_id=mid, bond_idx=b.GetIdx(),
            atom_a_idx=b.GetBeginAtomIdx(),
            atom_b_idx=b.GetEndAtomIdx(),
            bond_type=bond_type,
            in_ring=b.IsInRing(),
        ))

    return mol, atoms, bonds


_STORE: Optional[PlaygroundStore] = None


def get_store() -> PlaygroundStore:
    global _STORE
    if _STORE is None:
        _STORE = PlaygroundStore()
    return _STORE
