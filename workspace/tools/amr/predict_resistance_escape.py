"""Red-team mode: predict the most likely resistance-escape mutations against
a candidate antibiotic.

Used in build-vs-break mode to ask "what would break this drug?" — the agent
proposes mutations the pathogen could acquire, with predicted MIC fold-shift.

This is NOVEL — no existing public tool does pathogen-specific escape prediction
for arbitrary candidate molecules. We hand-curate the high-yield mutations per
pathogen × drug-class, drawn from the elite reasoning slice we trained on.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..base import tool
from .check_resistance_genes import _infer_drug_class


# Curated escape-mutations per (pathogen, drug_class) pair — drawn from
# Stage 2 elite reasoning slice + IDSA AMR 2024 + named papers.
ESCAPE_MAP: dict[tuple[str, str], list[dict]] = {
    ("MRSA", "beta_lactam"): [
        {"target": "PBP2a (mecA)", "mutation": "Glu447Lys",
         "fold_shift": 8, "mechanism": "allosteric site mutation reduces ceftaroline binding"},
        {"target": "femAB", "mutation": "loss-of-function",
         "fold_shift": 4, "mechanism": "altered pentaglycine cross-bridge"},
    ],
    ("MRSA", "cephalosporin"): [
        {"target": "PBP2a", "mutation": "Tyr446Asn",
         "fold_shift": 4, "mechanism": "allosteric pocket reorganization"},
    ],
    ("EColi-CRE", "carbapenem"): [
        {"target": "blaKPC", "mutation": "D179Y (KPC-31)",
         "fold_shift": 16, "mechanism": "loses avibactam binding while retaining ceftazidime hydrolysis"},
        {"target": "OmpK35/36", "mutation": "porin loss",
         "fold_shift": 4, "mechanism": "reduced periplasmic uptake"},
    ],
    ("KpneuCRE", "ceftaz_avi"): [
        {"target": "blaKPC", "mutation": "D179Y (KPC-31)",
         "fold_shift": 16, "mechanism": "see-saw escape from avibactam"},
        {"target": "blaKPC", "mutation": "D178A",
         "fold_shift": 8, "mechanism": "carbamoyl orientation altered"},
    ],
    ("Mtb", "rifamycin"): [
        {"target": "rpoB", "mutation": "Ser531Leu (RRDR)",
         "fold_shift": 256, "mechanism": "high-level RIF resistance, ~70% of clinical R isolates"},
        {"target": "rpoB", "mutation": "His526Tyr",
         "fold_shift": 64, "mechanism": "moderate resistance"},
    ],
    ("Mtb", "isoniazid"): [
        {"target": "katG", "mutation": "Ser315Thr",
         "fold_shift": 100, "mechanism": "loss of INH activation, ~70% of clinical INH-R"},
        {"target": "inhA promoter", "mutation": "C-15T",
         "fold_shift": 5, "mechanism": "target overexpression, low-level"},
    ],
    ("Mtb", "bedaquiline"): [
        {"target": "atpE", "mutation": "D28V",
         "fold_shift": 8, "mechanism": "c-ring binding pocket altered"},
        {"target": "Rv0678", "mutation": "loss-of-function",
         "fold_shift": 4, "mechanism": "MmpS5-MmpL5 efflux derepression (cross-resistance with clofazimine)"},
    ],
    ("VRE", "glycopeptide"): [
        {"target": "vanA operon", "mutation": "(already present)",
         "fold_shift": 1000, "mechanism": "D-Ala-D-Lac substitution"},
        {"target": "ddl loss", "mutation": "with vanD",
         "fold_shift": 100, "mechanism": "alternative resistance lineage"},
    ],
    ("VRE", "oxazolidinone"): [
        {"target": "23S rRNA", "mutation": "G2576T",
         "fold_shift": 8, "mechanism": "linezolid binding pocket"},
        {"target": "cfr methyltransferase", "mutation": "acquisition",
         "fold_shift": 16, "mechanism": "PhLOPSa cross-resistance (chloramphenicol, linc, oxa, pleuro, strepto-A)"},
    ],
    ("Paer", "ceftolozane_tazo"): [
        {"target": "PBP3", "mutation": "M313I",
         "fold_shift": 8, "mechanism": "active-site reorganization"},
        {"target": "PBP3", "mutation": "A452V",
         "fold_shift": 4, "mechanism": "ceftolozane-specific resistance"},
    ],
    ("Abaum", "OXA"): [
        {"target": "PBP3", "mutation": "various",
         "fold_shift": 4, "mechanism": "compensates for OXA-DBO inhibition"},
    ],
    ("NGono", "ceftriaxone"): [
        {"target": "penA", "mutation": "mosaic A501T/G542S",
         "fold_shift": 8, "mechanism": "horizontally acquired from N. perflava"},
    ],
}


class PredictEscapeInput(BaseModel):
    smiles: str = Field(..., description="Candidate SMILES")
    pathogen: str = Field(..., description="Target pathogen short code")


class EscapeMutation(BaseModel):
    target: str = Field(..., description="Gene / protein where mutation lies")
    mutation: str = Field(..., description="Specific mutation (e.g. Ser531Leu)")
    predicted_fold_shift: int = Field(..., description="Predicted MIC fold-shift")
    mechanism: str = Field(..., description="Plain-English mechanism")
    likelihood: Literal["high", "medium", "low"]


class PredictEscapeOutput(BaseModel):
    smiles: str
    pathogen: str
    drug_class: Optional[str]
    escape_mutations: list[EscapeMutation]
    summary: str
    red_team_verdict: Literal["robust", "vulnerable", "highly_vulnerable"]


@tool(
    description=(
        "Red-team mode: predict the most likely resistance-escape mutations "
        "against a candidate antibiotic. Returns mutations the pathogen could "
        "acquire to defeat the drug, with predicted MIC fold-shift and mechanism. "
        "NOVEL — no public tool does this for arbitrary candidate molecules. "
        "Used in build-vs-break workflow."
    ),
    category="amr",
    input_model=PredictEscapeInput,
    output_model=PredictEscapeOutput,
    expected_duration_ms=50,
    tags=("amr", "resistance", "red_team", "novel"),
)
def predict_resistance_escape(smiles: str, pathogen: str) -> PredictEscapeOutput:
    drug_class = _infer_drug_class(smiles)

    candidates = []
    for (path, cls), muts in ESCAPE_MAP.items():
        if path != pathogen:
            continue
        if drug_class is None or cls.lower() in drug_class.lower() or drug_class.lower() in cls.lower():
            for m in muts:
                fold = m["fold_shift"]
                likelihood = "high" if fold >= 16 else ("medium" if fold >= 4 else "low")
                candidates.append(EscapeMutation(
                    target=m["target"],
                    mutation=m["mutation"],
                    predicted_fold_shift=fold,
                    mechanism=m["mechanism"],
                    likelihood=likelihood,
                ))

    candidates.sort(key=lambda m: -m.predicted_fold_shift)

    if not candidates:
        verdict = "robust"
        summary = (
            f"No high-yield escape mutations matched for {pathogen} × "
            f"{drug_class or 'unknown class'}. Either the pathogen has no "
            f"validated escape pathway against this class OR drug-class "
            f"inference failed. Robust by elimination — verify experimentally."
        )
    else:
        max_fold = candidates[0].predicted_fold_shift
        if max_fold >= 64:
            verdict = "highly_vulnerable"
        elif max_fold >= 8:
            verdict = "vulnerable"
        else:
            verdict = "robust"
        top = candidates[0]
        summary = (
            f"{pathogen} could escape via {top.target} {top.mutation} "
            f"({top.predicted_fold_shift}x MIC shift, {top.mechanism}). "
            f"{len(candidates)} total escape pathway(s) identified."
        )

    return PredictEscapeOutput(
        smiles=smiles,
        pathogen=pathogen,
        drug_class=drug_class,
        escape_mutations=candidates,
        summary=summary,
        red_team_verdict=verdict,
    )
