"""Predict ADMET (Absorption, Distribution, Metabolism, Excretion, Toxicity)
properties from RDKit descriptors. Quick heuristic rules + Lipinski-style
flags. Used by the Critic agent to flag pharmacokinetic concerns early.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field
from ..base import tool


class AdmetInput(BaseModel):
    smiles: str = Field(..., description="Candidate SMILES")


class AdmetProfile(BaseModel):
    smiles: str
    mw: float
    logp: float
    tpsa: float
    hbd: int
    hba: int
    rotatable_bonds: int
    aromatic_rings: int
    lipinski_violations: int
    veber_pass: bool
    bbb_likely: Literal["yes", "no", "borderline"]
    bioavailability_score: float = Field(..., description="Veber + Lipinski composite [0,1]")
    cyp_3a4_substrate_likely: bool
    metabolic_concerns: list[str]
    interpretation: str


@tool(
    description=(
        "Predict ADMET properties (MW, logP, TPSA, HBD/HBA, rotatable bonds, "
        "Lipinski + Veber pass, BBB penetration likelihood, bioavailability "
        "composite, CYP 3A4 substrate flag, metabolic liability flags) from "
        "RDKit descriptors."
    ),
    category="scoring",
    input_model=AdmetInput,
    output_model=AdmetProfile,
    expected_duration_ms=80,
    tags=("scoring", "admet", "core"),
)
def predict_admet(smiles: str) -> AdmetProfile:
    from rdkit import Chem
    from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return AdmetProfile(
            smiles=smiles, mw=0, logp=0, tpsa=0, hbd=0, hba=0,
            rotatable_bonds=0, aromatic_rings=0, lipinski_violations=4,
            veber_pass=False, bbb_likely="no", bioavailability_score=0.0,
            cyp_3a4_substrate_likely=False, metabolic_concerns=["unparseable SMILES"],
            interpretation="SMILES failed RDKit parsing.",
        )

    mw = Descriptors.MolWt(mol)
    logp = Descriptors.MolLogP(mol)
    tpsa = Descriptors.TPSA(mol)
    hbd = Lipinski.NumHDonors(mol)
    hba = Lipinski.NumHAcceptors(mol)
    rotbonds = Lipinski.NumRotatableBonds(mol)
    aromatic = rdMolDescriptors.CalcNumAromaticRings(mol)

    lipinski = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    veber = rotbonds <= 10 and tpsa <= 140

    if tpsa < 70 and 1 < logp < 4 and mw < 450:
        bbb = "yes"
    elif tpsa > 90 or logp > 5 or mw > 500:
        bbb = "no"
    else:
        bbb = "borderline"

    bio_score = (1.0 - min(lipinski / 4, 1.0)) * 0.6 + (1.0 if veber else 0.0) * 0.4

    cyp_3a4 = mw > 300 and logp > 2.5 and aromatic >= 1

    concerns = []
    if mw > 500: concerns.append(f"MW {mw:.0f} > 500 (Lipinski)")
    if logp > 5: concerns.append(f"logP {logp:.1f} > 5 (lipophilicity)")
    if rotbonds > 10: concerns.append(f"rotatable bonds {rotbonds} > 10 (Veber)")
    if tpsa > 140: concerns.append(f"TPSA {tpsa:.0f} > 140 (oral absorption risk)")
    if aromatic >= 4: concerns.append(f"{aromatic} aromatic rings (planarity / promiscuity risk)")

    interp = (
        f"Bioavailability {bio_score:.2f}; Lipinski violations {lipinski}/4. "
        f"BBB penetration: {bbb}. "
    )
    if not veber:
        interp += "Fails Veber rule. "
    if concerns:
        interp += f"{len(concerns)} concern(s) flagged."

    return AdmetProfile(
        smiles=smiles, mw=mw, logp=logp, tpsa=tpsa, hbd=hbd, hba=hba,
        rotatable_bonds=rotbonds, aromatic_rings=aromatic,
        lipinski_violations=lipinski, veber_pass=veber,
        bbb_likely=bbb, bioavailability_score=round(bio_score, 3),
        cyp_3a4_substrate_likely=cyp_3a4,
        metabolic_concerns=concerns, interpretation=interp,
    )
