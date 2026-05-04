"""Return curated development-history of a known drug — class, MoA, approval
year, target pathogens, key trials. Used by the Designer agent for context.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..base import tool


# Curated history database — drawn from elite reasoning slice + IDSA + literature
DRUG_HISTORY: dict[str, dict] = {
    "vancomycin": {
        "class": "glycopeptide",
        "moa": "binds D-Ala-D-Ala terminus of lipid II, blocks transglycosylation",
        "year_approved": 1958,
        "discoverer": "Eli Lilly",
        "scaffold_origin": "Streptomyces orientalis fermentation",
        "primary_targets": ["MRSA", "C. difficile", "VRSA-rare"],
        "key_trials": ["Foundational, no single trial — decades of clinical use"],
        "notable": "Long the last-line for MRSA. Now challenged by hVISA + VRSA.",
    },
    "linezolid": {
        "class": "oxazolidinone",
        "moa": "binds 50S A-site at A2451 of 23S rRNA, blocks 70S initiation complex",
        "year_approved": 2000,
        "discoverer": "Pharmacia",
        "scaffold_origin": "synthetic — first novel antibacterial class in 40 years",
        "primary_targets": ["MRSA", "VRE", "M. tuberculosis"],
        "key_trials": ["ZEPHyR (Wunderink 2012, MRSA pneumonia)", "ZeNix 2022 (TB)"],
        "notable": "First fully-synthetic novel-class antibiotic in 40 years.",
    },
    "daptomycin": {
        "class": "lipopeptide",
        "moa": "Ca2+-dependent membrane depolarization via PG insertion",
        "year_approved": 2003,
        "discoverer": "Cubist",
        "scaffold_origin": "Streptomyces roseosporus fermentation",
        "primary_targets": ["MRSA bacteremia", "right-sided endocarditis", "VRE"],
        "key_trials": ["Fowler 2006 NEJM (non-inferior vs vanco)"],
        "notable": "Surfactant-inactivated → no pneumonia use.",
    },
    "ceftaroline": {
        "class": "anti-MRSA cephalosporin",
        "moa": "binds PBP2a allosteric site, opens active-site groove",
        "year_approved": 2010,
        "discoverer": "Forest / Cerexa",
        "scaffold_origin": "synthetic — engineered C3 thiazolyl-pyridinium",
        "primary_targets": ["MRSA pneumonia + SSTI", "PRSP"],
        "key_trials": ["FOCUS (CABP)", "CANVAS 1/2 (SSTI)"],
        "notable": "First cephalosporin with MRSA activity via allosteric PBP2a binding.",
    },
    "bedaquiline": {
        "class": "diarylquinoline",
        "moa": "atpE c-ring of mycobacterial F1-F0 ATP synthase",
        "year_approved": 2012,
        "discoverer": "Janssen / Tibotec",
        "scaffold_origin": "synthetic high-throughput screen",
        "primary_targets": ["MDR-TB", "XDR-TB"],
        "key_trials": ["Nix-TB 2020 NEJM (BPaL)", "ZeNix 2022", "TB-PRACTECAL"],
        "notable": "First new TB drug class in 40 years. Persister-active.",
    },
    "ceftolozane-tazobactam": {
        "class": "engineered cephalosporin + tazobactam BLI",
        "moa": "C3 substituent reduces MexAB-OprM efflux substrate fit",
        "year_approved": 2014,
        "discoverer": "Cubist / Merck",
        "primary_targets": ["MDR P. aeruginosa", "ESBL Enterobacterales"],
        "key_trials": ["ASPECT-cIAI", "ASPECT-NP (HABP/VABP)"],
        "notable": "First engineered Pseudomonas-active cephalosporin.",
    },
    "ceftazidime-avibactam": {
        "class": "ceph + DBO BLI",
        "moa": "avibactam covalently inhibits class A/C/D serine BLs",
        "year_approved": 2015,
        "discoverer": "Allergan / AstraZeneca",
        "primary_targets": ["KPC-CRE", "OXA-48"],
        "key_trials": ["RECAPTURE", "REPRISE", "REPROVE"],
        "notable": "KPC-31 D179Y escape mutation drives meropenem-vaborbactam choice.",
    },
    "meropenem-vaborbactam": {
        "class": "carbapenem + cyclic boronic-acid BLI",
        "moa": "vaborbactam reversibly covalently inhibits class A serine BLs",
        "year_approved": 2017,
        "discoverer": "Rempex / Melinta",
        "primary_targets": ["KPC-CRE"],
        "key_trials": ["TANGO-II 2018 (Wunderink)"],
        "notable": "Retains activity against KPC-31 escape mutation.",
    },
    "cefiderocol": {
        "class": "siderophore cephalosporin",
        "moa": "catechol chelates Fe3+, Trojan-horse uptake via TonB receptors",
        "year_approved": 2019,
        "discoverer": "Shionogi",
        "primary_targets": ["NDM/VIM/IMP MBL gram-negs", "CRAB", "Stenotrophomonas"],
        "key_trials": ["CREDIBLE-CR (mortality black-box flag)", "APEKS-NP"],
        "notable": "First siderophore-cephalosporin; bypasses porin loss + efflux.",
    },
    "pretomanid": {
        "class": "bicyclic 4-nitroimidazole prodrug",
        "moa": "Ddn nitroreductase activates → NO + mycolic-acid disruption",
        "year_approved": 2019,
        "discoverer": "TB Alliance",
        "primary_targets": ["XDR-TB"],
        "key_trials": ["Nix-TB 2020 NEJM"],
        "notable": "Persister-killing, hypoxia-active. BPaL component.",
    },
    "sulbactam-durlobactam": {
        "class": "penam-sulfone + DBO with class-D coverage",
        "moa": "sulbactam binds CRAB PBP1/3; durlobactam protects from OXA-23/24/58",
        "year_approved": 2023,
        "discoverer": "Innoviva / La Jolla",
        "primary_targets": ["CRAB"],
        "key_trials": ["ATTACK 2023 (Bouza, Lancet ID)"],
        "notable": "First DBO with class-D OXA coverage — paradigm shift for CRAB.",
    },
    "gepotidacin": {
        "class": "triazaacenaphthylene NBTI",
        "moa": "gyrase + topoisomerase IV at NEW pocket distinct from FQ pocket",
        "year_approved": 2024,
        "discoverer": "GSK",
        "primary_targets": ["ceftriaxone-R + FQ-R N. gonorrhoeae", "uncomplicated UTI"],
        "key_trials": ["EAGLE-2/3 (UTI)", "EAGLE-1 (gonorrhea)"],
        "notable": "First novel-target oral antibiotic in 20+ years.",
    },
}


class DrugHistoryInput(BaseModel):
    drug_name: str = Field(..., description="Drug name (case-insensitive)")


class DrugDevelopmentHistory(BaseModel):
    drug_name: str
    drug_class: str
    moa: str
    year_approved: int
    discoverer: Optional[str] = None
    scaffold_origin: Optional[str] = None
    primary_targets: list[str] = []
    key_trials: list[str] = []
    notable: Optional[str] = None
    found: bool


@tool(
    description=(
        "Look up curated development history of a known antibiotic — class, "
        "mechanism of action, approval year, primary targets, key trials, "
        "notable facts. Drawn from the elite reasoning slice + IDSA + literature."
    ),
    category="knowledge",
    input_model=DrugHistoryInput,
    output_model=DrugDevelopmentHistory,
    expected_duration_ms=10,
    tags=("knowledge", "history"),
)
def get_drug_history(drug_name: str) -> DrugDevelopmentHistory:
    key = drug_name.lower().strip()
    info = DRUG_HISTORY.get(key)
    if info is None:
        return DrugDevelopmentHistory(
            drug_name=drug_name, drug_class="unknown", moa="not in curated DB",
            year_approved=0, found=False,
        )
    return DrugDevelopmentHistory(
        drug_name=drug_name,
        drug_class=info["class"],
        moa=info["moa"],
        year_approved=info["year_approved"],
        discoverer=info.get("discoverer"),
        scaffold_origin=info.get("scaffold_origin"),
        primary_targets=info.get("primary_targets", []),
        key_trials=info.get("key_trials", []),
        notable=info.get("notable"),
        found=True,
    )
