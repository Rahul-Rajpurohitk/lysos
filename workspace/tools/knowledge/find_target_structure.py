"""Look up canonical PDB target structure(s) for a pathogen.

Used by the Designer agent before calling propose_pocket_aware or
predict_complex_structure — gives the right PDB ID to dock against.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..base import tool


# Canonical pathogen-target → PDB structure(s).
# Curated from RCSB + literature, with structure quality + ligand notes.
PATHOGEN_TARGETS: dict[str, list[dict]] = {
    "MRSA": [
        {"pdb_id": "1VQQ", "name": "PBP2a", "uniprot": "P07944",
         "resolution_a": 1.84, "ligand_present": True,
         "note": "MRSA mecA gene product; allosteric site target for ceftaroline"},
        {"pdb_id": "5HLB", "name": "PBP2a (closed)", "uniprot": "P07944",
         "resolution_a": 2.30, "ligand_present": False,
         "note": "Closed conformation — substrate-blocked"},
    ],
    "Mtb": [
        {"pdb_id": "2X22", "name": "InhA (enoyl-ACP reductase)", "uniprot": "P9WGR1",
         "resolution_a": 1.80, "ligand_present": True,
         "note": "Isoniazid target; mycolic acid biosynthesis"},
        {"pdb_id": "5UH8", "name": "DprE1 (decaprenylphosphoryl-β-D-ribose 2′-oxidase)", "uniprot": "P9WJF1",
         "resolution_a": 2.10, "ligand_present": True,
         "note": "Vulnerability target — BTZ/PBTZ class"},
        {"pdb_id": "4V1F", "name": "ATP synthase c-ring", "uniprot": "P9WPS1",
         "resolution_a": 3.50, "ligand_present": True,
         "note": "Bedaquiline target; persister-killing pathway"},
    ],
    "EColi-CRE": [
        {"pdb_id": "5UL8", "name": "PBP3 (FtsI)", "uniprot": "P0AD68",
         "resolution_a": 2.36, "ligand_present": True,
         "note": "Cephalosporin target; PBP3 inserts emerging in NDM-7 strains"},
    ],
    "KpneuCRE": [
        {"pdb_id": "6QWN", "name": "KPC-2 carbapenemase", "uniprot": "Q9F663",
         "resolution_a": 1.85, "ligand_present": True,
         "note": "Class A serine BL; D179Y = KPC-31 escape"},
        {"pdb_id": "5KSS", "name": "OXA-48 carbapenemase", "uniprot": "Q6XEC0",
         "resolution_a": 1.90, "ligand_present": True,
         "note": "Class D serine BL; weak carbapenemase, stealth phenotype"},
    ],
    "Abaum": [
        {"pdb_id": "7M4F", "name": "OXA-23 carbapenemase", "uniprot": "Q7BSF1",
         "resolution_a": 1.95, "ligand_present": True,
         "note": "Acquired class D BL; sulbactam-durlobactam target"},
    ],
    "Paer": [
        {"pdb_id": "5DPX", "name": "PBP3", "uniprot": "Q9HVM6",
         "resolution_a": 2.41, "ligand_present": True,
         "note": "Ceftolozane PBP3 target"},
        {"pdb_id": "6V69", "name": "MexB (RND efflux)", "uniprot": "P52002",
         "resolution_a": 3.30, "ligand_present": False,
         "note": "MexAB-OprM efflux pump - primary MDR mechanism"},
    ],
    "VRE": [
        {"pdb_id": "1MWS", "name": "VanA D-Ala-D-Lac ligase", "uniprot": "Q06239",
         "resolution_a": 2.40, "ligand_present": True,
         "note": "vanA operon resistance gene; Tn1546 transposon"},
    ],
    "NGono": [
        {"pdb_id": "5XFT", "name": "PBP2 (penA)", "uniprot": "P08149",
         "resolution_a": 2.40, "ligand_present": True,
         "note": "penA mosaic genes drive ceftriaxone-R XDR strains"},
    ],
}


class FindTargetInput(BaseModel):
    pathogen: str = Field(..., description="Pathogen short code")


class TargetStructure(BaseModel):
    pdb_id: str
    name: str
    uniprot: Optional[str] = None
    resolution_a: float
    ligand_present: bool
    note: str


class FindTargetOutput(BaseModel):
    pathogen: str
    targets: list[TargetStructure]
    primary_target: Optional[TargetStructure] = None
    interpretation: str


@tool(
    description=(
        "Look up canonical PDB target structure(s) for a pathogen. Returns "
        "PDB IDs, resolution, ligand presence, and clinical context. The "
        "Designer agent calls this before propose_pocket_aware / "
        "predict_complex_structure / dock_against_target."
    ),
    category="knowledge",
    input_model=FindTargetInput,
    output_model=FindTargetOutput,
    expected_duration_ms=10,
    tags=("knowledge", "structures", "pdb", "core"),
)
def find_target_structure(pathogen: str) -> FindTargetOutput:
    raw = PATHOGEN_TARGETS.get(pathogen, [])
    targets = [TargetStructure(**t) for t in raw]
    primary = targets[0] if targets else None
    if primary:
        interp = (
            f"{pathogen} primary target: {primary.name} (PDB {primary.pdb_id}, "
            f"{primary.resolution_a} Å). {primary.note}"
        )
    else:
        interp = f"No curated target structure for {pathogen}."
    return FindTargetOutput(
        pathogen=pathogen, targets=targets, primary_target=primary,
        interpretation=interp,
    )
