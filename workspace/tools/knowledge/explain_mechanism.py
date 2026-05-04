"""Generate plain-English mechanism-of-action narrative for a candidate.

Combines drug-class inference (from RDKit substructure) + literature on
the inferred class to produce a paragraph the agent can show in a side panel.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..base import tool


CLASS_MECHANISMS: dict[str, str] = {
    "beta_lactam": (
        "Beta-lactams covalently acylate the active-site serine of bacterial "
        "transpeptidases (penicillin-binding proteins, PBPs), blocking the "
        "final cross-linking step of peptidoglycan biosynthesis. The cell wall "
        "weakens and the bacterium lyses osmotically. Resistance mechanisms "
        "include beta-lactamases (TEM, SHV, CTX-M, KPC, NDM, OXA), PBP "
        "modifications (PBP2a in MRSA, PBP3 in Pseudomonas), and reduced "
        "permeability via porin loss."
    ),
    "cephalosporin": (
        "Cephalosporins are bicyclic beta-lactams with a fused dihydrothiazine "
        "ring. The C7 amide side chain determines pharmacokinetics and beta-"
        "lactamase stability; the C3 substituent tunes spectrum (4G "
        "cephalosporins like cefepime carry a permanent positive charge for "
        "improved gram-negative permeation; ceftaroline's C3 reaches the PBP2a "
        "allosteric site for MRSA activity)."
    ),
    "carbapenem": (
        "Carbapenems are bicyclic beta-lactams with a pyrroline ring (vs "
        "thiazolidine in penicillins). The C2 amidine and C6 hydroxyethyl "
        "groups confer broad PBP affinity and beta-lactamase stability. "
        "Resistance via metallo-beta-lactamases (NDM/VIM/IMP) or class A KPC "
        "is the major clinical concern."
    ),
    "fluoroquinolone": (
        "Fluoroquinolones inhibit DNA gyrase (GyrA-GyrB) and topoisomerase IV "
        "(ParC-ParE) by stabilizing the cleavage complex. Resistance via gyrA "
        "S83L and parC S80I mutations is the dominant mechanism; aac(6')-Ib-cr "
        "acetylates ciprofloxacin secondary amine."
    ),
    "tetracycline": (
        "Tetracyclines bind the 30S ribosomal A-site at h34 of 16S rRNA, "
        "blocking aminoacyl-tRNA delivery. Resistance via tet efflux pumps "
        "(TetA-K), Tet(M)/Tet(O) ribosomal protection, or tetX FAD-monooxygenase. "
        "Tigecycline + eravacycline escape Tet(M)/TetA via bulky C9 side chain."
    ),
    "aminoglycoside": (
        "Aminoglycosides bind 30S A-site at h44 of 16S rRNA, causing mistranslation. "
        "Concentration-dependent killing with significant post-antibiotic effect. "
        "Resistance via AAC/APH/ANT modifying enzymes; rmt 16S methyltransferases "
        "are the universal-resistance frontier."
    ),
    "macrolide": (
        "Macrolides bind 50S A-site at A2058 of 23S rRNA exit tunnel, blocking "
        "peptide elongation. Resistance via Erm methylation of A2058 (MLSb cross-"
        "resistance) or mef efflux pumps."
    ),
    "oxazolidinone": (
        "Oxazolidinones bind 50S A-site at A2451 of 23S rRNA peptidyl transferase "
        "center, blocking 70S initiation complex formation. Distinct from "
        "macrolide/lincosamide pocket (no MLSb cross-resistance). Resistance via "
        "cfr methylation of A2503 (PhLOPSa cross-resistance) or G2576T mutations."
    ),
    "glycopeptide": (
        "Glycopeptides bind D-Ala-D-Ala terminus of lipid II via 5 H-bonds, "
        "blocking transglycosylation. Resistance via vanA (D-Ala-D-Lac substitution, "
        "1 H-bond loss = 1000x affinity drop) or vanB (vancomycin-only). "
        "Lipoglycopeptides (telavancin/oritavancin/dalbavancin) add membrane-"
        "anchoring tail for dual mechanism."
    ),
    "default": (
        "Mechanism not directly inferable from substructure. Likely targets "
        "include cell wall biosynthesis, ribosomal protein synthesis, DNA "
        "replication/transcription, folate metabolism, or membrane integrity. "
        "Use predict_complex_structure + check_resistance_genes to ground the "
        "mechanism more specifically."
    ),
}


class ExplainInput(BaseModel):
    smiles: str = Field(..., description="Candidate SMILES")
    target: Optional[str] = Field(None, description="Optional target hint (PDB ID or pathogen)")


class Explanation(BaseModel):
    smiles: str
    inferred_class: str
    mechanism_narrative: str
    resistance_concerns: list[str] = []


@tool(
    description=(
        "Generate a plain-English mechanism-of-action narrative for a candidate. "
        "Combines drug-class inference (RDKit substructure) with curated class "
        "mechanism descriptions. Used by the Designer's MoA panel."
    ),
    category="knowledge",
    input_model=ExplainInput,
    output_model=Explanation,
    expected_duration_ms=20,
    tags=("knowledge", "moa", "explainability"),
)
def explain_mechanism(smiles: str, target: Optional[str] = None) -> Explanation:
    from ..amr.check_resistance_genes import _infer_drug_class
    cls = _infer_drug_class(smiles) or "default"
    narrative = CLASS_MECHANISMS.get(cls, CLASS_MECHANISMS["default"])

    concerns = []
    if cls == "beta_lactam":
        concerns = ["beta-lactamase hydrolysis", "PBP modifications", "porin loss"]
    elif cls == "cephalosporin":
        concerns = ["ESBL hydrolysis", "AmpC derepression", "OmpK porin loss"]
    elif cls == "carbapenem":
        concerns = ["KPC/MBL/OXA carbapenemases", "OprD porin loss"]
    elif cls == "fluoroquinolone":
        concerns = ["gyrA/parC mutations", "aac(6')-Ib-cr acetylation", "RND efflux pumps"]
    elif cls == "macrolide":
        concerns = ["Erm A2058 methylation (MLSb)", "mef efflux"]
    elif cls == "oxazolidinone":
        concerns = ["cfr A2503 methylation (PhLOPSa)", "23S G2576T mutations"]
    elif cls == "glycopeptide":
        concerns = ["vanA/vanB D-Ala-D-Lac substitution"]

    return Explanation(
        smiles=smiles,
        inferred_class=cls,
        mechanism_narrative=narrative,
        resistance_concerns=concerns,
    )
