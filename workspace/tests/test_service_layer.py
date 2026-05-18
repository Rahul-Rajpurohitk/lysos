"""Integration + unit tests for the productized service layer.

Covers Service 1 (Synthesis Make-Route) end to end, PLUS the
cross-layer integration invariants the recent system changes must
hold. These are the "in and out" checks — they catch the exact class
of bug this project kept hitting: a thing wired into one layer
(an agent tool, an orchestrator route, a workflow) but not the others.

Sections:
  A. service_store      — shared artifact CRUD round-trips
  B. chem_synthesis     — route assembly, cost model, RDKit validation
  C. HTTP surface       — /chem/synthesis plan + CRUD via TestClient
  D. cross-layer wiring — agent tools ↔ dispatch ↔ workflows ↔ orchestrator
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
from pathlib import Path

# Isolate the service-store SQLite to a throwaway temp file BEFORE any
# import can open it — keeps the test run off the real ~/.lysos DB.
os.environ["LYSOS_SERVICES_DB"] = tempfile.mktemp(suffix="_svc_test.sqlite")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workspace"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from workspace.api import service_store  # noqa: E402
from workspace.api import chem_synthesis  # noqa: E402
from workspace.api import agent as agent_mod  # noqa: E402
from workspace.api import orchestrator as orch_mod  # noqa: E402
from workspace.api import workflows as wf_mod  # noqa: E402
from workspace.api import server  # noqa: E402

client = TestClient(server.app)


# ─────────────────────────────────────────────────────────────────────
# A. service_store — shared artifact CRUD
# ─────────────────────────────────────────────────────────────────────

def test_service_store_save_and_get():
    rec = service_store.save_artifact(
        "unit_kind", {"x": 1, "label": "hello"},
        session_id="sessA", smiles="CCO", title="t1",
    )
    assert rec["id"]
    assert rec["kind"] == "unit_kind"
    assert rec["payload"] == {"x": 1, "label": "hello"}
    got = service_store.get_artifact(rec["id"])
    assert got is not None
    assert got["payload"]["x"] == 1
    assert got["session_id"] == "sessA"
    assert got["smiles"] == "CCO"


def test_service_store_list_filters():
    service_store.save_artifact("kindX", {"n": 1}, session_id="sFilter")
    service_store.save_artifact("kindX", {"n": 2}, session_id="sFilter")
    service_store.save_artifact("kindY", {"n": 3}, session_id="sFilter")
    only_x = service_store.list_artifacts(kind="kindX", session_id="sFilter")
    assert len(only_x) == 2
    assert all(a["kind"] == "kindX" for a in only_x)
    # Newest-first ordering.
    assert only_x[0]["updated_at"] >= only_x[1]["updated_at"]


def test_service_store_update_preserves_created_at():
    rec = service_store.save_artifact("kindU", {"v": "before"})
    created = rec["created_at"]
    upd = service_store.update_artifact(rec["id"], {"v": "after"})
    assert upd is not None
    assert upd["payload"]["v"] == "after"
    assert upd["created_at"] == created          # created_at frozen
    assert upd["updated_at"] >= created          # updated_at advances


def test_service_store_delete():
    rec = service_store.save_artifact("kindD", {"k": 1})
    assert service_store.delete_artifact(rec["id"]) is True
    assert service_store.get_artifact(rec["id"]) is None
    assert service_store.delete_artifact(rec["id"]) is False   # idempotent


def test_service_store_update_missing_returns_none():
    assert service_store.update_artifact("does-not-exist", {"a": 1}) is None


# ─────────────────────────────────────────────────────────────────────
# B. chem_synthesis — route assembly + cost model + RDKit validation
# ─────────────────────────────────────────────────────────────────────

def test_canonical_smiles():
    assert chem_synthesis._canonical("CCO") is not None
    assert chem_synthesis._canonical("c1ccccc1") is not None
    assert chem_synthesis._canonical("not-a-smiles-!!!") is None
    assert chem_synthesis._canonical("") is None


def test_assemble_route_valid_steps():
    target = "CC(=O)Nc1ccc(O)cc1"
    raw = {
        "steps": [
            {"name": "Nitration", "reaction_class": "EAS",
             "reagents": ["HNO3"], "conditions": "0C",
             "product_smiles": "O=[N+]([O-])c1ccc(O)cc1",
             "rationale": "install nitro"},
            {"name": "Reduction", "reaction_class": "reduction",
             "reagents": ["H2", "Pd/C"], "conditions": "rt",
             "product_smiles": "Nc1ccc(O)cc1", "rationale": "to aniline"},
            {"name": "Acetylation", "reaction_class": "acylation",
             "reagents": ["Ac2O"], "conditions": "rt",
             "product_smiles": target, "rationale": "cap the amine"},
        ],
        "starting_materials": [
            {"name": "Phenol", "smiles": "Oc1ccccc1", "availability": "in_stock"},
        ],
        "overall_notes": "classic route",
        "_model": "test",
    }
    route = chem_synthesis._assemble_route(target, raw)
    assert route["n_steps"] == 3
    assert all(s["product_valid"] for s in route["steps"])
    assert route["route_reaches_target"] is True       # final step == target
    assert route["n_invalid_intermediates"] == 0
    assert route["estimated_cost_usd"] > 0
    assert route["cost_band"] in {"low", "moderate", "high"}
    assert route["feasibility_band"] in {"ready", "workable", "hard"}
    assert 0.0 <= route["feasibility"] <= 1.0
    assert route["starting_materials"][0]["smiles_valid"] is True


def test_assemble_route_flags_invalid_intermediate():
    raw = {
        "steps": [
            {"name": "bad step", "product_smiles": "XYZ-not-valid-!!"},
            {"name": "ok step", "product_smiles": "CCO"},
        ],
        "starting_materials": [],
        "_model": "test",
    }
    route = chem_synthesis._assemble_route("CCO", raw)
    assert route["n_invalid_intermediates"] == 1
    assert route["steps"][0]["product_valid"] is False
    assert route["steps"][1]["product_valid"] is True
    # An invalid intermediate must drag feasibility down.
    assert route["feasibility"] < 1.0


def test_assemble_route_cost_scales_with_custom_materials():
    base = {"steps": [{"name": "s", "product_smiles": "CCO"}],
            "starting_materials": [], "_model": "test"}
    custom = {"steps": [{"name": "s", "product_smiles": "CCO"}],
              "starting_materials": [
                  {"name": "exotic", "smiles": "CCO", "availability": "custom"}],
              "_model": "test"}
    r_base = chem_synthesis._assemble_route("CCO", base)
    r_custom = chem_synthesis._assemble_route("CCO", custom)
    assert r_custom["estimated_cost_usd"] > r_base["estimated_cost_usd"]
    assert r_custom["lead_time_days"] > r_base["lead_time_days"]


def test_heuristic_route_is_valid_skeleton():
    raw = chem_synthesis._heuristic_route("CC(=O)Nc1ccc(O)cc1")
    assert raw["_model"] == "heuristic"
    assert len(raw["steps"]) >= 2
    route = chem_synthesis._assemble_route("CC(=O)Nc1ccc(O)cc1", raw)
    assert route["n_steps"] >= 2
    assert route["feasibility"] >= 0.1


# ─────────────────────────────────────────────────────────────────────
# C. HTTP surface — /chem/synthesis plan + CRUD (TestClient, in-process)
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture()
def no_gemini(monkeypatch):
    """Force the deterministic heuristic route — no network, fast."""
    async def _none(_smiles):
        return None
    monkeypatch.setattr(chem_synthesis, "_gemini_route", _none)


def test_plan_endpoint_rejects_bad_input(no_gemini):
    assert client.post("/workbench/chem/synthesis/plan", json={"smiles": ""}).status_code == 400
    r = client.post("/workbench/chem/synthesis/plan", json={"smiles": "!!!bad!!!"})
    assert r.status_code == 422


def test_plan_endpoint_returns_valid_route(no_gemini):
    r = client.post("/workbench/chem/synthesis/plan", json={
        "smiles": "CC(=O)Nc1ccc(O)cc1", "session_id": "httpSess", "save": True,
    })
    assert r.status_code == 200
    d = r.json()
    # Shape contract every downstream consumer (agent, workflow, card) relies on.
    for key in ("smiles", "n_steps", "steps", "starting_materials",
                "estimated_cost_usd", "cost_band", "lead_time_days",
                "feasibility", "feasibility_band", "artifact_id"):
        assert key in d, f"missing key: {key}"
    assert d["n_steps"] >= 1
    assert d["artifact_id"]              # save=True must persist


def test_synthesis_crud_round_trip(no_gemini):
    # CREATE via plan
    plan = client.post("/workbench/chem/synthesis/plan", json={
        "smiles": "c1ccccc1O", "session_id": "crudSess", "save": True,
    }).json()
    rid = plan["artifact_id"]
    assert rid

    # READ — list (session-scoped) shows it
    lst = client.get("/workbench/chem/synthesis/routes?session_id=crudSess").json()
    assert lst["n"] >= 1
    assert any(x["id"] == rid for x in lst["routes"])

    # READ — get one
    one = client.get(f"/workbench/chem/synthesis/routes/{rid}").json()
    assert one["id"] == rid
    assert one["kind"] == "synthesis_route"

    # UPDATE — star + notes
    patched = client.patch(f"/workbench/chem/synthesis/routes/{rid}",
                           json={"starred": True, "notes": "promising"}).json()
    assert patched["payload"]["starred"] is True
    assert patched["payload"]["user_notes"] == "promising"

    # DELETE
    deld = client.delete(f"/workbench/chem/synthesis/routes/{rid}").json()
    assert deld["deleted"] is True
    assert client.get(f"/workbench/chem/synthesis/routes/{rid}").status_code == 404


def test_synthesis_routes_unknown_id_404():
    assert client.get("/workbench/chem/synthesis/routes/nope").status_code == 404
    assert client.delete("/workbench/chem/synthesis/routes/nope").status_code == 404


# ─────────────────────────────────────────────────────────────────────
# D. cross-layer integration invariants — the "in and out" wiring
# ─────────────────────────────────────────────────────────────────────

def test_every_agent_tool_has_a_dispatch_branch():
    """Every tool advertised in _TOOL_DEFS must be handled in
    _dispatch_tool — otherwise the agent can call a tool that 400s."""
    dispatch_src = inspect.getsource(agent_mod._dispatch_tool)
    missing = [
        t["name"] for t in agent_mod._TOOL_DEFS
        if f'name == "{t["name"]}"' not in dispatch_src
    ]
    assert not missing, f"agent tools with no dispatch branch: {missing}"


def test_every_orchestrator_workflow_is_registered():
    """Every workflow the orchestrator can route to must exist in the
    workflow registry — otherwise routing dead-ends."""
    registered = set(wf_mod._REGISTRY.keys())
    catalog = {w["name"] for w in orch_mod._KNOWN_WORKFLOWS}
    missing = catalog - registered
    assert not missing, f"orchestrator routes to unregistered workflows: {missing}"


def test_plan_synthesis_spans_all_layers():
    """Service 1 must be wired through EVERY layer — this is the
    end-to-end integration guarantee for the new service."""
    assert "plan_synthesis" in [t["name"] for t in agent_mod._TOOL_DEFS]
    assert 'name == "plan_synthesis"' in inspect.getsource(agent_mod._dispatch_tool)
    assert "plan_synthesis" in wf_mod._REGISTRY
    assert "plan_synthesis" in {w["name"] for w in orch_mod._KNOWN_WORKFLOWS}


def test_analyze_toxicity_tool_wired():
    """The toxicity tool (added so the agent stops deflecting) must be
    both declared and dispatchable."""
    assert "analyze_toxicity" in [t["name"] for t in agent_mod._TOOL_DEFS]
    assert 'name == "analyze_toxicity"' in inspect.getsource(agent_mod._dispatch_tool)


def test_synthesis_router_mounted():
    """The synthesis routes must actually be reachable on the app."""
    paths = {r.path for r in server.app.routes}
    assert "/workbench/chem/synthesis/plan" in paths
    assert "/workbench/chem/synthesis/routes" in paths


def test_every_pathogen_primary_pdb_is_card_backed():
    """Every pathogen's primary PDB target must exist in the curated
    CARD subset — else picking that pathogen 404s the resistance
    chain (the bug fixed earlier this cycle)."""
    import asyncio
    from workspace.api.workbench import list_pathogens
    from workspace.api import chem_resistance
    out = asyncio.run(list_pathogens())
    card_pdbs = set((getattr(chem_resistance, "_CARD", {}) or {}).get("by_pdb", {}).keys())
    bad = [
        p["code"] for p in out["pathogens"]
        if p.get("primary_pdb") and p["primary_pdb"] not in card_pdbs
    ]
    assert not bad, f"pathogens whose primary PDB is not CARD-backed: {bad}"


def test_orchestrator_narrate_endpoint_present():
    """The action-narrator endpoint (button clicks read as the agent)
    must be mounted."""
    paths = {r.path for r in server.app.routes}
    assert "/api/orchestrator/narrate" in paths
