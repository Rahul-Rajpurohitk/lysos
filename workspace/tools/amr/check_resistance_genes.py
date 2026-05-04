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


def _infer_drug_class(smiles: str) -> str | None:
    """Cheap RDKit substructure → class mapping for common antibiotic scaffolds."""
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles(smiles)
        if m is None:
            return None
        # SMARTS for common antibacterial cores
        patterns = {
            "beta_lactam": "[NX3]1[CX3](=O)[CX4][CX4]1",
            "carbapenem": "[NX3]1[CX3](=O)[CX4][CX3]=[CX3]1",
            "cephalosporin": "[NX3]1[CX3](=O)[CX4][CX3]2[SX2][CX4][CX3](=[CX3])[CX3]12",
            "fluoroquinolone": "c1cc2c(cc1F)c(=O)c(C(=O)O)cn2",
            "tetracycline": "C12C(O)C(=O)CC(N(C)C)C1Cc1cccc(O)c1C2=O",
            "aminoglycoside": "[NX3][CX4]1[CX4][CX4]([NX3])[CX4][CX4]1[NX3]",
            "macrolide": "[CX4]1[OX2][CX3](=O)[CX4]",
            "oxazolidinone": "[CX4]1[OX2][CX3](=O)[NX3]1",
            "glycopeptide": "[NX3][CX4]([CX3](=O)[NX3])[CX4]",
        }
        for cls, smarts in patterns.items():
            patt = Chem.MolFromSmarts(smarts)
            if patt is not None and m.HasSubstructMatch(patt):
                return cls
    except ImportError:
        return None
    return None


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
