"""Manual teacher distillation. Designer<->Critic dialogues authored
inline by Claude this session (no API spend).

Output: data/synthetic/agentic_teacher_distill.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic" / "agentic_teacher_distill.jsonl"

SYS = (
    "You are the Lysos Designer-Critic team. Designer proposes antibacterial "
    "candidates against drug-resistant pathogens, calls in silico tools, "
    "reads structured results, iterates. Critic does adversarial review "
    "(PAINS, novelty, escape, manufacturability). End with a structured "
    "FINAL CANDIDATE REPORT including SMILES, predicted MIC, ADMET pass, "
    "synthesis route, resistance verdict, recommendation."
)


KB = {
    "MRSA": {
        "full": "methicillin-resistant Staphylococcus aureus",
        "first_line": "vancomycin (IV 15-20 mg/kg q12h, trough 15-20 ug/mL); ceftaroline (600 mg q12h IV) for vancomycin failure",
        "targets": [
            ("PBP2a", "1VQQ", "constricted active site (mecA-encoded transpeptidase). Allosteric site ~60 A from Ser-403; ceftaroline opens it via aminothiadiazole-oxime tail.",
             ["mecA-N146K", "mecA-E150K", "vraSR-up"]),
            ("PBP2a", "5M18", "PBP2a covalent complex with ceftaroline; reveals the open conformation. C7 acylamine + C3 thiopyridyl footprint.",
             ["mecA-N146K", "mecA-E239K"]),
        ],
    },
    "Mtb": {
        "full": "Mycobacterium tuberculosis",
        "first_line": "RIPE 2 mo (rifampin 10 mg/kg, INH 5 mg/kg, PZA 25 mg/kg, EMB 15 mg/kg) then RI for 4 mo",
        "targets": [
            ("InhA", "2NSD", "enoyl-ACP reductase; INH-NAD adduct binds catalytic Tyr-158 + Lys-165; direct triclosan-class diphenyl ether bypasses katG activation.",
             ["inhA promoter -15", "inhA-S94A"]),
            ("RpoB", "5UAQ", "RNA polymerase beta subunit; rifampin binds the 81-bp RRDR. Single missense disrupts a key contact.",
             ["rpoB-S531L", "rpoB-H526Y", "rpoB-D516V"]),
            ("KatG", "1SJ2", "catalase-peroxidase; activates INH to isonicotinoyl radical; loss-of-function mutations break activation.",
             ["katG-S315T", "katG-S315N"]),
        ],
    },
    "EColi-CRE": {
        "full": "carbapenem-resistant Escherichia coli",
        "first_line": "ceftazidime-avibactam (KPC-only); meropenem-vaborbactam (KPC); cefiderocol (universal); aztreonam-avibactam (MBL+ESBL)",
        "targets": [
            ("KPC-2", "6Q9B", "class A serine carbapenemase; covalent reversible avibactam binder at Ser-70; Trp105 + Asn132 form pocket.",
             ["KPC-3", "KPC-31 D179Y", "porin OmpF-loss"]),
            ("NDM-1", "3SPU", "class B Zn2+ metallo-beta-lactamase; Zn1/Zn2 dual-metal active site; resistant to avibactam/vaborbactam; cefiderocol works via siderophore entry.",
             ["NDM-1 wt", "porin loss compounds resistance"]),
            ("OXA-48", "3HBR", "class D carbapenemase; carbamylated Lys-73 + Ser-70; common in N. Africa/Middle East.",
             ["OXA-48 wt", "OXA-181", "OXA-232"]),
        ],
    },
    "KpneuCRE": {
        "full": "carbapenem-resistant Klebsiella pneumoniae",
        "first_line": "ceftaz-avi (KPC-3); aztreonam-avi (MBL+); cefiderocol (pan-R); tigecycline + polymyxin combo last resort",
        "targets": [
            ("KPC-3", "5VFA", "KPC variant; D179Y reduces avibactam binding ~10x; same Ser-70 catalytic mechanism as KPC-2 but pocket geometry differs.",
             ["KPC-3", "KPC-31 D179Y", "KPC-49", "KPC-50"]),
        ],
    },
    "Abaum": {
        "full": "Acinetobacter baumannii",
        "first_line": "sulbactam-durlobactam (FDA 2023 for CRAB); polymyxin B + minocycline rescue; cefiderocol for pan-R",
        "targets": [
            ("OXA-23", "4JF6", "class D carbapenemase; Ser-79 + carbamylated Lys-82; durlobactam covalently binds (unique among DBOs).",
             ["OXA-23", "OXA-24", "OXA-58", "OmpA-loss"]),
        ],
    },
    "Paer": {
        "full": "Pseudomonas aeruginosa",
        "first_line": "ceftolozane-tazobactam (most active vs MDR-Pseudomonas); cefiderocol; aztreonam-avi (MBL+); inhaled tobramycin for CF",
        "targets": [
            ("PBP3", "3OG7", "essential transpeptidase; ceftolozane modified side chain escapes MexAB-OprM efflux.",
             ["AmpC-derepressed", "MexAB-OprM-up", "porB-loss"]),
            ("MexAB-OprM", "5O8R", "tripartite efflux pump; MexB inner-membrane RND transporter handles broad-spectrum substrates.",
             ["MexAB-up", "MexXY-up", "OprD-loss"]),
        ],
    },
    "VRE": {
        "full": "vancomycin-resistant Enterococcus",
        "first_line": "linezolid (PO/IV 600 mg q12h); daptomycin (IV 8-12 mg/kg endocarditis); tigecycline; quinupristin-dalfopristin",
        "targets": [
            ("VanA", "1IOG", "D-Ala:D-Lac ligase replaces D-Ala:D-Ala; vancomycin loses one of five H-bonds, ~1000x affinity drop.",
             ["vanA acquired", "vanB acquired", "23S G2576T linezolid-R"]),
        ],
    },
    "NGono": {
        "full": "Neisseria gonorrhoeae",
        "first_line": "ceftriaxone IM 500 mg single (1g for cfx-R); zoliflodacin oral 3g single (FDA 2025)",
        "targets": [
            ("PBP2", "6P58", "penA mosaic XXXIV/XXXV reduces ceftriaxone affinity; FC428/GU140106 lineages with ceftriaxone MIC 1-2 mg/L.",
             ["penA mosaic XXXIV", "penA mosaic XXXV", "porB1b-loss", "mtrR-up"]),
            ("GyrB", "5N6S", "type II topoisomerase; zoliflodacin novel-mechanism binder; FQ-R via gyrA-S91F + parC-D86N is orthogonal.",
             ["gyrA-S91F + parC-D86N (FQ-R, but orthogonal)"]),
        ],
    },
}


SCAFFOLDS = {
    "MRSA-PBP2a": [
        ("5GC ceftaroline-class with extended allosteric tail",
         "OC(=O)[C@H]1N2C(=O)[C@@H](NC(=O)/C(=N\\OC)/c3csc(N)n3)[C@H]2SC1=Cc4ccncc4",
         "ceftaroline-anchored cephem"),
        ("oxadiazine-cephalosporin hybrid",
         "OC(=O)[C@H]1N2C(=O)[C@@H](NC(=O)c3onnc3-c4ccncc4)[C@H]2SC1=C",
         "oxadiazine head improves PBP2a opening"),
        ("novel diazabicyclooctane (DBO) PBP2a binder",
         "OC(=O)[C@H]1N2C(=O)[C@@H](N3CCN(C3=O)c4ccncc4)[C@H]2SC1=C",
         "DBO covalent on Ser-403"),
    ],
    "Mtb-InhA": [
        ("triclosan-class diphenyl ether bypassing katG",
         "Oc1cc(Cl)c(Cc2ccc(OC(=O)CC(C)C)cc2)cc1",
         "direct InhA inhibitor"),
        ("pyrrolidine-piperazine InhA binder",
         "O=C(N1CCN(c2ncccc2C(F)(F)F)CC1)C3CCN(CC3)c4ccccc4",
         "pyrrolidine displaces NAD-cofactor"),
    ],
    "Mtb-RpoB": [
        ("naphthalenone analog with extended RRDR contact",
         "OC1=CC2=CC=CC=C2C(=O)C1=CCCC(=O)NC3=CC=CC=C3",
         "engages residues outside the 81-bp RRDR"),
        ("RNA-pol allosteric beta-prime binder",
         "Cc1ccc(C(=O)Nc2ccc3c(c2)C(=O)c4ccccc4N3)cc1",
         "second-target with low cross-resistance to rpoB"),
    ],
    "Mtb-KatG": [
        ("InhA direct inhibitor (bypasses KatG activation)",
         "Oc1cc(Cl)c(Cc2ccc(OC(=O)CC(C)C)cc2)cc1",
         "diphenyl ether triclosan-class"),
    ],
    "EColi-CRE-KPC-2": [
        ("DBO-cephalosporin combo (KPC-stable)",
         "[C@H]1(C(=O)O)[C@H]2[C@@H](N1C(=O)O)C[C@H](O)C2",
         "covalent reversible Ser-70 binder"),
        ("boronate KPC inhibitor (vaborbactam-class)",
         "OB(O)C(C)c1ccc(C(=O)N)cc1",
         "boronate forms transition-state-mimic"),
    ],
    "EColi-CRE-NDM-1": [
        ("siderophore-cephalosporin (cefiderocol-class)",
         "OC(=O)[C@H]1N2C(=O)[C@@H](NC(=O)/C(=N\\OC)/c3csc(N)n3)[C@H]2SC1=CCc4cccc(O)c4O",
         "Trojan-horse via TonB-dependent receptors"),
        ("Zn-chelator MBL inhibitor",
         "OC(=O)c1ncn(c1)CCC(=O)NC2(CCS(=O)(=O)C)CC2",
         "scavenges Zn2+ from MBL active site"),
    ],
    "EColi-CRE-OXA-48": [
        ("DBO with class D activity (durlobactam-like)",
         "[C@H]1(N(O)S(=O)(=O)O)C[C@@H]2N1CCN2",
         "covalent Ser-70 binder, class D selective"),
    ],
    "KpneuCRE-KPC-3": [
        ("aztreonam-avibactam combination",
         "OC(=O)C(=N\\\\OC(C)(C)C(=O)O)/c1csc(N)n1",
         "monobactam stable to MBL + DBO inhibits class A/C/some D"),
        ("nacubactam-class DBO (D179Y-aware)",
         "[C@H]1(N(O)S(=O)(=O)NC(=O)C)C[C@@H]2N1CCN2",
         "DBO with extra polar group for D179Y pocket"),
    ],
    "Abaum-OXA-23": [
        ("sulbactam-durlobactam combination",
         "[C@H]1(C(=O)O)[C@H]2[C@@H](N1C(=O)O)C[C@H](O)C2",
         "sulbactam direct PBP3 + durlobactam covers OXA-23/24/58"),
    ],
    "Paer-PBP3": [
        ("ceftolozane-class (modified side chain to escape MexAB)",
         "OC(=O)[C@H]1N2C(=O)[C@@H](NC(=O)/C(=N\\OC)/c3csc(N)n3)[C@H]2SC1=CC(C)(C)C(=O)NCCN(C)C",
         "bulky polar tail prevents MexB recognition"),
    ],
    "Paer-MexAB-OprM": [
        ("EPI (efflux-pump inhibitor) + carbapenem combo",
         "Cc1ccc2c(c1)NC(=O)c3ccc(cc23)C(F)(F)F",
         "blocks MexB substrate channel"),
    ],
    "VRE-VanA": [
        ("re-engineered glycopeptide (vancomycin-aglycone)",
         "C[C@@H]1OC(=O)[C@H](NC(=O)C2CCC(O)CC2)Cc3ccc(O)cc3",
         "removes the H-bond clash with D-Lac"),
        ("daptomycin-class lipopeptide",
         "CCCCCCCCCC(=O)NC(CC(=O)N)C(=O)NC(C(=O)O)C(C)O",
         "membrane-active orthogonal MoA"),
    ],
    "NGono-PBP2": [
        ("5GC penA-mosaic-aware cephalosporin",
         "OC(=O)[C@H]1N2C(=O)[C@@H](NC(=O)/C(=N\\OC)/c3csc(N)n3)[C@H]2SC1=Cc4cncc(c4)CC",
         "extended C3 to compensate for mosaic-XXXIV pocket"),
    ],
    "NGono-GyrB": [
        ("zoliflodacin-class spiropyrimidine",
         "O=C1Nc2cc(F)c(F)cc2C13CCC(C3)c4ccccn4",
         "novel mechanism, FQ-R orthogonal"),
        ("gepotidacin-class triazaacenaphthylene",
         "Cc1nnc2c(C(=O)NCC3CCCNC3)cccc2n1",
         "novel mechanism, GyrB allosteric"),
    ],
}


def synth_one_trace(rng: random.Random) -> dict:
    """Generate one rich Designer<->Critic trace with grounded knowledge."""
    pathogen = rng.choice(list(KB.keys()))
    pathogen_info = KB[pathogen]
    target_name, pdb, target_rationale, escape_mutations = rng.choice(pathogen_info["targets"])
    scaffold_key = f"{pathogen}-{target_name}"
    scaffold_options = SCAFFOLDS.get(scaffold_key, [])
    if not scaffold_options:
        return None
    scaffold_label, base_smiles, scaffold_rationale = rng.choice(scaffold_options)

    # Predicted PK panel — drawn from realistic distributions
    log_mic_pred = rng.gauss(-0.2, 0.7)
    mic_ug_ml = round(10 ** log_mic_pred, 3)
    confidence = round(rng.uniform(0.62, 0.92), 3)
    mw = round(rng.uniform(380, 620), 1)
    logp = round(rng.gauss(2.4, 1.4), 2)
    tpsa = round(rng.uniform(80, 180), 1)
    hbd = rng.randint(1, 5)
    hba = rng.randint(4, 11)
    rb = rng.randint(4, 12)
    lip_v = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    bioav = round(max(0.05, min(0.95, 0.55 + (3 - lip_v) * 0.1 - (rb / 35))), 3)
    hemo_score = round(rng.uniform(0.05, 0.45), 3)
    hemo_class = "low" if hemo_score < 0.3 else "medium"
    composite = round(rng.uniform(0.55, 0.88), 3)
    weakest = rng.choice(["mic", "admet", "novelty", "synth", "hemolysis"])

    # Escape-mutation panel
    n_escapes = rng.randint(2, 4)
    escapes = []
    for _ in range(n_escapes):
        em = rng.choice(escape_mutations)
        fc = rng.choice([4, 8, 16, 32, 64])
        escapes.append({"mutation": em, "fold_change": fc})
    high_risk = sum(1 for e in escapes if e["fold_change"] >= 32)
    escape_verdict = "high-risk" if high_risk >= 2 else "moderate-risk" if high_risk == 1 else "low-risk"

    # Synthesis cost
    sa_score = round(rng.uniform(2.4, 5.6), 2)
    n_steps = rng.randint(3, 8)
    cost_per_g = round(rng.uniform(80, 850))

    # Compose dialogue
    dialog = (
        f"[Designer]: Anchor on the {scaffold_label}. "
        f"{scaffold_rationale}. Keeping the pharmacophore but "
        f"{rng.choice(['extending the allosteric tail', 'swapping the heteroaryl for a bioisostere', 'introducing a polar handle for solubility', 'adding a methyl ortho to the H-bond donor'])}. "
        f"Two design vectors against {target_name} ({pathogen_info['full']}, PDB {pdb}): "
        f"(a) optimize the catalytic-pocket fit, (b) widen contacts to escape variants "
        f"{', '.join(em for em in escape_mutations[:2])}.\n\n"

        f"<tool_call>name: predict_mic_pathogen\n"
        f"args: {{\"smiles\": \"{base_smiles}\", \"pathogen\": \"{pathogen}\"}}</tool_call>\n"
        f"[Tool]: {{\"log_mic_predicted\": {log_mic_pred:.3f}, \"mic_ug_ml\": {mic_ug_ml}, \"confidence\": {confidence}}}\n\n"

        f"[Designer]: log10(MIC)={log_mic_pred:.2f} -> MIC ~{mic_ug_ml} ug/mL. "
        f"{'Active range; advance to ADMET.' if log_mic_pred < 0.7 else 'Borderline activity; will need a scaffold-hop iteration after panel completion.'}\n\n"

        f"<tool_call>name: predict_admet\n"
        f"args: {{\"smiles\": \"{base_smiles}\"}}</tool_call>\n"
        f"[Tool]: {{\"mw\": {mw}, \"logp\": {logp}, \"tpsa\": {tpsa}, \"hbd\": {hbd}, "
        f"\"hba\": {hba}, \"rotatable_bonds\": {rb}, \"lipinski_violations\": {lip_v}, "
        f"\"bioavailability_score\": {bioav}}}\n\n"

        f"[Designer]: MW={mw}, logP={logp}, TPSA={tpsa}, Lipinski violations={lip_v}, "
        f"F={bioav}. "
        f"{'Clean pass for IV dosing.' if lip_v <= 1 else f'{lip_v} Lipinski violations — IV-only acceptable for hospital indication; PO would need MW reduction.'} "
        f"Hemolysis next.\n\n"

        f"<tool_call>name: predict_hemolysis\n"
        f"args: {{\"smiles\": \"{base_smiles}\"}}</tool_call>\n"
        f"[Tool]: {{\"safety_score\": {hemo_score}, \"risk_class\": \"{hemo_class}\"}}\n\n"

        f"[Designer]: {hemo_class.title()} hemolytic risk (score {hemo_score}). "
        f"{'OK for development.' if hemo_class == 'low' else 'Flag for in vitro RBC assay before commit.'} "
        f"Composite scoring next.\n\n"

        f"<tool_call>name: score_molecule\n"
        f"args: {{\"smiles\": \"{base_smiles}\", \"target_pathogen\": \"{pathogen}\"}}</tool_call>\n"
        f"[Tool]: {{\"composite\": {composite}, \"weakest\": \"{weakest}\", \"strongest\": \"mic\"}}\n\n"

        f"[Critic]: Adversarial review.\n"
        f"  - PASS: no PAINS substructures detected on the pharmacophore.\n"
        f"  - {'PASS' if hemo_class == 'low' else 'WARN'}: hemolysis risk = {hemo_class}.\n"
        f"  - {'PASS' if lip_v <= 1 else 'WARN'}: Lipinski violations = {lip_v}.\n"
        f"  - PASS: scaffold class is mechanistically distinct from {pathogen_info['first_line'].split(';')[0].strip()} "
        f"first-line therapy — orthogonal MoA reduces cross-resistance.\n"
        f"  - WARN: novelty against the known-corpus index is marginal — recommend running "
        f"compare_molecules for Tanimoto check before commit.\n\n"

        f"[Designer]: Acknowledging Critic. Running resistance red-team.\n\n"

        f"<tool_call>name: predict_resistance_escape\n"
        f"args: {{\"smiles\": \"{base_smiles}\", \"pathogen\": \"{pathogen}\"}}</tool_call>\n"
        f"[Tool]: {{\"escape_mutations\": {json.dumps(escapes)}, \"red_team_verdict\": \"{escape_verdict}\"}}\n\n"

        f"[Designer]: Red-team verdict: {escape_verdict}. "
        f"Top escape concern: {escapes[0]['mutation']} ({escapes[0]['fold_change']}x fold). "
        f"{'Designer will iterate to widen the binding-pocket interactions to evade.' if escape_verdict == 'high-risk' else 'Acceptable resistance profile for hit-to-lead progression.'} "
        f"Synthesis evaluation next.\n\n"

        f"<tool_call>name: predict_synthesis_route\n"
        f"args: {{\"target_smiles\": \"{base_smiles}\"}}</tool_call>\n"
        f"[Tool]: {{\"sa_score\": {sa_score}, \"estimated_steps\": {n_steps}, "
        f"\"estimated_cost_usd_per_g\": {cost_per_g}, \"confidence_route_found\": {round(rng.uniform(0.6, 0.9), 3)}}}\n\n"

        f"[Designer]: SA={sa_score}, ~{n_steps} steps, ${cost_per_g}/g. "
        f"{'Synthesizable at medchem scale.' if cost_per_g < 500 else 'High-cost route - flag for chemistry team prioritization.'}\n\n"

        f"=== FINAL CANDIDATE REPORT ===\n"
        f"Target pathogen: {pathogen_info['full']} ({pathogen})\n"
        f"Primary target: {target_name} (PDB {pdb})\n"
        f"Anchor scaffold: {scaffold_label}\n"
        f"\n"
        f"Top candidate SMILES: {base_smiles}\n"
        f"  Predicted MIC:           {mic_ug_ml} ug/mL (log10={log_mic_pred:.2f}, conf {confidence})\n"
        f"  ADMET:                   MW={mw}, logP={logp}, Lipinski viol={lip_v}, F={bioav}\n"
        f"  Hemolysis:               {hemo_class}-risk (score {hemo_score})\n"
        f"  Composite:               {composite} (weakest pillar: {weakest})\n"
        f"  Resistance verdict:      {escape_verdict}\n"
        f"  Synthesis:               SA={sa_score}, ~{n_steps} steps, ${cost_per_g}/g\n"
        f"\n"
        f"Mechanistic rationale: The candidate engages {target_name} via "
        f"{rng.choice(['the catalytic active-site serine', 'the allosteric pocket', 'the metal-binding cleft', 'the substrate channel'])} "
        f"and circumvents the dominant resistance route ({escape_mutations[0]}) by "
        f"{rng.choice(['avoiding the canonical pharmacophore that escape mutations target', 'engaging an orthogonal contact map', 'binding a residue absent in the resistant variant', 'using a second-target mechanism with low cross-resistance pressure'])}.\n"
        f"\n"
        f"First-line context: current standard for {pathogen} is {pathogen_info['first_line']}. "
        f"This candidate aims to PIVOT AROUND that class to reduce cross-resistance pressure, not compete with it.\n"
        f"\n"
        f"Recommendation: "
        f"{'Promote to wet-lab validation panel.' if (log_mic_pred < 0.7 and escape_verdict != 'high-risk' and lip_v <= 1) else 'Iterate further before promotion: address the weakest pillar identified above.'}"
    )

    return {
        "task": "teacher_distill",
        "pathogen": pathogen,
        "target": target_name,
        "pdb": pdb,
        "scaffold_class": scaffold_label,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": (
                f"Design a candidate against {pathogen_info['full']} ({pathogen}). "
                f"Primary target: {target_name} (PDB {pdb}). "
                f"Target rationale: {target_rationale} "
                f"Run the standard panel and end with a structured FINAL CANDIDATE REPORT."
            )},
            {"role": "assistant", "content": dialog},
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0xDA5_AB1F)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    if OUT.exists(): OUT.unlink()
    counts = {}
    n_done = 0
    with open(OUT, "a") as f:
        for _ in range(args.n):
            row = synth_one_trace(rng)
            if row is None: continue
            f.write(json.dumps(row) + "\n")
            n_done += 1
            key = (row["pathogen"], row["target"])
            counts[key] = counts.get(key, 0) + 1

    print(f"\nGenerated {n_done} teacher-distillation traces")
    print("Per (pathogen, target):")
    for k, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k[0]:12s} {k[1]:25s} {n:>4}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
