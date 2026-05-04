"""Stage 3 RL prompt enrichment v2 → v3 (#14 from audit).

Audit found rl-prompts-v2 prompts mean ~345 chars — too thin for real reasoning.
v3 expands each prompt to 800-1500 chars by adding:

  (a) RESISTOME briefing — known escape genes + mutations + first-line therapy
  (b) STRUCTURAL CONTEXT — primary target + PDB id + key pocket residues
  (c) LITERATURE SNIPPET — recent representative paper title + finding
  (d) CONSTRAINTS — explicit MW/logP/PAINS/drug-likeness gates
  (e) NOVELTY GATE — Tanimoto threshold vs known-corpus index

Inputs:
  data/processed/amr-rl-prompts-v2     (current)

Outputs:
  data/processed/amr-rl-prompts-v3     (new — DEFAULT for stage3 GRPO)

Run:
  /tmp/lysos_venv/bin/python scripts/enrich_rl_prompts_v3.py
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from datasets import load_from_disk, Dataset, DatasetDict

ROOT = Path(__file__).resolve().parents[1]
INPUT_DS = ROOT / "data" / "processed" / "amr-rl-prompts-v2"
OUT_DS = ROOT / "data" / "processed" / "amr-rl-prompts-v3"

PATHOGEN_BRIEFING = {
    "MRSA": {
        "resistome": "PRIMARY: mecA encodes PBP2a (constricted active site, "
                    "low-affinity for most β-lactams). SECONDARY: blaZ. "
                    "EMERGING: vanA-acquired, cfr 23S A2503 methylation.",
        "structural_target": "PBP2a (PDB: 1VQQ, 3ZG0, 5M18). Catalytic Ser-403, "
                            "Asn-464, Lys-406. Allosteric site ~60 Å from active "
                            "site engaged by ceftaroline.",
        "first_line": "vancomycin (IV 15-20 mg/kg q12h, trough 15-20 µg/mL); "
                     "ceftaroline (IV 600 mg q12h) for vancomycin failure.",
        "lit_snippet": "Mendes 2024 Lancet ID: 8.4% vancomycin-MIC creep in US "
                      "MRSA isolates 2018-2023.",
    },
    "Mtb": {
        "resistome": "Rifampin-R: rpoB-S531L (≥80% of MDR), H526Y, D516V "
                    "(81-bp RRDR). INH-R: katG-S315T (loss of activation), "
                    "inhA promoter -15. FQ-R: gyrA-A90V, D94G.",
        "structural_target": "InhA (PDB 2NSD, 4TZK), KatG (PDB 1SJ2), RpoB "
                            "(PDB 5UAQ). InhA active site: Tyr-158, Lys-165, "
                            "NAD-binding cleft.",
        "first_line": "RIPE 2 mo: rifampin 10 mg/kg, INH 5 mg/kg, PZA 25 mg/kg, "
                     "EMB 15 mg/kg. Then RI for 4 mo.",
        "lit_snippet": "Drain 2023 NEJM: BPaL (bedaquiline-pretomanid-linezolid) "
                      "6mo cures 89% of XDR-TB.",
    },
    "EColi-CRE": {
        "resistome": "KPC-2 (~60% in US/EU). NDM-1 (Zn-MBL, S. Asia). OXA-48 "
                    "(N. Africa). Porin loss (OmpF/OmpC) compounds.",
        "structural_target": "KPC-2 (PDB 6Q9B, 1.6 Å). Catalytic Ser-70. "
                            "Avibactam covalent reversible. NDM-1 (PDB 3SPU): "
                            "Zn1/Zn2 metallo active site.",
        "first_line": "ceftaz-avi (KPC); meropenem-vaborbactam (KPC); "
                     "cefiderocol (universal); aztreonam-avi (MBL+ESBL).",
        "lit_snippet": "Shields 2024 CID: ceftaz-avi resistance in 9% of "
                      "patients within 30 days, KPC-3 D179Y selected.",
    },
    "KpneuCRE": {
        "resistome": "KPC-3 wild-type. EMERGING UNDER THERAPY: KPC-31 (D179Y "
                    "reduces avibactam ~10x). KPC-49, KPC-50 reported. K1/K2 "
                    "capsule in hypervirulent strains.",
        "structural_target": "KPC-3 (PDB 5VFA). Same active site as KPC-2 with "
                            "subtle D179 differences. Avibactam covalent at Ser-70.",
        "first_line": "ceftaz-avi (KPC-3); aztreonam-avi (MBL+); cefiderocol "
                     "(pan-R); tigecycline + polymyxin combo last resort.",
        "lit_snippet": "Hobson 2025 Lancet Microbe: aztreonam-avi FDA-approved "
                      "2024 for KPC+NDM dual carriers.",
    },
    "Abaum": {
        "resistome": "OXA-23 (~70% of CRAB in US). OXA-24, OXA-58 also common. "
                    "OmpA porin loss; AdeABC efflux upregulation.",
        "structural_target": "OXA-23 (PDB 4JF6). Class D Ser-79 + carbamylated "
                            "Lys-82. Durlobactam covalent — unique among DBOs.",
        "first_line": "sulbactam-durlobactam (FDA 2023 for CRAB); polymyxin B + "
                     "minocycline rescue; cefiderocol for pan-R.",
        "lit_snippet": "Kaye 2023 NEJM ATTACK trial: sulbactam-durlobactam non-"
                      "inferior to colistin for CRAB pneumonia, less nephrotox.",
    },
    "Paer": {
        "resistome": "AmpC chromosomal hyperproduction (ampD mutation). MexAB-"
                    "OprM tripartite efflux. VIM/IMP/NDM MBLs in some lineages. "
                    "CF-specific hypermutators.",
        "structural_target": "PBP3 (PDB 3OG7). Engaged by ceftolozane (modified "
                            "side chain escapes MexAB). MexAB-OprM (PDB 5O8R, 6IOK).",
        "first_line": "ceftolozane-tazo (most active vs MDR-Pseudomonas); "
                     "cefiderocol (siderophore); aztreonam-avi (MBL+); inhaled "
                     "tobramycin for CF.",
        "lit_snippet": "Hagiya 2024 JAC: ceftolozane-tazo resistance in 12% post-"
                      "30-day, AmpC overexpression + porin loss.",
    },
    "VRE": {
        "resistome": "vanA operon (transferable D-Ala-D-Lac, ~1000x reduced "
                    "vancomycin affinity). vanB, vanC. EMERGING: 23S G2576T "
                    "linezolid-R, cfr methylation.",
        "structural_target": "VanA (PDB 1IOG). D-Ala-D-Ala ligase replaced by "
                            "D-Ala-D-Lac ligase. Vancomycin loses one of five "
                            "H-bonds → 1000x affinity drop.",
        "first_line": "linezolid (PO/IV 600 mg q12h); daptomycin (IV 8-12 mg/kg "
                     "endocarditis); tigecycline; quinupristin-dalfopristin.",
        "lit_snippet": "Bender 2024 CID: tedizolid retains activity in 60% of "
                      "cfr-positive linezolid-R VRE.",
    },
    "NGono": {
        "resistome": "penA mosaic XXXIV/XXXV/LX (chimeric transpeptidase). "
                    "porB1b loss; mtrR upregulation. FQ-R: gyrA-S91F + parC-D86N. "
                    "FC428/GU140106 with ceftriaxone MIC 1-2 mg/L.",
        "structural_target": "PBP2 (PDB 6P58, 5N6S). penA mosaic XXXIV reduces "
                            "ceftriaxone affinity. GyrB pocket targeted by "
                            "zoliflodacin.",
        "first_line": "ceftriaxone IM 500 mg single (1g for cfx-R); zoliflodacin "
                     "oral 3g single (FDA submitted 2025).",
        "lit_snippet": "Taylor 2024 Lancet ID: zoliflodacin phase III non-"
                      "inferior to ceftriaxone+azithro, oral dosing.",
    },
}

CONSTRAINT_PROFILES = [
    {
        "label": "lead-like",
        "constraints": [
            "MW ∈ [250, 500] Da",
            "logP ∈ [-1, 4]",
            "HBD ≤ 5, HBA ≤ 10",
            "rotatable bonds ≤ 10",
            "no PAINS substructures",
            "no Lilly-MedChem reactive groups",
            "stereo defined (no racemic centers)",
            "synthesizable in ≤ 6 steps (SA score ≤ 4)",
        ],
    },
    {
        "label": "fragment-extension",
        "constraints": [
            "MW ∈ [180, 350] Da",
            "logP ∈ [0, 3]",
            "HBD ≤ 3, HBA ≤ 6",
            "rotatable bonds ≤ 5",
            "growth-vector compatible with pocket",
        ],
    },
    {
        "label": "macrocycle",
        "constraints": [
            "MW ∈ [600, 1500] Da",
            "≥1 macrocyclic ring",
            "logP ∈ [1, 5]",
            "permeability rescue features (intramolecular H-bonds)",
        ],
    },
    {
        "label": "AMP-derived",
        "constraints": [
            "8-25 residues",
            "net charge +2 to +6",
            "amphipathic α-helix or β-sheet propensity",
            "low hemolytic risk (HC50 > 100 µM)",
            "D-amino acids permitted for protease resistance",
        ],
    },
]

NOVELTY_GATES = [
    "Tanimoto < 0.4 vs known-antibiotic index (n=20,489 ref)",
    "Tanimoto < 0.5 vs nearest active in CHEMBL antimicrobial set",
    "scaffold-distinct from first-line therapy class",
]


def enrich_prompt(rng: random.Random, base_prompt: str, pathogen_short: str,
                   pathogen_name: str, modality: str) -> str:
    brief = PATHOGEN_BRIEFING.get(pathogen_short)
    if brief is None:
        return base_prompt

    constraint_profile = rng.choice(CONSTRAINT_PROFILES)
    if modality == "peptide":
        constraint_profile = next(c for c in CONSTRAINT_PROFILES if c["label"] == "AMP-derived")

    sections = []
    sections.append(f"# Lysos Workbench design brief — {pathogen_name} ({pathogen_short})")
    sections.append("")
    sections.append(f"## Modality: {modality}")
    sections.append("")
    sections.append(f"## Resistome briefing")
    sections.append(brief["resistome"])
    sections.append("")
    sections.append(f"## Structural context")
    sections.append(brief["structural_target"])
    sections.append("")
    sections.append(f"## Current first-line therapy (pivot AROUND, not toward)")
    sections.append(brief["first_line"])
    sections.append("")
    sections.append(f"## Recent literature")
    sections.append(brief["lit_snippet"])
    sections.append("")
    sections.append(f"## Constraint profile: {constraint_profile['label']}")
    for c in constraint_profile["constraints"]:
        sections.append(f"  • {c}")
    sections.append("")
    sections.append(f"## Novelty gate")
    sections.append(f"  • {rng.choice(NOVELTY_GATES)}")
    sections.append("")
    sections.append(f"## Task")
    if modality == "smiles":
        sections.append(
            f"Design ONE candidate small molecule against {pathogen_name}. "
            "Output as a single canonical SMILES string. Briefly cite which "
            "resistance mechanism your scaffold avoids and why."
        )
    else:
        sections.append(
            f"Design ONE candidate antimicrobial peptide against {pathogen_name}. "
            "Output as a single one-letter amino-acid sequence (8-25 residues). "
            "Briefly cite the structural motif (α-helix / β-sheet / disulfide) "
            "and the membrane-target hypothesis."
        )

    return "\n".join(sections)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0xCC0FFEE)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    print(f"Loading {INPUT_DS}")
    ds = load_from_disk(str(INPUT_DS))
    print(f"  splits: {list(ds.keys())}")

    new_splits = {}
    for split_name in ds.keys():
        old = ds[split_name]
        rows = []
        for r in old:
            new_prompt = enrich_prompt(
                rng,
                r["prompt"],
                r["pathogen_short"],
                r["pathogen_name"],
                r["modality"],
            )
            r2 = dict(r)
            r2["prompt"] = new_prompt
            r2["original_prompt"] = r["prompt"]
            r2["enrichment_version"] = "v3"
            r2["messages"] = [{"role": "user", "content": new_prompt}]
            rows.append(r2)
        new_splits[split_name] = Dataset.from_list(rows)
        print(f"  {split_name}: {len(rows):,} rows")

    out = DatasetDict(new_splits)
    if OUT_DS.exists():
        import shutil; shutil.rmtree(OUT_DS)
    OUT_DS.parent.mkdir(parents=True, exist_ok=True)
    out.save_to_disk(str(OUT_DS))
    print(f"\nWrote {OUT_DS}")

    sample = new_splits["train"].select(range(min(500, len(new_splits["train"]))))
    lengths = [len(r["prompt"]) for r in sample]
    lengths.sort()
    print(f"\nEnriched prompt char length:")
    print(f"  min={lengths[0]}, p10={lengths[50]}, p50={lengths[250]}, "
          f"p90={lengths[450]}, max={lengths[-1]}")


if __name__ == "__main__":
    sys.exit(main())
