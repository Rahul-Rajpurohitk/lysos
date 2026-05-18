"""Smoke tests for the 25-tool registry."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from tools import registry


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in registry.all()}


def test_registry_has_25_tools(tools):
    # The registry grew from the original 25 to 37 tools. Assert the
    # 25-tool floor (catches catastrophic tool loss) without breaking
    # every time a tool is legitimately added.
    assert len(tools) >= 25


def test_registry_has_all_amr_tools(tools):
    expected = {
        "predict_mic_pathogen", "check_resistance_genes",
        "predict_resistance_escape", "get_pathogen_resistome",
        "find_active_against_mdr",
    }
    missing = expected - set(tools)
    assert not missing


def test_get_pathogen_resistome_mrsa(tools):
    r = tools["get_pathogen_resistome"].call({"pathogen": "MRSA"})
    assert r["error"] is None
    assert r["result"]["pathogen"] == "MRSA"
    assert len(r["result"]["resistome"]) >= 4
    assert "mecA / PBP2a" in [g["gene"] for g in r["result"]["resistome"]]


def test_predict_mic_pathogen_returns_score(tools):
    r = tools["predict_mic_pathogen"].call({
        "smiles": "CC(=O)NCC1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1",  # linezolid
        "pathogen": "MRSA",
    })
    assert r["error"] is None
    assert 0 <= r["result"]["reward"] <= 1


def test_score_molecule_full_breakdown(tools):
    r = tools["score_molecule"].call({
        "smiles": "CC(=O)NCC1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1",
        "target_pathogen": "MRSA",
    })
    assert r["error"] is None
    components = r["result"]["components"]
    assert len(components) == 8
    assert 0 <= r["result"]["composite"] <= 1


def test_predict_admet_drug_likeness(tools):
    r = tools["predict_admet"].call({
        "smiles": "CC(=O)NCC1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1",
    })
    assert r["error"] is None
    res = r["result"]
    assert res["mw"] > 100
    assert res["lipinski_violations"] >= 0


def test_transform_structure_swap_chloro(tools):
    r = tools["transform_structure"].call({
        "smiles": "Clc1ccccc1",  # chlorobenzene
        "op": "swap_chloro_to_fluoro",
    })
    assert r["error"] is None
    assert len(r["result"]["products"]) > 0
    assert "F" in r["result"]["products"][0]


def test_compare_molecules(tools):
    r = tools["compare_molecules"].call({
        "smiles_a": "CC(=O)NCC1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1",
        "smiles_b": "O=C(O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O",
        "pathogen": "MRSA",
    })
    assert r["error"] is None
    assert 0 <= r["result"]["tanimoto_similarity"] <= 1


def test_get_drug_history_known_drug(tools):
    r = tools["get_drug_history"].call({"drug_name": "linezolid"})
    assert r["error"] is None
    assert r["result"]["found"] is True
    assert r["result"]["year_approved"] == 2000


def test_find_target_structure_pdb_id(tools):
    r = tools["find_target_structure"].call({"pathogen": "MRSA"})
    assert r["error"] is None
    assert r["result"]["primary_target"]["pdb_id"] == "1VQQ"


def test_predict_resistance_escape_vre(tools):
    r = tools["predict_resistance_escape"].call({
        "smiles": "CC(=O)NCC1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1",  # linezolid
        "pathogen": "VRE",
    })
    assert r["error"] is None
    assert len(r["result"]["escape_mutations"]) > 0
    assert r["result"]["red_team_verdict"] in {"robust", "vulnerable", "highly_vulnerable"}


def test_invalid_smiles_validity_zero(tools):
    r = tools["score_molecule"].call({
        "smiles": "this-is-not-smiles",
        "target_pathogen": "MRSA",
    })
    # Should still return; validity should be 0
    if r["error"] is None:
        validity = next(
            c["value"] for c in r["result"]["components"] if c["name"] == "validity"
        )
        assert validity == 0


def test_tool_schemas_for_anthropic(tools):
    """Anthropic-format schemas — used by Claude function-calling."""
    schemas = registry.schemas_for_anthropic()
    # One schema per registered tool (registry has grown past 25).
    assert len(schemas) == len(tools)
    assert len(schemas) >= 25
    for s in schemas:
        assert "name" in s
        assert "description" in s
        assert "input_schema" in s
