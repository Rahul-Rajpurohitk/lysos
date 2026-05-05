"""Tests for the chemistry sandbox endpoints.

These verify the agent-driven molecular edit flow that the v3 frontend
exposes via drag-edit chips. If this surface breaks, the workbench's
"the agent actually does chemistry" feature dies — so it gets tests.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "workspace"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(WORKSPACE))

# Loosen the rate limit so tests can fire many requests
os.environ["LYSOS_RL_DEFAULT_PER_MIN"] = "1000"
os.environ["LYSOS_RL_SCORE_PER_MIN"] = "1000"

from workspace.api import server  # noqa: E402

client = TestClient(server.app)


def test_transforms_catalog():
    r = client.get("/workbench/sandbox/transforms")
    assert r.status_code == 200
    d = r.json()
    assert "groups" in d
    assert all(k in d["groups"] for k in ("add", "swap", "remove", "ring"))
    assert d["total"] >= 8

    # Each transform must have label + rationale
    for g, items in d["groups"].items():
        for item in items:
            assert "id" in item
            assert "label" in item
            assert "rationale" in item


def test_named_transform_pen_g_add_methyl():
    """Magic methyl on penG should slightly raise predicted_mic."""
    body = {
        "smiles": "CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O",
        "transform": "add_methyl",
        "target_pathogen": "MRSA",
        "score": True,
    }
    r = client.post("/workbench/sandbox/transform", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["candidate"] != d["parent"]
    assert d["candidate_props"]["valid"] is True
    # mw should go up by ~14 (methyl addition)
    assert d["candidate_props"]["mw"] > d["parent_props"]["mw"]
    # delta dict should have all reward components
    assert "delta" in d
    for k in ("validity", "predicted_mic", "drug_likeness_qed",
             "synthesizability", "hemolysis_safety"):
        assert k in d["delta"]


def test_swap_chloro_to_fluoro_preserves_aryl():
    """Cl→F on chlorobenzene should give Fc1ccccc1 (not bare F)."""
    body = {
        "smiles": "Clc1ccccc1",
        "transform": "swap_chloro_to_fluoro",
        "score": False,
    }
    r = client.post("/workbench/sandbox/transform", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert "F" in d["candidate"]
    assert "Cl" not in d["candidate"]
    assert "c1ccccc1" in d["candidate"] or "C1=CC=CC=C1" in d["candidate"]


def test_transform_no_match_returns_ok_false():
    """If SMARTS doesn't match anything, we return ok=false (not 500)."""
    body = {
        "smiles": "CC(=O)Oc1ccccc1C(=O)O",  # aspirin: no Cl
        "transform": "swap_chloro_to_fluoro",
        "score": False,
    }
    r = client.post("/workbench/sandbox/transform", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert "did not match" in d["reason"]


def test_transform_unknown_id():
    body = {"smiles": "CCO", "transform": "no_such_transform"}
    r = client.post("/workbench/sandbox/transform", json=body)
    assert r.status_code == 404


def test_transform_invalid_parent_smiles():
    body = {"smiles": "Q@@@@", "transform": "add_methyl"}
    r = client.post("/workbench/sandbox/transform", json=body)
    assert r.status_code == 422


def test_atom_edit_changes_element():
    body = {"smiles": "CCO", "atom_index": 0, "new_element": "N", "score": False}
    r = client.post("/workbench/sandbox/atom-edit", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["candidate"].startswith("N")  # NCO


def test_atom_edit_out_of_range():
    body = {"smiles": "CCO", "atom_index": 99, "new_element": "N"}
    r = client.post("/workbench/sandbox/atom-edit", json=body)
    assert r.status_code == 422


def test_python_sandbox_returns_stdout():
    body = {"code": "print(2+2)", "timeout_s": 3}
    r = client.post("/workbench/sandbox/python", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["returncode"] == 0
    assert d["stdout"].strip() == "4"


def test_python_sandbox_blocks_long_runs():
    body = {"code": "import time; time.sleep(10)", "timeout_s": 1}
    r = client.post("/workbench/sandbox/python", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["returncode"] == -1
    assert "timeout" in d["stderr"]


def test_resistance_graph_mrsa_has_meca():
    r = client.get("/workbench/sandbox/resistance-graph/MRSA")
    assert r.status_code == 200
    d = r.json()
    assert d["pathogen"] == "MRSA"
    assert d["n_nodes"] > 1
    labels = [n["label"] for n in d["nodes"]]
    assert any("mec" in lab.lower() for lab in labels), \
        f"mecA should appear in MRSA resistome; got {labels}"


def test_synth_route_aspirin_easy():
    r = client.get("/workbench/sandbox/synth/CC(=O)Oc1ccccc1C(=O)O")
    assert r.status_code == 200
    d = r.json()
    assert d["sa_score"] < 3.0  # aspirin is trivial
    assert d["confidence"] > 0.5
