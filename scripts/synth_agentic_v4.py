"""Heavy round — depth gaps the audit missed:

  PARETO    — 1,500 rows where Strategist picks among N candidates with
              different reward profiles (trade-off reasoning).
  CLASS     — 2,000 drug-class pharmacology priors (β-lactam → PBP2a;
              FQ → gyrA; macrolide → 23S rRNA; aminoglycoside → 16S).
  MECH      — 2,000 mechanistic CoT chains (target binding mode + escape
              pathway + scaffold-level countermeasure).
  TRAJECTORY— 1,500 rows giving Strategist a real composite trajectory
              [c1, c2, c3, ...] and asking for the decision (plateau /
              improving / regressing pattern recognition).
  REGRESS   — 800 rows where Editor regresses + Designer must re-propose
              from a different scaffold (loop recovery).
  SCAFFOLD  — 1,500 explicit scaffold-hop rows (tool_use scaffold_hop,
              receive 3 alternatives, pick best with rationale).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workspace"))
sys.path.insert(0, str(ROOT / "scripts"))
from synth_agentic_traces import PATHOGENS, DRUG_ANCHORS, get_resistome_briefing
from synth_agentic_v2 import DESIGNER_SYS, CRITIC_SYS, STRATEGIST_SYS

OUT = ROOT / "data" / "synthetic"

# Drug-class pharmacology priors — one row each teaches the model
# "X class targets Y; Z mutation defeats it"
CLASS_PRIORS = [
    ("β-lactam (penam, cephem, carbapenem)", "PBP2a / PBP3 / OXA-48", "transpeptidase inhibition", "blaKPC, blaNDM, mecA, ESBL"),
    ("fluoroquinolone", "DNA gyrase (gyrA) + topoisomerase IV (parC)", "supercoiling inhibition", "gyrA S91F, parC S87R, qnrA/B/S, AAC(6')-Ib-cr"),
    ("macrolide", "23S rRNA (peptidyl transferase center)", "ribosome arrest", "ermA/B/C 23S methylation, mefA efflux, A2058G/A2059G"),
    ("aminoglycoside", "16S rRNA decoding A-site (30S)", "translational misreading + cell death", "rmtB/armA 16S methylation, AAC/ANT/APH-modifying enzymes"),
    ("oxazolidinone (linezolid)", "23S rRNA (V loop) + 50S A-site", "blocks initiation complex assembly", "G2576T, cfr methylation, optrA, poxtA"),
    ("glycopeptide (vancomycin)", "D-Ala-D-Ala terminus of peptidoglycan precursor", "blocks transpeptidation by sequestering substrate", "vanA / vanB → D-Ala-D-Lac substitution"),
    ("lipopeptide (daptomycin)", "membrane phosphatidylglycerol (Ca2+-mediated insertion)", "membrane depolarization", "mprF L826F, walK T101M, cls R218Q"),
    ("polymyxin (colistin)", "lipid A of LPS (gram-negative)", "membrane disruption", "pmrAB H89R, mcr-1/-2 (plasmid), lpxA loss"),
    ("tetracycline", "30S ribosomal A-site", "blocks aminoacyl-tRNA binding", "tetK/tetM efflux, tetX oxidation, ribosomal protection (Tet(O))"),
    ("nitroimidazole (metronidazole, pretomanid)", "DNA (after activation by anaerobic enzymes / Ddn)", "DNA damage", "Ddn loss-of-function, low-NAD reduction state"),
    ("rifamycin (rifampin)", "RpoB β-subunit of RNA polymerase", "blocks transcription initiation", "RRDR mutations: S531L, H526Y, D516V"),
    ("diaminopyrimidine (trimethoprim)", "dihydrofolate reductase (DHFR)", "blocks folate synthesis", "dfrA1/dfrG acquisition; F98Y in TMP-resistant DHFR"),
    ("sulfonamide", "dihydropteroate synthase (DHPS)", "blocks folate synthesis", "sul1/sul2 acquisition; P64S DHPS mutation"),
    ("isoniazid (INH)", "InhA (enoyl-ACP reductase, mycolic acid synthesis)", "blocks mycolic acid biosynthesis", "katG S315T (no activation), inhA -15 C/T promoter"),
    ("ethambutol", "EmbB (arabinosyl transferase)", "blocks arabinogalactan synthesis", "embB M306I/V"),
    ("bedaquiline", "atpE (mycobacterial ATP synthase c-ring)", "blocks ATP generation", "atpE D28V/I66M; Rv0678 efflux derepression"),
    ("pleuromutilin (lefamulin)", "23S rRNA (peptidyl transferase center, V domain)", "blocks tRNA binding", "vga(A), cfr (linezolid cross-resistance)"),
    ("phenicol (chloramphenicol)", "23S rRNA + peptidyl transferase", "blocks peptide bond formation", "catA/catB acetyltransferases, cfr"),
]
def synth_class_prior(rng, pathogen) -> dict:
    cls, target, mech, defeat = rng.choice(CLASS_PRIORS)
    msgs = [
        {"role": "system", "content":
            "You teach drug-class pharmacology priors. Given a class, name "
            "the molecular target, the mechanism, and the dominant resistance routes."},
        {"role": "user", "content":
            f"What's the target / mechanism / resistance profile of the {cls} class "
            f"in the context of {pathogen}?"},
        {"role": "assistant", "content":
            f"Class: {cls}\n"
            f"Target: {target}\n"
            f"Mechanism: {mech}\n"
            f"Dominant resistance routes: {defeat}\n"
            f"Implication for {pathogen}: any candidate in this class must avoid the listed resistance "
            f"genes/mutations, or be paired with an inhibitor / pump-bypass."},
    ]
    return {"task": "drug_class_prior", "pathogen": pathogen, "messages": msgs}


# Mechanism CoT chains — bind site → escape pathway → counter-strategy
MECHANISM_CHAINS = [
    ("PBP2a active site", "MRSA carries mecA encoding PBP2a, which has a closed active site that excludes most β-lactams.",
     "Ceftaroline overcomes this via a structural feature (oxyimino + thiadiazole side-chain) that stabilises an open conformation.",
     "Designs in this class should preserve the conformational opener while modulating the C-3 and C-7 side chains."),
    ("23S rRNA peptidyl transferase center", "G2576T (E. coli numbering) on 23S rRNA shifts the A-site geometry, eliminating linezolid binding.",
     "Tedizolid + radezolid extend the C-5 acetamide arm, restoring contacts that compensate for the loss.",
     "Future oxazolidinones should explore C-5 substituents that span both the original and shifted geometries."),
    ("DNA gyrase (gyrA)", "S83L / S91F substitutions reduce the affinity of the gyrA pocket for fluoroquinolones.",
     "8-methoxy-quinolones (moxifloxacin) gain water-bridged contacts that recover binding under S83 mutations.",
     "Design should explore C-7 + C-8 substituent pairs that retain potency across S83 + parC variants."),
    ("D-Ala-D-Ala peptidoglycan terminus", "vanA acquisition switches the terminus to D-Ala-D-Lac, reducing vancomycin affinity ~1000x.",
     "Lipoglycopeptides (telavancin, dalbavancin) restore activity via membrane anchoring + secondary site binding.",
     "Future scaffolds should carry a lipophilic anchor + cationic residue for dual mechanism."),
    ("Membrane phosphatidylglycerol (Ca2+-mediated)", "mprF L826F flips lysyl-PG to the outer leaflet, repelling daptomycin's Ca2+ complex.",
     "Octapeptin scaffolds use a different lipid recognition mode that bypasses the lysyl-PG repulsion.",
     "Designs should explore alternative membrane recognition (cardiolipin-targeting) instead of PG."),
    ("16S rRNA decoding A-site", "rmtB / armA acquisition methylates G1405 / A1408, blocking aminoglycoside binding.",
     "Plazomicin's deletion at the 4'-position partially restores binding by shifting interactions to 5'-OH.",
     "Future aminoglycosides should explore 4'-deoxy + 6'-N-substituted variants that bypass the methylation."),
    ("RpoB RRDR", "S531L sits at the rifampin binding cleft entrance; the mutation eliminates direct H-bond.",
     "Rifapentine and the PRIME-class explore alternative side-chains that recover contacts via van der Waals.",
     "New scaffolds should explore rifaximin-like rigidity + hydrophobic packing in the RRDR pocket."),
]
def synth_mechanism_cot(rng, pathogen) -> dict:
    target, escape, recovery, design = rng.choice(MECHANISM_CHAINS)
    msgs = [
        {"role": "system", "content":
            "You explain antibiotic mechanism + resistance + counter-strategy as a 4-step chain."},
        {"role": "user", "content":
            f"For target '{target}' in {pathogen}, walk me through: "
            f"1) the dominant escape pathway, "
            f"2) how an existing class regains activity, "
            f"3) what direction a new candidate should explore."},
        {"role": "assistant", "content":
            f"Target: {target}\n\n"
            f"1) Escape: {escape}\n\n"
            f"2) Recovery (current class): {recovery}\n\n"
            f"3) Design direction: {design}"},
    ]
    return {"task": "mechanism_cot", "pathogen": pathogen, "messages": msgs}


# Pareto reasoning — N candidates with different reward profiles
def synth_pareto(rng, pathogen) -> dict:
    n_cands = rng.randint(3, 5)
    cands = []
    for i in range(n_cands):
        scores = {
            "predicted_mic":      round(rng.uniform(0.40, 0.95), 3),
            "drug_likeness_qed":  round(rng.uniform(0.40, 0.95), 3),
            "synthesizability":   round(rng.uniform(0.40, 0.95), 3),
            "hemolysis_safety":   round(rng.uniform(0.40, 0.95), 3),
            "novelty":            round(rng.uniform(0.40, 0.95), 3),
        }
        scores["composite"] = round(sum(scores.values()) / len(scores), 3)
        cands.append({"id": f"c{i+1}", "scores": scores})
    # Pick the one with best composite as recommendation
    best = max(cands, key=lambda c: c["scores"]["composite"])
    cand_lines = "\n".join(
        f"  {c['id']}: composite {c['scores']['composite']:.3f}, MIC {c['scores']['predicted_mic']:.2f}, "
        f"QED {c['scores']['drug_likeness_qed']:.2f}, synth {c['scores']['synthesizability']:.2f}, "
        f"safety {c['scores']['hemolysis_safety']:.2f}, novelty {c['scores']['novelty']:.2f}"
        for c in cands
    )
    msgs = [
        {"role": "system", "content": STRATEGIST_SYS},
        {"role": "user", "content":
            f"Pareto frontier for {pathogen} ({n_cands} candidates):\n{cand_lines}\n\n"
            f"Pick the ship candidate and justify."},
        {"role": "assistant", "content":
            f"DECISION: SHIP {best['id']}\n"
            f"RATIONALE: {best['id']} has the highest composite ({best['scores']['composite']:.3f}). "
            f"Its profile balances MIC + drug-likeness without sacrificing safety. "
            f"Other candidates either trade off MIC for novelty or lose synthesizability."},
    ]
    return {"task": "pareto_selection", "pathogen": pathogen, "messages": msgs}


# Trajectory pattern recognition (composite-over-time → decision)
def synth_trajectory(rng, pathogen) -> dict:
    pattern = rng.choice(["plateau", "improving", "regressing", "oscillating"])
    if pattern == "plateau":
        c0 = rng.uniform(0.55, 0.65)
        traj = [round(c0 + rng.gauss(0, 0.005), 3) for _ in range(rng.randint(3, 5))]
        decision, reason = "BRANCH", "Last 3-4 composites within ±0.01 — plateau detected; recommending scaffold-hop."
    elif pattern == "improving":
        traj = [round(0.45 + i * rng.uniform(0.04, 0.10), 3) for i in range(rng.randint(3, 5))]
        decision, reason = "CONTINUE", f"Composite improving steadily (slope ~+{(traj[-1]-traj[0])/(len(traj)-1):.3f}/iter); momentum healthy."
    elif pattern == "regressing":
        c0 = rng.uniform(0.70, 0.80)
        traj = [round(c0 - i * rng.uniform(0.02, 0.05), 3) for i in range(rng.randint(3, 5))]
        decision, reason = "BRANCH", "Composite regressing across iterations — Editor's transforms hurting; branch to a new scaffold."
    else:
        traj = [round(0.55 + 0.05 * (-1)**i + rng.gauss(0, 0.02), 3) for i in range(rng.randint(4, 6))]
        decision, reason = "CONTINUE", "Composite oscillating but Critic still finding new weakness each turn — staying in-loop."
    msgs = [
        {"role": "system", "content": STRATEGIST_SYS},
        {"role": "user", "content":
            f"Composite trajectory for {pathogen}: {traj}\n"
            f"Decide T/C/B based on the pattern."},
        {"role": "assistant", "content":
            f"DECISION: {decision}\nRATIONALE: {reason}"},
    ]
    return {"task": "trajectory_pattern", "pathogen": pathogen, "messages": msgs}


# Loop recovery (Editor regressed → Designer re-proposes from different scaffold)
LOOP_RECOVERY_HINTS = [
    ("β-lactam", "oxazolidinone"), ("β-lactam", "fluoroquinolone"),
    ("fluoroquinolone", "lipopeptide"), ("fluoroquinolone", "tetracycline"),
    ("aminoglycoside", "polymyxin"), ("aminoglycoside", "phenicol"),
    ("macrolide", "pleuromutilin"), ("macrolide", "lincosamide"),
    ("oxazolidinone", "rifamycin"), ("glycopeptide", "lipoglycopeptide"),
    ("rifamycin", "diarylquinoline"), ("isoniazid", "ethionamide"),
]
def synth_loop_recovery(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    from_cls, to_cls = rng.choice(LOOP_RECOVERY_HINTS)
    msgs = [
        {"role": "system", "content": DESIGNER_SYS},
        {"role": "user", "content":
            f"Editor's last 2 transforms regressed composite. Designer should re-propose "
            f"from a DIFFERENT scaffold class. Current was {from_cls}; pick a fresh class for {pathogen}."},
        {"role": "assistant", "content":
            f"PROPOSAL: {smiles}\n"
            f"RATIONALE: Class hop from {from_cls} → {to_cls}. The {to_cls} class targets a "
            f"different essential pathway, so the Critic's earlier weakness in the {from_cls} "
            f"family won't carry over. Anchored on {name} as the {to_cls}-class exemplar."},
    ]
    return {"task": "loop_recovery_classhop", "pathogen": pathogen, "messages": msgs}


# Explicit scaffold-hop with tool_use
def synth_scaffold_hop(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    alts = [smiles + "_alt1", smiles + "_alt2", smiles + "_alt3"]
    msgs = [
        {"role": "system", "content": DESIGNER_SYS},
        {"role": "user", "content":
            f"Generate scaffold-hop alternatives for {smiles[:40]}... against {pathogen}."},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu_h", "name": "scaffold_hop",
             "input": {"smiles": smiles, "n_alternatives": 3}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_h",
             "content": json.dumps({"alternatives": alts})},
        ]},
        {"role": "assistant", "content":
            f"Three alternatives returned. Picking #1 — it preserves the active fragment "
            f"while shifting the central ring system, which should reduce Tanimoto to known "
            f"resistant scaffolds without sacrificing the {name}-anchored pharmacophore.\n"
            f"PROPOSAL: {alts[0]}\n"
            f"RATIONALE: Scaffold-hop chosen for novelty + resistance dodge."},
    ]
    return {"task": "scaffold_hop_explicit", "pathogen": pathogen, "messages": msgs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-class",      type=int, default=2000)
    ap.add_argument("--n-mechanism",  type=int, default=2000)
    ap.add_argument("--n-pareto",     type=int, default=1500)
    ap.add_argument("--n-trajectory", type=int, default=1500)
    ap.add_argument("--n-recovery",   type=int, default=800)
    ap.add_argument("--n-scaffold",   type=int, default=1500)
    ap.add_argument("--seed", type=int, default=0xC0DE_F00D)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    paths = {
        "class":      OUT / "agentic_class_priors.jsonl",
        "mechanism":  OUT / "agentic_mechanism_cot.jsonl",
        "pareto":     OUT / "agentic_pareto_selection.jsonl",
        "trajectory": OUT / "agentic_trajectory_pattern.jsonl",
        "recovery":   OUT / "agentic_loop_recovery.jsonl",
        "scaffold":   OUT / "agentic_scaffold_hop_explicit.jsonl",
    }
    for p in paths.values():
        if p.exists(): p.unlink()

    counts = {k: 0 for k in paths}
    n_per = {k: getattr(args, f"n_{k.split('_')[0]}", 1000) // len(PATHOGENS) for k in paths}
    n_per = {
        "class":      args.n_class // len(PATHOGENS),
        "mechanism":  args.n_mechanism // len(PATHOGENS),
        "pareto":     args.n_pareto // len(PATHOGENS),
        "trajectory": args.n_trajectory // len(PATHOGENS),
        "recovery":   args.n_recovery // len(PATHOGENS),
        "scaffold":   args.n_scaffold // len(PATHOGENS),
    }
    for pathogen in PATHOGENS:
        if pathogen not in DRUG_ANCHORS or not DRUG_ANCHORS[pathogen]:
            continue
        anchors = DRUG_ANCHORS[pathogen]
        with open(paths["class"], "a") as f:
            for _ in range(n_per["class"]):
                f.write(json.dumps(synth_class_prior(rng, pathogen)) + "\n"); counts["class"] += 1
        with open(paths["mechanism"], "a") as f:
            for _ in range(n_per["mechanism"]):
                f.write(json.dumps(synth_mechanism_cot(rng, pathogen)) + "\n"); counts["mechanism"] += 1
        with open(paths["pareto"], "a") as f:
            for _ in range(n_per["pareto"]):
                f.write(json.dumps(synth_pareto(rng, pathogen)) + "\n"); counts["pareto"] += 1
        with open(paths["trajectory"], "a") as f:
            for _ in range(n_per["trajectory"]):
                f.write(json.dumps(synth_trajectory(rng, pathogen)) + "\n"); counts["trajectory"] += 1
        with open(paths["recovery"], "a") as f:
            for _ in range(n_per["recovery"]):
                f.write(json.dumps(synth_loop_recovery(rng, pathogen, rng.choice(anchors))) + "\n"); counts["recovery"] += 1
        with open(paths["scaffold"], "a") as f:
            for _ in range(n_per["scaffold"]):
                f.write(json.dumps(synth_scaffold_hop(rng, pathogen, rng.choice(anchors))) + "\n"); counts["scaffold"] += 1
    print(json.dumps({"counts": counts}, indent=2))

if __name__ == "__main__":
    main()
