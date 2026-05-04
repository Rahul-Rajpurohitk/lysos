"""Find existing approved/late-stage drugs known to be active against a given
panel of MDR pathogens. Used as in-context examples for the designer agent.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..base import tool


# Curated active-drug map per pathogen — same source as elite reasoning slice.
ACTIVE_DRUGS: dict[str, list[dict]] = {
    "MRSA": [
        {"name": "vancomycin", "class": "glycopeptide", "status": "approved",
         "mic50_ug_ml": 1.0, "note": "AUC/MIC 400-600 target"},
        {"name": "daptomycin", "class": "lipopeptide", "status": "approved",
         "mic50_ug_ml": 0.25, "note": "8-12 mg/kg high dose for bacteremia"},
        {"name": "linezolid", "class": "oxazolidinone", "status": "approved",
         "mic50_ug_ml": 1.0, "note": "preferred for MRSA pneumonia (ZEPHyR)"},
        {"name": "ceftaroline", "class": "anti-MRSA cephalosporin", "status": "approved",
         "mic50_ug_ml": 1.0, "note": "allosteric PBP2a binder"},
        {"name": "tedizolid", "class": "oxazolidinone", "status": "approved",
         "mic50_ug_ml": 0.25, "note": "lower MAO-A inhibition than linezolid"},
        {"name": "delafloxacin", "class": "fluoroquinolone", "status": "approved",
         "mic50_ug_ml": 0.06, "note": "anionic at acidic pH"},
        {"name": "telavancin", "class": "lipoglycopeptide", "status": "approved",
         "mic50_ug_ml": 0.25, "note": "REMS pregnancy testing"},
        {"name": "dalbavancin", "class": "lipoglycopeptide", "status": "approved",
         "mic50_ug_ml": 0.06, "note": "single-dose 8.5-day half-life"},
        {"name": "oritavancin", "class": "lipoglycopeptide", "status": "approved",
         "mic50_ug_ml": 0.06, "note": "active vs vanA VRE via dual mechanism"},
    ],
    "Mtb": [
        {"name": "rifampin", "class": "rifamycin", "status": "approved",
         "mic50_ug_ml": 0.06, "note": "rpoB target; never as monotherapy"},
        {"name": "isoniazid", "class": "INH (KatG-activated)", "status": "approved",
         "mic50_ug_ml": 0.05, "note": "KatG Ser315Thr ~70% of clinical INH-R"},
        {"name": "bedaquiline", "class": "diarylquinoline", "status": "approved",
         "mic50_ug_ml": 0.06, "note": "atpE c-ring; 5.5-month M2 metabolite"},
        {"name": "pretomanid", "class": "nitroimidazole prodrug", "status": "approved",
         "mic50_ug_ml": 0.1, "note": "Ddn-activated NO release; persister-killing"},
        {"name": "linezolid (BPaL)", "class": "oxazolidinone", "status": "approved",
         "mic50_ug_ml": 0.5, "note": "ZeNix supports 600 mg daily"},
        {"name": "moxifloxacin", "class": "fluoroquinolone", "status": "approved",
         "mic50_ug_ml": 0.25, "note": "C8 methoxy improves potency vs gyrA single mutants"},
        {"name": "delamanid", "class": "nitroimidazole prodrug", "status": "approved",
         "mic50_ug_ml": 0.1, "note": "alternative to pretomanid"},
    ],
    "EColi-CRE": [
        {"name": "meropenem-vaborbactam", "class": "carbapenem + boronic-acid BLI",
         "status": "approved", "mic50_ug_ml": 0.06, "note": "TANGO-II for KPC-CRE"},
        {"name": "ceftazidime-avibactam", "class": "ceph + DBO BLI", "status": "approved",
         "mic50_ug_ml": 0.5, "note": "covers KPC + OXA-48; KPC-31 escape"},
        {"name": "cefiderocol", "class": "siderophore cephalosporin", "status": "approved",
         "mic50_ug_ml": 0.5, "note": "Trojan-horse uptake, MBL-stable"},
        {"name": "aztreonam-avibactam", "class": "monobactam + DBO", "status": "approved 2024",
         "mic50_ug_ml": 1.0, "note": "MBL + ESBL co-resident"},
        {"name": "plazomicin", "class": "aminoglycoside", "status": "approved",
         "mic50_ug_ml": 1.0, "note": "EPIC trial for cUTI"},
        {"name": "imipenem-relebactam", "class": "carbapenem + DBO", "status": "approved",
         "mic50_ug_ml": 0.25, "note": "RESTORE-IMI for KPC-CRE"},
    ],
    "KpneuCRE": [
        {"name": "meropenem-vaborbactam", "class": "carbapenem + boronic-acid BLI",
         "status": "approved", "mic50_ug_ml": 0.06, "note": ""},
        {"name": "ceftazidime-avibactam", "class": "ceph + DBO BLI", "status": "approved",
         "mic50_ug_ml": 0.5, "note": ""},
        {"name": "cefiderocol", "class": "siderophore cephalosporin", "status": "approved",
         "mic50_ug_ml": 0.5, "note": ""},
        {"name": "aztreonam-avibactam", "class": "monobactam + DBO", "status": "approved 2024",
         "mic50_ug_ml": 1.0, "note": ""},
    ],
    "Abaum": [
        {"name": "sulbactam-durlobactam", "class": "penam-sulfone + DBO (class-D coverage)",
         "status": "approved", "mic50_ug_ml": 1.0, "note": "ATTACK trial (Bouza 2023)"},
        {"name": "cefiderocol", "class": "siderophore cephalosporin", "status": "approved",
         "mic50_ug_ml": 1.5, "note": "CREDIBLE-CR mortality concern"},
        {"name": "tigecycline (high-dose)", "class": "glycylcycline", "status": "approved",
         "mic50_ug_ml": 1.0, "note": "100 mg q12h for severe; bacteremia black-box"},
        {"name": "polymyxin-B (legacy)", "class": "polymyxin", "status": "approved",
         "mic50_ug_ml": 1.0, "note": "25-30% nephrotox"},
    ],
    "Paer": [
        {"name": "ceftolozane-tazobactam", "class": "engineered ceph + tazo",
         "status": "approved", "mic50_ug_ml": 1.0, "note": "low MexAB efflux substrate"},
        {"name": "cefiderocol", "class": "siderophore cephalosporin", "status": "approved",
         "mic50_ug_ml": 1.0, "note": ""},
        {"name": "imipenem-relebactam", "class": "carbapenem + DBO", "status": "approved",
         "mic50_ug_ml": 0.5, "note": "compensates OprD loss"},
        {"name": "tobramycin (inhaled)", "class": "aminoglycoside", "status": "approved",
         "mic50_ug_ml": 1.0, "note": "TOBI Podhaler for chronic CF"},
        {"name": "aztreonam (inhaled)", "class": "monobactam", "status": "approved",
         "mic50_ug_ml": 0.25, "note": "Cayston inhaled, alternative to tobi"},
    ],
    "VRE": [
        {"name": "linezolid", "class": "oxazolidinone", "status": "approved",
         "mic50_ug_ml": 1.0, "note": "bacteriostatic but oral"},
        {"name": "daptomycin (high-dose)", "class": "lipopeptide", "status": "approved",
         "mic50_ug_ml": 1.0, "note": "10-12 mg/kg for endocarditis"},
        {"name": "tedizolid", "class": "oxazolidinone", "status": "approved",
         "mic50_ug_ml": 0.5, "note": "partial rescue for cfr+"},
        {"name": "oritavancin", "class": "lipoglycopeptide", "status": "approved",
         "mic50_ug_ml": 0.06, "note": "active vs vanA via membrane mechanism"},
    ],
    "NGono": [
        {"name": "ceftriaxone", "class": "3G cephalosporin", "status": "approved",
         "mic50_ug_ml": 0.06, "note": "500 mg IM x 1 (CDC 2021); rising R"},
        {"name": "gepotidacin", "class": "NBTI (novel)", "status": "approved 2024",
         "mic50_ug_ml": 0.06, "note": "novel gyrase pocket; FQ-R + CRO-R rescue"},
        {"name": "zoliflodacin", "class": "spiropyrimidinetrione", "status": "phase 3",
         "mic50_ug_ml": 0.12, "note": "single oral dose"},
    ],
}


class FindActiveInput(BaseModel):
    pathogens: list[str] = Field(..., description="One or more pathogen short codes")
    require_all: bool = Field(False, description="If True, only return drugs active vs ALL pathogens")
    status_filter: Literal["any", "approved", "phase 3 or later"] = "any"


class KnownDrug(BaseModel):
    name: str
    drug_class: str
    status: str
    mic50_ug_ml: float
    note: str
    pathogens_covered: list[str]


class FindActiveOutput(BaseModel):
    pathogens: list[str]
    drugs: list[KnownDrug]
    summary: str


@tool(
    description=(
        "Find existing approved/late-stage drugs known to be active against a "
        "panel of MDR pathogens. Used as in-context examples for the designer "
        "agent (RAG)."
    ),
    category="amr",
    input_model=FindActiveInput,
    output_model=FindActiveOutput,
    expected_duration_ms=20,
    tags=("amr", "knowledge", "rag"),
)
def find_active_against_mdr(
    pathogens: list[str],
    require_all: bool = False,
    status_filter: str = "any",
) -> FindActiveOutput:
    # Aggregate by drug name across pathogens
    by_name: dict[str, dict] = {}
    for p in pathogens:
        for d in ACTIVE_DRUGS.get(p, []):
            key = d["name"]
            if key not in by_name:
                by_name[key] = {**d, "pathogens_covered": []}
            by_name[key]["pathogens_covered"].append(p)

    drugs = []
    for key, info in by_name.items():
        if require_all and len(info["pathogens_covered"]) < len(pathogens):
            continue
        if status_filter != "any":
            if status_filter == "approved" and "approved" not in info["status"]:
                continue
            if status_filter == "phase 3 or later" and (
                "approved" not in info["status"] and "phase 3" not in info["status"]
            ):
                continue
        drugs.append(KnownDrug(
            name=info["name"],
            drug_class=info["class"],
            status=info["status"],
            mic50_ug_ml=info["mic50_ug_ml"],
            note=info["note"],
            pathogens_covered=info["pathogens_covered"],
        ))

    drugs.sort(key=lambda d: (-len(d.pathogens_covered), d.mic50_ug_ml))

    if drugs:
        summary = (
            f"Found {len(drugs)} drugs active vs {pathogens}. "
            f"Top option by coverage + potency: {drugs[0].name} "
            f"({drugs[0].drug_class}, MIC50 {drugs[0].mic50_ug_ml} µg/mL)."
        )
    else:
        summary = f"No drugs found matching the filters for {pathogens}."

    return FindActiveOutput(pathogens=pathogens, drugs=drugs, summary=summary)
