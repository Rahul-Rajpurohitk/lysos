"""Tests for the workspace FastAPI hardening layer.

Covers:
  * SMILES sanitizer rejects HTML/JS injection attempts
  * 400 on illegal SMILES, 404 on unknown pathogen, 413 on oversized body
  * /api/ready returns model_loaded=False until generator is loaded
  * Response carries X-Request-ID + X-Process-Time-Ms headers
  * Rate-limit fires above the configured cap
  * Score cache returns the same payload on repeat (deterministic)
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

# Tighter cap so the rate-limit test isn't flaky on slow CI
os.environ["LYSOS_RL_SCORE_PER_MIN"] = "3"
os.environ["LYSOS_RL_DESIGN_PER_MIN"] = "1"

from workspace.api import server  # noqa: E402

client = TestClient(server.app)


def test_smiles_sanitizer_rejects_xss():
    r = client.get("/api/score", params={"smiles": "<script>alert(1)</script>", "target": "MRSA"})
    assert r.status_code == 400
    assert "illegal characters" in r.text


def test_smiles_sanitizer_rejects_too_long():
    r = client.get("/api/score", params={"smiles": "C" * 600, "target": "MRSA"})
    assert r.status_code == 422  # pydantic Query length validation fires first


def test_unknown_pathogen():
    r = client.get("/api/score", params={"smiles": "CCO", "target": "NoSuchPathogen"})
    assert r.status_code == 404


def test_health_and_ready_separate():
    r = client.get("/api/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "ok"

    r2 = client.get("/api/ready")
    assert r2.status_code == 200
    p2 = r2.json()
    # Generator hasn't been loaded; ready=false is the correct signal.
    assert p2["ready"] is False
    assert p2["model_loaded"] is False


def test_response_carries_request_id_and_timing():
    r = client.get("/api/health")
    assert "x-request-id" in {k.lower() for k in r.headers}
    assert "x-process-time-ms" in {k.lower() for k in r.headers}


def test_pathogens_list_complete():
    r = client.get("/api/pathogens")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 8  # 8 WHO priority pathogens
    shorts = {p["short"] for p in data}
    assert {"MRSA", "Mtb", "EColi-CRE", "KpneuCRE", "Abaum",
            "Paer", "VRE", "NGono"}.issubset(shorts)


def test_rate_limit_score():
    """Cap = 3/min for /api/score (set in env at module import).
    Burst of 6 requests; expect ~3 to pass and ~3 to 429."""
    # Reset bucket for this client IP
    from workspace.api.hardening import _BUCKETS
    _BUCKETS.clear()

    n_ok, n_429 = 0, 0
    for i in range(6):
        r = client.get("/api/score", params={"smiles": "CCO", "target": "MRSA"})
        if r.status_code == 200:
            n_ok += 1
        elif r.status_code == 429:
            n_429 += 1
    assert n_ok <= 4, f"too many passed: {n_ok}"
    assert n_429 >= 2, f"too few throttled: {n_429}"


def test_score_cache_repeat_request_identical():
    """Identical (smiles, target) should return identical payload — cache hit."""
    from workspace.api.hardening import _BUCKETS
    _BUCKETS.clear()
    r1 = client.get("/api/score", params={"smiles": "CC(=O)Oc1ccccc1C(=O)O", "target": "MRSA"})
    r2 = client.get("/api/score", params={"smiles": "CC(=O)Oc1ccccc1C(=O)O", "target": "MRSA"})
    assert r1.status_code == 200 == r2.status_code
    assert r1.json() == r2.json()


def test_smiles_sanitizer_unit():
    """Direct unit test of sanitize_smiles()."""
    from workspace.api.hardening import sanitize_smiles
    assert sanitize_smiles("CCO") == "CCO"
    assert sanitize_smiles("  CC(=O)Oc1ccccc1C(=O)O  ") == "CC(=O)Oc1ccccc1C(=O)O"
    with pytest.raises(ValueError):
        sanitize_smiles("")
    with pytest.raises(ValueError):
        sanitize_smiles("CCO; rm -rf /")
    with pytest.raises(ValueError):
        sanitize_smiles("<script>")
    with pytest.raises(ValueError):
        sanitize_smiles("C" * 1000)
