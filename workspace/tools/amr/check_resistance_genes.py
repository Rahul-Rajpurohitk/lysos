"""Check which CARD-known resistance genes are likely to compromise a candidate.

Uses the curated Pathogen → Resistance-gene → Drug-class map. The agent uses
this BEFORE proposing a candidate to anticipate which structural classes are
already compromised in the target pathogen.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..base import tool


# Curated resistome map per priority pathogen — drawn from CARD + clinical
# stewardship literature (matches what's in the elite reasoning slice we
# trained Stage 2 on). Acts as a fast lookup without needing the full CARD
# tarball at runtime.
PATHOGEN_RESISTOME: dict[str, dict[str, list[str]]] = {
    "MRSA": {
        "mecA / PBP2a": ["all_beta_lactams_except_anti_MRSA_cephs"],
        "Erm A/B/C": ["macrolides", "lincosamides", "streptogramin_B"],
        "tetK / tet(M)": ["tetracyclines (susceptible to tigecycline + eravacycline)"],
        "blaZ / penicillinase": ["penicillin_G"],
    },
    "Mtb": {
        "katG Ser315Thr": ["isoniazid"],
        "rpoB (RRDR S531L/H526Y)": ["rifampin"],
        "embB M306": ["ethambutol"],
        "atpE c-ring D28V/I66M": ["bedaquiline"],
        "ddn loss-of-function": ["pretomanid", "delamanid"],
        "Rv0678 / mmpS5-mmpL5": ["bedaquiline", "clofazimine (cross-resistance)"],
    },
    "EColi-CRE": {
        "blaCTX-M-15 ESBL": ["3G_cephalosporins", "aztreonam"],
        "blaKPC": ["carbapenems_except_with_BLI"],
        "blaNDM-1 / blaVIM / blaIMP (MBL)": ["all_beta_lactams_except_aztreonam_avibactam_or_cefiderocol"],
        "blaOXA-48": ["carbapenems_modestly", "ESBL_susceptible_unless_CTX-M_co-resident"],
        "AAC(6')-Ib-cr": ["aminoglycosides", "ciprofloxacin"],
    },
    "KpneuCRE": {
        "blaKPC-2/3 (most common)": ["carbapenems_except_with_BLI"],
        "blaKPC-31 (D179Y)": ["ceftazidime-avibactam (ESCAPE mutation)"],
        "blaNDM": ["all_beta_lactams_except_aztreonam_avibactam"],
        "blaOXA-48": ["carbapenems_modestly"],
        "OmpK35/OmpK36 porin loss": ["all_beta_lactams_when_combined_with_carbapenemase"],
        "16S rRNA methyltransferases (RmtB, ArmA)": ["all_aminoglycosides", "plazomicin"],
    },
    "Abaum": {
        "blaOXA-23/24/40/58 (acquired)": ["carbapenems"],
        "blaOXA-51 + ISAba1 (overexpressed)": ["carbapenems"],
        "AdeABC efflux pump": ["tetracyclines", "tigecycline"],
        "PBP3 modifications": ["beta_lactams"],
        "pmrAB lipid-A modification": ["polymyxins (chromosomal high-level)"],
    },
    "Paer": {
        "MexAB-OprM efflux": ["beta_lactams_FQs_tetracyclines"],
        "MexXY-OprM efflux": ["aminoglycosides"],
        "OprD porin loss": ["meropenem", "imipenem"],
        "blaNDM / blaVIM (MBL)": ["all_beta_lactams_except_aztreonam"],
        "AmpC derepression": ["3G_cephalosporins"],
        "PBP3 mutations": ["ceftolozane-tazobactam (under selection)"],
    },
    "VRE": {
        "vanA operon (Tn1546)": ["vancomycin", "teicoplanin"],
        "vanB operon": ["vancomycin (teicoplanin partial)"],
        "PBP5 of E. faecium": ["ampicillin", "penicillin"],
        "Erm B": ["macrolides", "lincosamides"],
        "cfr methyltransferase": ["linezolid (PhLOPSa cross-resistance)"],
        "aac(6')-Ie-aph(2'')": ["high-level gentamicin (HLAR)"],
    },
    "NGono": {
        "penA mosaic genes": ["ceftriaxone (XDR strains)"],
        "gyrA S91F + parC S87R": ["fluoroquinolones"],
        "23S rRNA A2058G/A2059G": ["azithromycin"],
        "mtrR mutations": ["macrolides", "azoles"],
    },
}


class CheckResistanceInput(BaseModel):
    pathogen: str = Field(..., description="Target pathogen short code")
    drug_class_or_smiles: Optional[str] = Field(
        None,
        description=(
            "Optional: if a SMILES is given, infer drug class via simple "
            "substructure rules. If a class name (e.g. 'beta_lactam', "
            "'macrolide', 'fluoroquinolone'), use directly."
        ),
    )


class ResistanceGene(BaseModel):
    gene: str
    affects: list[str]
    relevance: Literal["high", "medium", "low"]
    note: Optional[str] = None


class CheckResistanceOutput(BaseModel):
    pathogen: str
    drug_class_inferred: Optional[str]
    relevant_genes: list[ResistanceGene]
    summary: str


# Curated drug name → class lookup. Used FIRST before SMARTS structural match,
# since exact-name lookup is more reliable than substructure heuristics.
DRUG_NAME_TO_CLASS: dict[str, str] = {
    # Oxazolidinones
    "linezolid": "oxazolidinone", "tedizolid": "oxazolidinone",
    "sutezolid": "oxazolidinone", "radezolid": "oxazolidinone",
    # Fluoroquinolones
    "ciprofloxacin": "fluoroquinolone", "levofloxacin": "fluoroquinolone",
    "moxifloxacin": "fluoroquinolone", "delafloxacin": "fluoroquinolone",
    "ofloxacin": "fluoroquinolone", "nalidixic acid": "fluoroquinolone",
    # Penicillins
    "penicillin": "penicillin", "penicillin g": "penicillin",
    "penicillin v": "penicillin", "amoxicillin": "penicillin",
    "ampicillin": "penicillin", "piperacillin": "penicillin",
    "ticarcillin": "penicillin", "oxacillin": "penicillin",
    "methicillin": "penicillin", "nafcillin": "penicillin",
    "flucloxacillin": "penicillin",
    # Cephalosporins
    "cefepime": "cephalosporin", "ceftriaxone": "cephalosporin",
    "ceftazidime": "cephalosporin", "cefazolin": "cephalosporin",
    "cefuroxime": "cephalosporin", "cefoxitin": "cephalosporin",
    "ceftaroline": "cephalosporin", "ceftolozane": "cephalosporin",
    "cefiderocol": "cephalosporin",
    # Carbapenems
    "meropenem": "carbapenem", "imipenem": "carbapenem",
    "ertapenem": "carbapenem", "doripenem": "carbapenem",
    "biapenem": "carbapenem",
    # Tetracyclines
    "doxycycline": "tetracycline", "tigecycline": "tetracycline",
    "minocycline": "tetracycline", "tetracycline": "tetracycline",
    "eravacycline": "tetracycline", "omadacycline": "tetracycline",
    # Nitroimidazoles
    "metronidazole": "nitroimidazole", "tinidazole": "nitroimidazole",
    "pretomanid": "nitroimidazole", "delamanid": "nitroimidazole",
    "nitazoxanide": "nitroimidazole",
    # Sulfonamides
    "sulfamethoxazole": "sulfonamide", "sulfadiazine": "sulfonamide",
    "sulfisoxazole": "sulfonamide", "sulfasalazine": "sulfonamide",
    # Diaminopyrimidines
    "trimethoprim": "diaminopyrimidine", "iclaprim": "diaminopyrimidine",
    "pyrimethamine": "diaminopyrimidine",
    # Glycopeptides / lipoglycopeptides
    "vancomycin": "glycopeptide", "teicoplanin": "glycopeptide",
    "telavancin": "glycopeptide", "dalbavancin": "glycopeptide",
    "oritavancin": "glycopeptide",
    # Lipopeptides
    "daptomycin": "lipopeptide",
    # Polymyxins
    "polymyxin b": "polymyxin", "colistin": "polymyxin",
    "polymyxin": "polymyxin",
    # Macrolides
    "erythromycin": "macrolide", "azithromycin": "macrolide",
    "clarithromycin": "macrolide", "roxithromycin": "macrolide",
    "telithromycin": "macrolide", "fidaxomicin": "macrolide",
    # Aminoglycosides
    "gentamicin": "aminoglycoside", "tobramycin": "aminoglycoside",
    "amikacin": "aminoglycoside", "streptomycin": "aminoglycoside",
    "neomycin": "aminoglycoside", "plazomicin": "aminoglycoside",
    "kanamycin": "aminoglycoside",
    # Rifamycins
    "rifampin": "rifamycin", "rifampicin": "rifamycin",
    "rifabutin": "rifamycin", "rifapentine": "rifamycin",
    "rifaximin": "rifamycin",
    # Anti-TB (singletons)
    "isoniazid": "isoniazid", "ethambutol": "ethambutol",
    "pyrazinamide": "pyrazinamide", "bedaquiline": "diarylquinoline",
    "ethionamide": "thioamide", "para-aminosalicylic acid": "salicylate",
    # Lincosamides
    "clindamycin": "lincosamide", "lincomycin": "lincosamide",
    # Streptogramins
    "quinupristin-dalfopristin": "streptogramin",
    # Phenicols
    "chloramphenicol": "phenicol",
    # Pleuromutilins
    "lefamulin": "pleuromutilin", "tiamulin": "pleuromutilin",
    # Azoles (antifungal but mtrR also affects)
    "fluconazole": "triazole", "voriconazole": "triazole",
    "itraconazole": "triazole", "posaconazole": "triazole",
}


def _infer_drug_class(text: str) -> Optional[str]:
    """Map a drug name OR SMILES to a known antibacterial class.

    Strategy (most-reliable first):
      1. Exact name lookup against DRUG_NAME_TO_CLASS (~70 known antibacterials)
      2. RDKit SMARTS substructure match (curated, ordered specific→general)
      3. Generic feature heuristics (peptide bonds → polypeptide)
    """
    text_norm = text.lower().strip()
    if text_norm in DRUG_NAME_TO_CLASS:
        return DRUG_NAME_TO_CLASS[text_norm]

    try:
        from rdkit import Chem
    except ImportError:
        return None
    m = Chem.MolFromSmiles(text)
    if m is None:
        return None

    # Canonicalize for known-drug SMILES match (handles aromatization differences)
    try:
        canonical = Chem.MolToSmiles(m, canonical=True)
        if canonical in _CANONICAL_DRUGS:
            return _CANONICAL_DRUGS[canonical]
    except Exception:
        pass

    # SMARTS patterns — ORDER CRITICAL: most-specific bicyclic/substituted
    # cores BEFORE the generic 4-membered beta-lactam (which would otherwise
    # capture all carbapenems/cephalosporins/penicillins).
    patterns = [
        # ============ Most-specific functional groups first ============
        # Nitroimidazole (metronidazole, pretomanid) — must precede imidazole
        ("nitroimidazole",      "[#6]1=,:[#6]([#7+](=O)[O-])[#7]=,:[#6][#7]1"),
        ("nitroimidazole",      "[$([N+](=O)[O-])]-c1cncn1*"),
        ("nitroimidazole",      "[$([N+](=O)[O-])]-c1ncn(*)c1"),
        ("nitroimidazole",      "[$([N+](=O)[O-])]-c1cnc(*)n1*"),
        # ============ Bicyclic beta-lactams (must precede generic) ============
        # Carbapenem (meropenem, imipenem) — 4-mem β-lactam + 5-mem pyrroline
        ("carbapenem",          "O=C1N2C(=CC2*)C1*"),
        ("carbapenem",          "O=C1[#6][#6]2N1[#6]=,:[#6]2*"),
        ("carbapenem",          "[#7]12[#6](=O)[#6][#6]1[#6]=,:[#6]2"),
        # Penam (penicillin) — 4-mem β-lactam + 5-mem thiazolidine
        ("penicillin",          "S1C(C)(C)C(C(=O)O)N2C(=O)CC12"),
        ("penicillin",          "[#16]1[#6][#6]N2[#6](=O)[#6][#6]12"),
        # Cephem (cephalosporin) — 4-mem β-lactam + 6-mem dihydrothiazine
        # Validated against cefepime, ceftriaxone, ceftazidime canonical SMILES.
        ("cephalosporin",       "[#16]1[#6][#6]=[#6][#7]2[#6](=O)[#6][#6]12"),
        ("cephalosporin",       "S1CC=CN2C(=O)CC12"),
        ("cephalosporin",       "C1C(=O)N2C(=CCSC12)*"),
        # ============ Other specific cores ============
        # Oxazolidinone (linezolid) — 5-mem N-C(=O)-O-C-C
        ("oxazolidinone",       "O=C1OCCN1*"),
        ("oxazolidinone",       "[#6]1[#8][#6](=O)[#7][#6]1"),
        # 4-Quinolone / fluoroquinolone — fused pyridone+benzene+carboxyl
        ("fluoroquinolone",     "O=c1cn(*)c2ccccc2c1C(=O)[#8,#7]"),
        ("fluoroquinolone",     "O=c1cn(*)c2ccccc2c1*"),
        ("fluoroquinolone",     "O=C1C=CN(*)c2ccccc21"),
        ("fluoroquinolone",     "OC(=O)c1cn(*)c2ccccc2c1=O"),
        # 2,4-Diaminopyrimidine (trimethoprim, iclaprim)
        ("diaminopyrimidine",   "[NH2,NH3+]c1ncc(*)c(*)n1"),
        ("diaminopyrimidine",   "[NH2,NH3+]c1nc([NH2,NH3+])ncc1*"),
        ("diaminopyrimidine",   "[#7;H2]c1nc([#7;H2])ncc1"),
        ("diaminopyrimidine",   "Nc1ncc(*)c(N)n1"),
        # Tetracycline — phenol + ortho-carbonyl + extended fused tetracycle
        ("tetracycline",        "Oc1cccc2c1C(=O)C1=C(O)C(*)CC1C2"),
        ("tetracycline",        "[#8]c1cccc2c1[#6](=O)[#6]1=[#6]([#8])[#6](*)[#6][#6]1[#6]2"),
        ("tetracycline",        "Oc1cccc(*)c1C(=O)*"),
        # Sulfonamide — para-aminobenzene-sulfonamide
        ("sulfonamide",         "[NH2]c1ccc([S](=O)(=O)[N])cc1"),
        ("sulfonamide",         "Nc1ccc(S(=O)(=O)N(*))cc1"),
        ("sulfonamide",         "Nc1ccc(S(=O)(=O)Nc2*)cc1"),
        # Aminoglycoside — 2-deoxystreptamine ring
        ("aminoglycoside",      "[NH2,NH3+]C1C[CH]([NH2,NH3+])[CH]([OH])[CH]([OH])[CH]1[OH]"),
        ("aminoglycoside",      "NC1CC(N)C(O)C(O)C1O"),
        ("aminoglycoside",      "OC1CC(N)C(O)CC1N"),
        # Rifamycin — naphthohydroquinone (collapsed ansa)
        ("rifamycin",           "Oc1c(*)c(*)c2C(=O)*c(*)c2c1*"),
        ("rifamycin",           "c1c2c(cc(C)c1O)C(=O)c1c2C(=O)c(C)cc1"),
        # ============ Generic / catch-all patterns LAST ============
        # Macrolide — 14+-atom lactone (≥12 ring members)
        ("macrolide",           "[#6]1[#6][#6][#6][#6][#6][#6][#6][#6][#6][#6][#8][#6](=O)1"),
        # Generic 4-membered beta-lactam (monobactams, etc.) — LAST among lactams
        ("beta_lactam",         "[NX3]1[CX3](=O)[CX4][CX4]1"),
        # Azoles
        ("triazole",            "c1ncnn1*"),
        ("triazole",            "c1ncnn1"),
        ("imidazole",           "c1cnc[nH]1"),
        ("imidazole",           "c1ncn(*)c1"),
    ]
    for cls, smarts in patterns:
        try:
            patt = Chem.MolFromSmarts(smarts)
            if patt is not None and m.HasSubstructMatch(patt):
                return cls
        except Exception:
            continue

    # Fallback: 4+ peptide bonds suggests cyclic peptide (vancomycin, daptomycin)
    try:
        amide_patt = Chem.MolFromSmarts("C(=O)N")
        if amide_patt is not None:
            n_amides = len(m.GetSubstructMatches(amide_patt))
            if n_amides >= 4:
                return "polypeptide"
    except Exception:
        pass
    return None


# Lazily-built canonical SMILES → class lookup. Populated on first call to
# _infer_drug_class via the `_build_canonical_drugs` helper.
_CANONICAL_DRUGS: dict[str, str] = {}


def _build_canonical_drugs() -> None:
    """Pre-canonicalize known drug SMILES once for O(1) lookup."""
    if _CANONICAL_DRUGS:
        return
    try:
        from rdkit import Chem
    except ImportError:
        return
    seeds = {
        # SMILES → class
        "CC(=O)NC[C@H]1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1": "oxazolidinone",  # linezolid
        "O=C(O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O": "fluoroquinolone",     # ciprofloxacin
        "CC1(C)S[C@@H]2[C@H](NC(=O)[C@@H](N)c3ccc(O)cc3)C(=O)N2[C@H]1C(=O)O": "penicillin",  # amoxicillin
        "CC1[C@@H]2CC(=C(N2C1=O)C(=O)O)S[C@H]3CN[C@@H](C3)C(=O)N(C)C": "carbapenem",  # meropenem
        "Cc1ncc([N+](=O)[O-])n1CCO": "nitroimidazole",  # metronidazole
        "COc1cc(Cc2cnc(N)nc2N)cc(OC)c1OC": "diaminopyrimidine",  # trimethoprim
        "Cc1cc(NS(=O)(=O)c2ccc(N)cc2)no1": "sulfonamide",  # sulfamethoxazole
    }
    for smi, cls in seeds.items():
        try:
            mol = Chem.MolFromSmiles(smi)
            if mol is not None:
                _CANONICAL_DRUGS[Chem.MolToSmiles(mol, canonical=True)] = cls
        except Exception:
            continue


# Eagerly populate on module import (best-effort; silent if RDKit absent)
_build_canonical_drugs()


@tool(
    description=(
        "Check which CARD-known resistance genes are likely to compromise a "
        "drug-class against a given pathogen. Used by the agent BEFORE "
        "proposing candidates to avoid scaffolds already defeated by the "
        "pathogen's resistome."
    ),
    category="amr",
    input_model=CheckResistanceInput,
    output_model=CheckResistanceOutput,
    expected_duration_ms=20,
    tags=("amr", "resistance", "card", "core"),
)
def check_resistance_genes(
    pathogen: str,
    drug_class_or_smiles: Optional[str] = None,
) -> CheckResistanceOutput:
    resistome = PATHOGEN_RESISTOME.get(pathogen, {})

    inferred_class = None
    if drug_class_or_smiles:
        # If looks like SMILES (has Cs/atoms/parens), try to infer
        if any(c in drug_class_or_smiles for c in "()[]") or len(drug_class_or_smiles) > 12:
            inferred_class = _infer_drug_class(drug_class_or_smiles)
        else:
            inferred_class = drug_class_or_smiles

    relevant = []
    for gene, affects in resistome.items():
        relevance = "low"
        affects_str = " ".join(affects).lower()
        if inferred_class and inferred_class.lower() in affects_str:
            relevance = "high"
        elif inferred_class and any(part in affects_str for part in inferred_class.lower().split("_")):
            relevance = "medium"
        relevant.append(ResistanceGene(
            gene=gene,
            affects=affects,
            relevance=relevance,
        ))

    relevant.sort(key=lambda g: {"high": 0, "medium": 1, "low": 2}[g.relevance])

    n_high = sum(1 for g in relevant if g.relevance == "high")
    if inferred_class:
        if n_high:
            summary = (
                f"⚠ {pathogen} carries {n_high} resistance gene(s) likely to "
                f"compromise {inferred_class}: {', '.join(g.gene for g in relevant[:n_high])}. "
                f"Consider scaffold-hopping or adding a complementary mechanism."
            )
        else:
            summary = (
                f"✓ {pathogen}'s known resistome does not have a direct match "
                f"for {inferred_class}. Proposed scaffold should retain activity."
            )
    else:
        summary = (
            f"{pathogen} has {len(relevant)} known resistance gene(s) in its "
            f"resistome. Provide a SMILES or drug class for relevance ranking."
        )

    return CheckResistanceOutput(
        pathogen=pathogen,
        drug_class_inferred=inferred_class,
        relevant_genes=relevant,
        summary=summary,
    )
