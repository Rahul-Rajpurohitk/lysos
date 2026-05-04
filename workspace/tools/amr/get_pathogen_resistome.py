"""Return a structured summary of a pathogen's resistome — all resistance
genes, intrinsic features, drug-class vulnerabilities, and recommended
empirical-therapy options.

Used by the agent at session START to ground its understanding of the target.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..base import tool
from .check_resistance_genes import PATHOGEN_RESISTOME


# Curated empirical-therapy guidance per pathogen. Aligned with IDSA + AMR 2024.
EMPIRICAL_GUIDANCE: dict[str, dict] = {
    "MRSA": {
        "first_line": ["vancomycin AUC 400-600", "daptomycin 8-12 mg/kg",
                       "linezolid (preferred for pneumonia)", "ceftaroline (anti-MRSA ceph)"],
        "syndromes": ["bacteremia", "endocarditis", "pneumonia", "SSTI", "osteomyelitis"],
        "context": "mecA/PBP2a is the defining feature. Ceftaroline is the only "
                   "cephalosporin active vs MRSA via allosteric PBP2a binding.",
    },
    "Mtb": {
        "first_line": ["BPaLM (bedaquiline + pretomanid + linezolid + moxifloxacin)",
                       "BPaL (FQ-resistant cases)", "RIPE for drug-susceptible"],
        "syndromes": ["pulmonary", "extrapulmonary", "MDR/XDR-TB"],
        "context": "MDR = R/H resistant. XDR adds FQ + 2nd-line injectable. "
                   "atpE c-ring + Ddn nitroreductase are the persister-killing targets.",
    },
    "EColi-CRE": {
        "first_line": ["meropenem-vaborbactam (KPC)",
                       "ceftazidime-avibactam (KPC, OXA-48)",
                       "cefiderocol (MBL)",
                       "aztreonam-avibactam (NDM + ESBL)",
                       "plazomicin (cUTI)"],
        "syndromes": ["bacteremia", "cUTI", "intra-abdominal", "HAP/VAP"],
        "context": "MERINO trial (Harris 2018 JAMA) — meropenem > pip-tazo for ESBL bacteremia. "
                   "KPC-31 D179Y escape from avibactam reverses to mero-vab susceptibility.",
    },
    "KpneuCRE": {
        "first_line": ["meropenem-vaborbactam (KPC)",
                       "ceftazidime-avibactam (KPC, OXA-48)",
                       "aztreonam-avibactam (MBL+ESBL co-resident)"],
        "syndromes": ["bacteremia", "HAP/VAP", "cUTI"],
        "context": "OmpK35/36 porin loss + KPC + ESBL is the dominant phenotype. "
                   "TANGO-II trial supports mero-vab.",
    },
    "Abaum": {
        "first_line": ["sulbactam-durlobactam (CRAB, ATTACK trial Bouza 2023)",
                       "cefiderocol (CREDIBLE-CR caveat)",
                       "polymyxin-B + tigecycline + meropenem combo (legacy)"],
        "syndromes": ["VAP", "bacteremia", "wound", "meningitis"],
        "context": "OXA-23 is the most common acquired carbapenemase. "
                   "Sulbactam alone is the active arm (sulbactam itself is the antibiotic, "
                   "DBO partner protects it).",
    },
    "Paer": {
        "first_line": ["ceftolozane-tazobactam (MexAB-overexpressers)",
                       "cefiderocol (MBL)",
                       "imipenem-relebactam",
                       "tobramycin-add-on for severe"],
        "syndromes": ["VAP", "CF lung", "bacteremia", "burn wound"],
        "context": "MexAB-OprM efflux + OprD porin loss + AmpC is the MDR triad. "
                   "Inhaled tobramycin for chronic CF colonization.",
    },
    "VRE": {
        "first_line": ["daptomycin 10-12 mg/kg (bactericidal)",
                       "linezolid 600 mg q12h (bacteriostatic but oral)",
                       "tedizolid (cfr-positive partial rescue)",
                       "oritavancin (vanA single-dose)"],
        "syndromes": ["bacteremia", "endocarditis (E. faecium)", "cUTI"],
        "context": "vanA Tn1546 D-Ala-D-Lac substitution. cfr methylation is "
                   "the rising linezolid-resistance threat (PhLOPSa cross-resistance).",
    },
    "NGono": {
        "first_line": ["ceftriaxone 500 mg IM x 1 (CDC 2021)",
                       "gepotidacin (novel target, FQ-R + CRO-R rescue)",
                       "azithromycin (deprioritized — rising R)"],
        "syndromes": ["urethritis", "PID", "disseminated", "ophthalmia"],
        "context": "penA mosaic genes + 23S rRNA mutations. XDR strains require "
                   "novel-target NBTIs (gepotidacin, zoliflodacin).",
    },
}


class GetResistomeInput(BaseModel):
    pathogen: str = Field(..., description="Pathogen short code")


class ResistomeEntry(BaseModel):
    gene: str
    affects: list[str]


class PathogenResistome(BaseModel):
    pathogen: str
    full_name: str
    resistome: list[ResistomeEntry]
    intrinsic_features: list[str]
    first_line_therapy: list[str]
    common_syndromes: list[str]
    clinical_context: str


PATHOGEN_FULL_NAMES = {
    "MRSA": "Methicillin-resistant Staphylococcus aureus",
    "Mtb": "Mycobacterium tuberculosis",
    "EColi-CRE": "Escherichia coli (ESBL+/CRE)",
    "KpneuCRE": "Klebsiella pneumoniae (CRE)",
    "Abaum": "Acinetobacter baumannii (carbapenem-resistant)",
    "Paer": "Pseudomonas aeruginosa (MDR)",
    "VRE": "Enterococcus faecium / faecalis (vanA/vanB)",
    "NGono": "Neisseria gonorrhoeae (XDR)",
}

INTRINSIC = {
    "MRSA": ["gram-positive cocci", "low-affinity PBP2a (mecA)", "biofilm-forming on hardware"],
    "Mtb": ["acid-fast bacillus", "mycolic-acid waxy cell wall (low permeability)",
            "intracellular in macrophages", "non-replicating persister state in granulomas"],
    "EColi-CRE": ["gram-negative bacillus", "OM porins OmpF/OmpC",
                  "AmpC chromosomal repressed (low constitutive)"],
    "KpneuCRE": ["gram-negative bacillus", "polysaccharide capsule (K1/K2 hypervirulent)",
                 "OmpK35/OmpK36 porins"],
    "Abaum": ["gram-negative coccobacillus", "intrinsic blaOXA-51 chromosomal",
              "extreme environmental persistence (weeks on surfaces)"],
    "Paer": ["gram-negative bacillus", "MexAB-OprM constitutive efflux",
             "OprD carbapenem-specific porin", "biofilm-forming in CF lung"],
    "VRE": ["gram-positive cocci", "intrinsic low-affinity PBP5 (E. faecium)",
            "intrinsic resistance to cephalosporins"],
    "NGono": ["gram-negative diplococcus", "obligate human pathogen",
              "high transformation/recombination rate (penA mosaicism)"],
}


@tool(
    description=(
        "Return a structured summary of a pathogen's resistome — all resistance "
        "genes, intrinsic features, drug-class vulnerabilities, and recommended "
        "empirical therapy. Use at session START to ground the agent's "
        "understanding of the target."
    ),
    category="amr",
    input_model=GetResistomeInput,
    output_model=PathogenResistome,
    expected_duration_ms=10,
    tags=("amr", "knowledge", "resistome", "core"),
)
def get_pathogen_resistome(pathogen: str) -> PathogenResistome:
    resistome_dict = PATHOGEN_RESISTOME.get(pathogen, {})
    guidance = EMPIRICAL_GUIDANCE.get(pathogen, {})

    return PathogenResistome(
        pathogen=pathogen,
        full_name=PATHOGEN_FULL_NAMES.get(pathogen, pathogen),
        resistome=[ResistomeEntry(gene=g, affects=a) for g, a in resistome_dict.items()],
        intrinsic_features=INTRINSIC.get(pathogen, []),
        first_line_therapy=guidance.get("first_line", []),
        common_syndromes=guidance.get("syndromes", []),
        clinical_context=guidance.get("context", ""),
    )
