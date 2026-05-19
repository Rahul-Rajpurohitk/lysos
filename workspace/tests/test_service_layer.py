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
    base = {"steps": [{"name": "s", "reaction_class": "acylation",
                       "product_smiles": "CCO"}],
            "starting_materials": [], "_model": "test"}
    # A complex polycyclic multi-stereocentre SM — must be DERIVED as
    # 'custom' from structure, NOT taken from any input field.
    complex_smi = ("O=C(O)C1=C(Cn2nnc(C(F)(F)F)c2N)CS[C@]2([H])[C@H]"
                   "(NC(=O)C(=NOC)c3csc(N)n3)C(=O)N12")
    with_custom = {"steps": [{"name": "s", "reaction_class": "acylation",
                              "product_smiles": "CCO"}],
                   "starting_materials": [
                       {"name": "complex intermediate", "smiles": complex_smi}],
                   "_model": "test"}
    r_base = chem_synthesis._assemble_route("CCO", base)
    r_custom = chem_synthesis._assemble_route("CCO", with_custom)
    # Availability is derived — the complex SM lands in 'custom'.
    assert r_custom["starting_materials"][0]["availability"] == "custom"
    assert r_custom["estimated_cost_usd"] > r_base["estimated_cost_usd"]
    assert r_custom["lead_time_days"] > r_base["lead_time_days"]


def test_cost_model_responds_to_reaction_class():
    """A Pd cross-coupling step must cost materially more than a simple
    acylation — the cost is NOT a flat per-step constant."""
    suzuki_usd, _ = chem_synthesis._step_cost("Aryl coupling", "Suzuki coupling")
    acyl_usd, _ = chem_synthesis._step_cost("Cap the amine", "acylation")
    boc_usd, _ = chem_synthesis._step_cost("Remove protecting group", "Boc deprotection")
    assert suzuki_usd > acyl_usd > 0
    assert suzuki_usd >= 2 * boc_usd        # precious-metal tier vs robust tier


def test_building_block_availability_derived_from_structure():
    """Availability must come from RDKit structural complexity, not a
    model claim."""
    tiny = chem_synthesis._assess_building_block("CCO", "ethanol")
    assert tiny["availability"] == "in_stock"
    complex_bb = chem_synthesis._assess_building_block(
        "O=C(O)C1=C(Cn2nnc(C(F)(F)F)c2N)CS[C@]2([H])[C@H]"
        "(NC(=O)C(=NOC)c3csc(N)n3)C(=O)N12", "cephem core")
    assert complex_bb["availability"] == "custom"
    assert complex_bb["est_cost_usd"] > tiny["est_cost_usd"]


def test_route_tracks_cumulative_yield():
    raw = {
        "steps": [
            {"name": "a", "reaction_class": "acylation",
             "product_smiles": "CCO", "yield_pct": 90},
            {"name": "b", "reaction_class": "reduction",
             "product_smiles": "CCO", "yield_pct": 80},
        ],
        "starting_materials": [], "_model": "test",
    }
    route = chem_synthesis._assemble_route("CCO", raw)
    # 0.90 * 0.80 = 0.72 → 72%
    assert abs(route["overall_yield_pct"] - 72.0) < 0.5
    assert route["steps"][0]["yield_pct"] == 90.0


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
    """Kill ALL Gemini calls at the single _gemini_json seam — the route
    proposer falls back to the heuristic, the critic to its
    deterministic review. No network, deterministic, fast."""
    async def _none(*_args, **_kwargs):
        return None
    monkeypatch.setattr(chem_synthesis, "_gemini_json", _none)


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


# ─────────────────────────────────────────────────────────────────────
# E. Candidate Dossier — the integration backbone
# ─────────────────────────────────────────────────────────────────────

from workspace.api import candidate_dossier as dossier_mod  # noqa: E402


def test_dossier_upsert_accumulates_facets():
    """Each service's upsert_facet attaches onto ONE shared dossier."""
    smi = "CC(=O)Nc1ccc(O)cc1"
    dossier_mod.upsert_facet("dosSess1", smi, "score",
                             {"composite": 0.55, "weakest": "novelty"})
    dossier_mod.upsert_facet("dosSess1", smi, "resistance",
                             {"robustness": 0.82, "n_vulnerable": 2})
    d = dossier_mod.upsert_facet("dosSess1", smi, "synthesis",
                                 {"n_steps": 3, "cost_band": "low", "feasibility": 0.9})
    assert set(d["facets"]) == {"score", "resistance", "synthesis"}
    assert d["facets"]["score"]["composite"] == 0.55
    # All three upserts land on the SAME dossier (deterministic id).
    fetched = dossier_mod.get_dossier("dosSess1", smi)
    assert fetched is not None
    assert len(fetched["facets"]) == 3


def test_dossier_developability_rollup():
    smi = "c1ccc(O)cc1"
    dossier_mod.upsert_facet("dosSess2", smi, "score", {"composite": 0.7})
    d = dossier_mod.upsert_facet("dosSess2", smi, "synthesis",
                                 {"feasibility": 0.8, "cost_band": "low"})
    dev = d["developability"]
    assert dev["characterized"] == 2
    assert dev["total_facets"] == 6
    assert set(dev["gaps"]) == {"resistance", "fto", "admet", "regimen"}
    assert 0.0 <= dev["readiness"] <= 1.0
    assert dev["tier"] in {"advance", "promising", "early", "uncharacterized"}


def test_dossier_flags_cross_facet_risks():
    """A weak facet must raise a cross-facet flag."""
    smi = "CCOc1ccccc1"
    d = dossier_mod.upsert_facet("dosSess3", smi, "score", {"composite": 0.30})
    assert any("composite" in f for f in d["developability"]["flags"])
    d2 = dossier_mod.upsert_facet("dosSess3", smi, "resistance", {"robustness": 0.55})
    assert any("resistance" in f for f in d2["developability"]["flags"])


def test_dossier_harness_feed_from_state():
    """feed_from_state — the harness hook — must auto-link facets from
    a workflow's final state with no per-service wiring."""
    fed = dossier_mod.feed_from_state({
        "_session_id": "dosSess4",
        "smiles": "CC(=O)Nc1ccc(O)cc1",
        "winner_score": {"composite": 0.6, "weakest": "synthesizability"},
        "prediction": {"robustness_score": 0.78, "vulnerable_atoms": [3, 7],
                       "target_name": "PBP2a"},
        "synthesis_route": {"n_steps": 4, "estimated_cost_usd": 400,
                            "cost_band": "moderate", "feasibility": 0.7,
                            "overall_yield_pct": 55},
        "pathogen": "MRSA",
    })
    assert set(fed) >= {"score", "resistance", "synthesis", "target"}
    d = dossier_mod.get_dossier("dosSess4", "CC(=O)Nc1ccc(O)cc1")
    assert d is not None
    assert d["facets"]["score"]["composite"] == 0.6
    assert d["facets"]["resistance"]["robustness"] == 0.78
    assert d["facets"]["synthesis"]["n_steps"] == 4


def test_dossier_summary_for_agent_context():
    smi = "CC(=O)Nc1ccc(O)cc1"
    dossier_mod.upsert_facet("dosSess5", smi, "score", {"composite": 0.5})
    summary = dossier_mod.dossier_summary("dosSess5", smi)
    assert "dossier" in summary.lower()
    assert "facets characterised" in summary


def test_dossier_endpoints_via_testclient():
    smi = "Cc1ccccc1"
    dossier_mod.upsert_facet("dosHttp", smi, "score", {"composite": 0.6})
    # Portfolio
    lst = client.get("/workbench/chem/dossier/dosHttp").json()
    assert lst["n"] >= 1
    assert any(d["smiles"] for d in lst["dossiers"])
    # Single candidate
    one = client.get(f"/workbench/chem/dossier/dosHttp/candidate?smiles={smi}")
    assert one.status_code == 200
    assert "developability" in one.json()
    # Unknown candidate → 404
    assert client.get(
        "/workbench/chem/dossier/dosHttp/candidate?smiles=C#N").status_code == 404


def test_dossier_router_mounted():
    paths = {r.path for r in server.app.routes}
    assert "/workbench/chem/dossier/{session_id}" in paths
    assert "/workbench/chem/dossier/{session_id}/candidate" in paths


def test_synthesis_workflow_is_three_streamed_steps():
    """The plan_synthesis workflow must expose 3 streamed steps so the
    agent is visibly working (editor → validate → critic)."""
    wf = wf_mod._REGISTRY.get("plan_synthesis")
    assert wf is not None
    assert len(wf.steps) == 3
    step_ids = [s.id for s in wf.steps]
    assert step_ids == ["plan_route", "validate_cost", "critique"]


# ─────────────────────────────────────────────────────────────────────
# F. Service 2 — IP / FTO Sentinel
# ─────────────────────────────────────────────────────────────────────

from workspace.api import chem_ip as ip_mod  # noqa: E402


@pytest.fixture()
def fto_offline(monkeypatch):
    """Skip the escape-variant design (Gemini) — the prior-art scan is
    real RDKit maths + deterministic; the variant design needs network."""
    async def _none(_scan):
        return None
    monkeypatch.setattr(ip_mod, "_design_escape_variant", _none)


def test_fto_reference_panel_loads_from_data_file():
    """The reference panel must load from the JSON data file (NOT a
    hardcoded inline list) and fingerprint, dropping bad SMILES."""
    fps = ip_mod._reference_fps()
    assert len(fps) >= 12
    for entry, _fp in fps:
        # Honest public-record fields only — no fabricated patent number.
        assert "name" in entry and "ip_status" in entry
        assert "patent" not in entry        # the fabricated field is gone


def test_fto_verdict_ladder_is_internally_consistent():
    """The verdict must agree with the similarity it is derived from —
    it can no longer say 'analogous IP nearby' when nothing is near."""
    # Exact published match → not novel.
    v_exact, tier_exact, _ = ip_mod._verdict(1.0, None)
    assert "not novel" in v_exact and tier_exact == "none"
    # Nothing similar → structurally novel (NOT 'watch').
    v_far, tier_far, _ = ip_mod._verdict(0.20, None)
    assert "novel" in v_far and tier_far == "high"
    assert "nearby" not in v_far.lower()
    # Close prior art → a real 'review' verdict.
    v_close, _, _ = ip_mod._verdict(0.78, None)
    assert "novel" in v_close or "review" in v_close


def test_fto_scan_endpoint_returns_honest_report(fto_offline):
    r = client.post("/workbench/chem/ip/fto-scan", json={
        "smiles": "CC(=O)Nc1ccc(O)cc1", "session_id": "ftoHttp",
        "save": True, "design_variant": False,
    })
    assert r.status_code == 200
    d = r.json()
    for key in ("smiles", "novelty_score", "novelty_tier", "verdict",
                "closest_published", "closest_published_similarity",
                "prior_art", "artifact_id"):
        assert key in d, f"missing key: {key}"
    assert 0.0 <= d["novelty_score"] <= 1.0
    # novelty_score must be consistent with closest similarity.
    assert abs(d["novelty_score"] - (1.0 - d["closest_published_similarity"])) < 0.01


def test_fto_does_not_surface_noise_as_a_threat(fto_offline):
    """A molecule far from every reference antibiotic must NOT get a
    fake 'closest analog' — closest_marketed_drug should be None."""
    # Caffeine — nothing like the antibiotic panel.
    d = client.post("/workbench/chem/ip/fto-scan", json={
        "smiles": "Cn1cnc2c1c(=O)n(C)c(=O)n2C", "session_id": "ftoNoise",
        "save": True, "design_variant": False,
    }).json()
    assert d["closest_marketed_drug"] is None    # no noise-level threat


def test_fto_scan_rejects_bad_input(fto_offline):
    assert client.post("/workbench/chem/ip/fto-scan", json={"smiles": ""}).status_code == 400
    assert client.post("/workbench/chem/ip/fto-scan",
                       json={"smiles": "!!!"}).status_code == 422


def test_fto_crud_round_trip(fto_offline):
    rep = client.post("/workbench/chem/ip/fto-scan", json={
        "smiles": "c1ccccc1O", "session_id": "ftoCrud",
        "save": True, "design_variant": False,
    }).json()
    rid = rep["artifact_id"]
    lst = client.get("/workbench/chem/ip/reports?session_id=ftoCrud").json()
    assert any(x["id"] == rid for x in lst["reports"])
    assert client.get(f"/workbench/chem/ip/reports/{rid}").status_code == 200
    assert client.delete(f"/workbench/chem/ip/reports/{rid}").json()["deleted"] is True
    assert client.get(f"/workbench/chem/ip/reports/{rid}").status_code == 404


def test_fto_feeds_the_candidate_dossier(fto_offline):
    """The IP scan must link an `fto` facet into the candidate dossier."""
    smi = "CCc1ccccc1"
    client.post("/workbench/chem/ip/fto-scan", json={
        "smiles": smi, "session_id": "ftoDossier",
        "save": True, "design_variant": False})
    d = dossier_mod.get_dossier("ftoDossier", smi)
    assert d is not None
    assert "fto" in d["facets"]
    assert "novelty_score" in d["facets"]["fto"]


def test_fto_escape_variant_skipped_when_already_novel():
    """When prior art is distant, no escape edit is manufactured."""
    import asyncio
    novel_scan = {"closest_published_similarity": 0.2, "smiles": "CCO",
                  "novelty_score": 0.8}
    assert asyncio.run(ip_mod._design_escape_variant(novel_scan)) is None


def test_fto_wired_across_all_layers():
    """Service 2 spans agent tool → dispatch → workflow → orchestrator."""
    assert "check_freedom_to_operate" in [t["name"] for t in agent_mod._TOOL_DEFS]
    assert 'name == "check_freedom_to_operate"' in inspect.getsource(agent_mod._dispatch_tool)
    assert "fto_scan" in wf_mod._REGISTRY
    assert len(wf_mod._REGISTRY["fto_scan"].steps) == 2
    assert "fto_scan" in {w["name"] for w in orch_mod._KNOWN_WORKFLOWS}


def test_fto_router_mounted():
    paths = {r.path for r in server.app.routes}
    assert "/workbench/chem/ip/fto-scan" in paths
    assert "/workbench/chem/ip/reports" in paths
