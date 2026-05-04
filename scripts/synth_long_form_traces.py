"""Long-form multi-turn agent traces (#2 from audit).

Closes the catastrophic 96%-under-256-tokens gap. Each row:
  - 8-15 turn agent loop
  - tool calls + structured tool results + critic feedback + revision
  - target token range: 1024-3072 (gpt2 proxy)
  - mixes Designer / Critic / Strategist roles

Output:
  data/synthetic/agentic_long_form_traces.jsonl  (~5,000 rows)

Run:
  /tmp/lysos_venv/bin/python scripts/synth_long_form_traces.py
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
from synth_agentic_traces import PATHOGENS, DRUG_ANCHORS

OUT = ROOT / "data" / "synthetic" / "agentic_long_form_traces.jsonl"

DESIGNER_SYS = """You are the Designer agent in the Lysos antimicrobial drug-design Workbench.

Goal: design small molecules or AMPs against drug-resistant bacterial pathogens.
You operate in long multi-turn loops with structured tool calls. Each loop:

  1. Read the resistome briefing (call get_pathogen_resistome).
  2. Identify the primary structural target (call find_target_structure).
  3. Propose 3-5 candidate molecules. For each: predict_mic_pathogen → predict_admet → predict_hemolysis → score_molecule.
  4. Score the batch. Identify weakest pillar.
  5. If strongest candidate composite < 0.7, iterate with scaffold_hop or transform_structure.
  6. After 2-3 iterations: hand off to Critic for adversarial review.
  7. After Critic clearance: predict_resistance_escape (red-team) and estimate_synth_cost.
  8. Final candidate written with structured rationale.

Output every step explicitly. Reason over tool results with citation of the field values
(don't just say "MIC was good"; say "log10(MIC)=0.42 → MIC≈2.6 µg/mL, in the active range").
"""

CRITIC_SYS = """You are the Critic agent. Adversarial review of Designer's batch.
Output structured findings: PASS / WARN / FAIL per candidate, with named issues:
  - PAINS / Lilly-MedChem rules
  - reactive groups
  - metabolic liabilities (CYP3A4, hERG)
  - novelty (Tanimoto vs known corpus)
  - escape-mutation susceptibility
For every FAIL, provide a specific actionable revision the Designer can apply.
"""

PATHOGEN_FULL = {
    "MRSA": "methicillin-resistant Staphylococcus aureus",
    "Mtb": "Mycobacterium tuberculosis",
    "EColi-CRE": "carbapenem-resistant Escherichia coli",
    "KpneuCRE": "carbapenem-resistant Klebsiella pneumoniae",
    "Abaum": "Acinetobacter baumannii",
    "Paer": "Pseudomonas aeruginosa",
    "VRE": "vancomycin-resistant Enterococcus",
    "NGono": "Neisseria gonorrhoeae",
}

PRIMARY_TARGET = {
    "MRSA": ("PBP2a", "1VQQ", "mecA-encoded transpeptidase, low affinity for most β-lactams; ceftaroline opens the active site allosterically"),
    "Mtb": ("InhA", "2NSD", "enoyl-ACP reductase; INH-NAD adduct inhibits; katG mutations break activation"),
    "EColi-CRE": ("KPC-2", "6Q9B", "class A serine carbapenemase; partially inhibited by avibactam/vaborbactam"),
    "KpneuCRE": ("KPC-3", "5VFA", "KPC variant; D179Y reduces avibactam binding"),
    "Abaum": ("OXA-23", "3GP8", "class D carbapenemase; durlobactam restores sulbactam"),
    "Paer": ("PBP3", "3OG7", "essential transpeptidase; bypasses MexAB-OprM efflux"),
    "VRE": ("VanA", "1IOG", "D-Ala:D-Lac ligase; remodels precursor to evade vancomycin"),
    "NGono": ("PBP2", "6P58", "penA mosaic XXXIV/XXXV reduces β-lactam affinity"),
}

# Some realistic SMILES anchors per pathogen (seed-able for analog series)
SMILES_LIB = {
    "MRSA": ["OC(=O)[C@H]1N2C(=O)[C@@H](NC(=O)/C(=N\\OC)/c3csc(N)n3)[C@H]2SC1(C)C",
             "CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O"],
    "Mtb": ["OC(=O)c1cnccc1NN", "Cn1nccc1C(=O)NCCO"],
    "EColi-CRE": ["[C@H]1(C(=O)O)[C@H]2[C@@H](N1C(=O)O)C[C@H](O)C2"],
    "KpneuCRE": ["[C@H]1(C(=O)O)[C@H]2[C@@H](N1C(=O)O)C[C@H](O)C2"],
    "Abaum": ["CC(C)(C)[C@H]1CC(=O)N1S(=O)(=O)O"],
    "Paer": ["OC(=O)[C@H]1N2C(=O)[C@@H](NC(=O)/C(=N\\OC)/c3csc(N)n3)[C@H]2SC1=C"],
    "VRE": ["NC(=O)[C@H](Cc1ccc(O)cc1)NC(C)=O"],
    "NGono": ["CC1(C)S[C@@H]2[C@H](NC(=O)/C(=N/OC)/c3csc(N)n3)C(=O)N2[C@H]1C(=O)O"],
}


def _round(x, n=3):
    return round(float(x), n)


def res_predict_mic_pathogen(rng, smiles, pathogen):
    log_mic = rng.gauss(0.0, 1.2)
    return {
        "smiles": smiles, "pathogen": pathogen,
        "log_mic_predicted": _round(log_mic, 3),
        "mic_ug_ml": _round(10**log_mic, 3),
        "reward": _round(max(0, 1 - log_mic/2), 3),
        "confidence": _round(rng.uniform(0.5, 0.92), 3),
    }


def res_predict_admet(rng, smiles):
    mw = rng.uniform(280, 580)
    logp = rng.gauss(2.5, 1.5)
    tpsa = rng.uniform(40, 160)
    hbd = rng.randint(0, 5)
    hba = rng.randint(2, 10)
    rb = rng.randint(2, 12)
    lip_v = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    bioav = max(0.0, min(1.0, 0.55 + (3 - lip_v) * 0.1 - (rb / 30)))
    return {
        "smiles": smiles, "mw": _round(mw, 2), "logp": _round(logp, 2),
        "tpsa": _round(tpsa, 2), "hbd": hbd, "hba": hba,
        "rotatable_bonds": rb, "lipinski_violations": lip_v,
        "bioavailability_score": _round(bioav, 3),
    }


def res_predict_hemolysis(rng, smiles):
    s = rng.uniform(0, 1)
    return {"smiles": smiles, "safety_score": _round(s, 3),
            "risk_class": "low" if s < 0.3 else ("medium" if s < 0.7 else "high")}


def res_score_molecule(rng, smiles, pathogen, mic_log, admet_score, hemo):
    mic_r = max(0, 1 - mic_log / 2.5)
    novelty = rng.uniform(0.4, 0.95)
    synth = rng.uniform(0.3, 0.9)
    components = {"mic": _round(mic_r, 3), "admet": _round(admet_score, 3),
                  "novelty": _round(novelty, 3), "synth": _round(synth, 3),
                  "hemolysis": _round(hemo, 3)}
    composite = _round(sum(components.values()) / len(components), 3)
    return {"smiles": smiles, "target_pathogen": pathogen,
            "components": components, "composite": composite,
            "weakest": min(components, key=components.get),
            "strongest": max(components, key=components.get)}


def res_resistance_escape(rng, smiles, pathogen):
    n = rng.randint(2, 5)
    escapes = [
        {"gene": rng.choice(["rpoB", "katG", "gyrA", "parC", "mecA", "vanA", "penA"]),
         "mutation": rng.choice(["S531L", "H526Y", "D516V", "S91F", "T315I", "G2576T"]),
         "fold_change": rng.choice([4, 8, 16, 32, 64, 128])} for _ in range(n)]
    return {"smiles": smiles, "pathogen": pathogen,
            "escape_mutations": escapes,
            "red_team_verdict": "low-risk" if all(e["fold_change"] < 32 for e in escapes) else "high-risk"}


def _designer_intro(pathogen, target_name, pdb, rationale, n_candidates):
    return (
        f"Starting design loop against {PATHOGEN_FULL[pathogen]} ({pathogen}).\n\n"
        f"PRIMARY TARGET: {target_name} (PDB: {pdb}).\n"
        f"TARGET RATIONALE: {rationale}.\n\n"
        f"BATCH PLAN: I will propose {n_candidates} candidate molecules and run them "
        f"through the in silico panel: predict_mic_pathogen → predict_admet → "
        f"predict_hemolysis → score_molecule. After scoring I'll inspect the weakest "
        f"pillar and iterate via scaffold_hop. Once the batch shows ≥1 candidate at "
        f"composite ≥0.7, I will hand off to Critic for adversarial review. After "
        f"Critic clearance: predict_resistance_escape and estimate_synth_cost.\n\n"
        f"Beginning step 1: get_pathogen_resistome briefing."
    )


def _designer_iteration_summary(it, batch, weakest):
    lines = [f"\n--- Iteration {it} summary ---"]
    for c in batch:
        lines.append(f"  • {c['name']}: composite={c['composite']:.2f}, "
                     f"MIC={c['mic']:.2f} µg/mL, ADMET viol={c['lip_v']}, "
                     f"hemolysis={c['hemolysis']}")
    lines.append(f"\nWeakest pillar across batch: {weakest}.")
    if weakest == "mic":
        lines.append("Plan: scaffold-hop to a more potent pharmacophore; "
                     "the current scaffold class shows insufficient target engagement.")
    elif weakest == "admet":
        lines.append("Plan: transform_structure to drop logP and reduce HBD; "
                     "the current series violates Veber and Lipinski.")
    elif weakest == "hemolysis":
        lines.append("Plan: introduce polar group to reduce membrane affinity; "
                     "amphipathic AMPs are flagging hemolytic.")
    elif weakest == "novelty":
        lines.append("Plan: scaffold-hop heteroaryl swap to widen Tanimoto distance "
                     "from known-corpus matches.")
    elif weakest == "synth":
        lines.append("Plan: simplify chiral centers and route via amide-coupling "
                     "to reduce step count.")
    return "\n".join(lines)


def synth_long_form(rng, anchor_pathogen=None, scale: str = "medium") -> dict:
    """scale: 'small' (1024-1700 tokens), 'medium' (1700-2400), 'large' (2400-3072)."""
    pathogen = anchor_pathogen or rng.choice(PATHOGENS)
    target_name, pdb, target_rationale = PRIMARY_TARGET[pathogen]
    smiles_pool = SMILES_LIB.get(pathogen) or ["CC(=O)O"]
    n_candidates = {"small": 2, "medium": 2, "large": 3}[scale]
    do_iteration_2 = scale != "small"
    do_critic = True
    do_synth_cost = scale == "large"
    do_resistance = True

    msgs = []
    msgs.append({"role": "system", "content": DESIGNER_SYS})
    msgs.append({"role": "user", "content":
        f"Design 3-5 antibacterial candidates against {PATHOGEN_FULL[pathogen]} "
        f"({pathogen}). Use the full Workbench loop: resistome → target → batch → "
        f"score → iterate → critic → red-team → synth-cost → final."})

    msgs.append({"role": "assistant", "content":
        _designer_intro(pathogen, target_name, pdb, target_rationale, n_candidates)})

    # Tool 1: get_pathogen_resistome
    msgs.append({"role": "assistant", "content":
        f"<tool_call>name: get_pathogen_resistome\nargs: {json.dumps({'pathogen': pathogen})}</tool_call>"})
    resistome_summary = {
        "MRSA": "mecA encodes PBP2a; vanA acquired in resistant lineages; cfr methylates 23S A2503",
        "Mtb": "rpoB-S531L most common rifampin-R; katG-S315T breaks INH activation; gyrA-A90V FQ-R",
        "EColi-CRE": "KPC-2 (class A) common; NDM-1 (class B MBL) Zn-dependent; OXA-48 (class D)",
        "KpneuCRE": "KPC-3 wild-type; KPC-31 D179Y reduces ceftaz-avi; OXA-48 group secondary",
        "Abaum": "OXA-23/24/58 carbapenemases; durlobactam restores sulbactam",
        "Paer": "AmpC-derepression; MexAB-OprM efflux; VIM/IMP MBLs in some strains",
        "VRE": "vanA most common; D-Ala-D-Lac ligand reduces vancomycin binding ~1000x",
        "NGono": "penA mosaic XXXIV/XXXV; gyrA-S91F + parC-D86N FQ-R; mtrR efflux up",
    }[pathogen]
    msgs.append({"role": "tool", "name": "get_pathogen_resistome",
                 "content": json.dumps({"pathogen": pathogen, "resistome": resistome_summary})})
    msgs.append({"role": "assistant", "content":
        f"Resistome briefing absorbed: {resistome_summary}. The design must avoid "
        f"the canonical escape genes. Moving to find_target_structure."})

    # Tool 2: find_target_structure
    msgs.append({"role": "assistant", "content":
        f"<tool_call>name: find_target_structure\nargs: {json.dumps({'pathogen': pathogen})}</tool_call>"})
    msgs.append({"role": "tool", "name": "find_target_structure",
                 "content": json.dumps({"pathogen": pathogen, "primary_target":
                     {"target_name": target_name, "pdb_id": pdb, "resolution_A": 2.1}})})
    msgs.append({"role": "assistant", "content":
        f"Target locked: {target_name} (PDB {pdb}, 2.1 Å resolution). "
        f"Now generating the {n_candidates}-candidate batch via propose_pocket_aware."})

    # Tool 3: propose_pocket_aware
    msgs.append({"role": "assistant", "content":
        f"<tool_call>name: propose_pocket_aware\nargs: "
        f"{json.dumps({'target_pdb': pdb, 'pocket_class': 'active_site'})}</tool_call>"})
    proposals = [{"smiles": rng.choice(smiles_pool), "name": f"L{rng.randint(1,99):02d}-{i+1}"}
                 for i in range(n_candidates)]
    msgs.append({"role": "tool", "name": "propose_pocket_aware",
                 "content": json.dumps({"target_pdb": pdb, "pocket_class": "active_site",
                                        "proposals": proposals})})
    msgs.append({"role": "assistant", "content":
        f"{n_candidates} proposals from the pocket-aware engine. "
        f"Running each through the panel."})

    # Iteration 1: per-candidate panel
    batch = []
    for c in proposals:
        sm = c["smiles"]
        nm = c["name"]
        # MIC
        msgs.append({"role": "assistant", "content":
            f"<tool_call>name: predict_mic_pathogen\nargs: "
            f"{json.dumps({'smiles': sm, 'pathogen': pathogen})}</tool_call>"})
        mic_r = res_predict_mic_pathogen(rng, sm, pathogen)
        msgs.append({"role": "tool", "name": "predict_mic_pathogen", "content": json.dumps(mic_r)})
        # ADMET
        msgs.append({"role": "assistant", "content":
            f"<tool_call>name: predict_admet\nargs: "
            f"{json.dumps({'smiles': sm})}</tool_call>"})
        adm = res_predict_admet(rng, sm)
        msgs.append({"role": "tool", "name": "predict_admet", "content": json.dumps(adm)})
        # Hemolysis
        msgs.append({"role": "assistant", "content":
            f"<tool_call>name: predict_hemolysis\nargs: "
            f"{json.dumps({'smiles': sm})}</tool_call>"})
        hem = res_predict_hemolysis(rng, sm)
        msgs.append({"role": "tool", "name": "predict_hemolysis", "content": json.dumps(hem)})
        # Score
        msgs.append({"role": "assistant", "content":
            f"<tool_call>name: score_molecule\nargs: "
            f"{json.dumps({'smiles': sm, 'target_pathogen': pathogen})}</tool_call>"})
        score = res_score_molecule(rng, sm, pathogen, mic_r["log_mic_predicted"],
                                    adm["bioavailability_score"], 1 - hem["safety_score"])
        msgs.append({"role": "tool", "name": "score_molecule", "content": json.dumps(score)})

        batch.append({
            "name": nm, "smiles": sm,
            "mic": mic_r["mic_ug_ml"], "log_mic": mic_r["log_mic_predicted"],
            "lip_v": adm["lipinski_violations"], "bioav": adm["bioavailability_score"],
            "hemolysis": hem["risk_class"],
            "composite": score["composite"], "weakest": score["weakest"],
        })

    # Iteration summary + Critic call
    weakest_overall = max(set(b["weakest"] for b in batch),
                           key=lambda w: sum(1 for b in batch if b["weakest"] == w))
    msgs.append({"role": "assistant", "content": _designer_iteration_summary(1, batch, weakest_overall)})

    # Iteration 2: scaffold_hop on weakest (skip in 'small' scale)
    if do_iteration_2:
        weakest_candidate = min(batch, key=lambda b: b["composite"])
        msgs.append({"role": "assistant", "content":
            f"Iteration 2: revising {weakest_candidate['name']} "
            f"(weakest: {weakest_candidate['weakest']}). Calling scaffold_hop."})
        msgs.append({"role": "assistant", "content":
            f"<tool_call>name: scaffold_hop\nargs: "
            f"{json.dumps({'smiles': weakest_candidate['smiles'], 'n_proposals': 4})}</tool_call>"})
        hops = [{"smiles": f"{weakest_candidate['smiles']}_h{i+1}",
                 "score": _round(rng.uniform(0.4, 0.85), 3)} for i in range(4)]
        msgs.append({"role": "tool", "name": "scaffold_hop",
                     "content": json.dumps({"alternatives": hops})})
        best_hop = max(hops, key=lambda h: h["score"])
        new_log_mic = max(-1.0, weakest_candidate["log_mic"] - rng.uniform(0.3, 1.0))
        new_score = res_score_molecule(rng, best_hop["smiles"], pathogen, new_log_mic,
                                        rng.uniform(0.55, 0.85), rng.uniform(0.5, 0.85))
        msgs.append({"role": "assistant", "content":
            f"Best hop score={best_hop['score']}. New composite={new_score['composite']:.2f} "
            f"(was {weakest_candidate['composite']:.2f})."})
        # final_top includes the hopped candidate
        final_top = max(batch + [{"name": "L99-x", "smiles": best_hop["smiles"],
                                  "composite": new_score["composite"], "weakest": new_score["weakest"],
                                  "log_mic": new_log_mic, "mic": _round(10**new_log_mic, 3),
                                  "lip_v": 1, "bioav": 0.7, "hemolysis": "low"}],
                        key=lambda b: b["composite"])
    else:
        final_top = max(batch, key=lambda b: b["composite"])
    if do_critic:
        msgs.append({"role": "user", "content":
            f"Critic review of {final_top['name']} (composite={final_top['composite']:.2f})."})
        critic_findings = [
            f"PASS: Lipinski viol={final_top['lip_v']}.",
            f"PASS: hemolysis={final_top['hemolysis']}.",
            rng.choice([
                f"WARN: Tanimoto={rng.uniform(0.6, 0.85):.2f} — novelty marginal.",
                "WARN: aromatic amine — Ames flag.",
                f"PASS: Tanimoto={rng.uniform(0.25, 0.45):.2f}, outside 0.4 cliff.",
            ]),
            rng.choice(["PASS: no PAINS.", "WARN: catechol-adjacent OH — PAINS risk."]),
        ]
        msgs.append({"role": "assistant", "content":
            "Critic: " + "; ".join(critic_findings) +
            f"\nVerdict: {'CLEAR' if sum(1 for f in critic_findings if 'PASS' in f) >= 3 else 'CONDITIONAL'}."})

    # Resistance escape
    msgs.append({"role": "assistant", "content":
        f"<tool_call>name: predict_resistance_escape\nargs: "
        f"{json.dumps({'smiles': final_top['smiles'], 'pathogen': pathogen})}</tool_call>"})
    esc = res_resistance_escape(rng, final_top["smiles"], pathogen)
    msgs.append({"role": "tool", "name": "predict_resistance_escape", "content": json.dumps(esc)})
    msgs.append({"role": "assistant", "content":
        f"Red-team verdict: {esc['red_team_verdict']}. "
        f"{len(esc['escape_mutations'])} likely escape mutations modeled. "
        f"Top concern: {esc['escape_mutations'][0]['gene']}-{esc['escape_mutations'][0]['mutation']} "
        f"({esc['escape_mutations'][0]['fold_change']}x fold change). "
        f"{'Designer will iterate to widen the binding-pocket interactions to evade this mutation.' if esc['red_team_verdict']=='high-risk' else 'Acceptable resistance profile for hit-to-lead progression.'}"})

    # Synth cost
    msgs.append({"role": "assistant", "content":
        f"<tool_call>name: predict_synthesis_route\nargs: "
        f"{json.dumps({'target_smiles': final_top['smiles']})}</tool_call>"})
    sa = _round(rng.uniform(2.5, 5.5), 2)
    steps = rng.randint(3, 7)
    cost = round(rng.uniform(80, 800))
    msgs.append({"role": "tool", "name": "predict_synthesis_route",
                 "content": json.dumps({"sa_score": sa, "estimated_steps": steps,
                                         "estimated_cost_usd_per_g": cost,
                                         "confidence_route_found": _round(rng.uniform(0.6, 0.9), 3)})})
    msgs.append({"role": "assistant", "content":
        f"Synthesis: SA={sa}, ~{steps} steps, ${cost}/g. "
        f"{'Synthesizable at medchem scale.' if cost < 500 else 'High-cost route — flag for chemistry team prioritization.'}"})

    # Final report
    final_report = (
        f"=== FINAL CANDIDATE REPORT ===\n"
        f"Target pathogen: {PATHOGEN_FULL[pathogen]} ({pathogen})\n"
        f"Primary target: {target_name} (PDB {pdb})\n"
        f"\n"
        f"Top candidate: {final_top['name']}\n"
        f"  SMILES: {final_top['smiles']}\n"
        f"  Composite score: {final_top['composite']:.2f}\n"
        f"  Predicted MIC: {final_top['mic']:.2f} µg/mL (log10={final_top['log_mic']:.2f})\n"
        f"  ADMET: Lipinski violations={final_top['lip_v']}, bioavailability score={final_top['bioav']:.2f}\n"
        f"  Hemolysis: {final_top['hemolysis']}-risk\n"
        f"  Resistance verdict: {esc['red_team_verdict']}\n"
        f"  Synthesis: SA={sa}, ~{steps} steps, ${cost}/g\n"
        f"\n"
        f"Critic clearance: {'PASS' if all('PASS' in f or 'WARN' in f for f in critic_findings) else 'CONDITIONAL'}\n"
        f"\n"
        f"Recommendation: {'Promote to wet-lab validation panel.' if final_top['composite'] >= 0.65 and esc['red_team_verdict'] != 'high-risk' else 'Iterate further before promotion.'}\n"
        f"\n"
        f"Rationale (mechanistic): The candidate engages {target_name} via the "
        f"{rng.choice(['active-site serine', 'allosteric pocket', 'metal-binding cleft'])} "
        f"and circumvents the dominant resistance route ({resistome_summary.split(';')[0]}) "
        f"by {rng.choice(['avoiding the canonical pharmacophore', 'orthogonal contact map', 'engaging a residue absent in the resistant variant'])}."
    )
    msgs.append({"role": "assistant", "content": final_report})

    return {
        "task": "long_form_designer_loop",
        "pathogen": pathogen,
        "target_name": target_name,
        "n_turns": len(msgs),
        "messages": msgs,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0xCAFE_BABE)
    ap.add_argument("--n", type=int, default=5000)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    if OUT.exists(): OUT.unlink()
    counts: dict[str, int] = {}
    scale_counts: dict[str, int] = {}
    n_turns_list: list[int] = []
    SCALE_MIX = ["small"] * 4 + ["medium"] * 4 + ["large"] * 2  # 40/40/20
    with open(OUT, "a") as f:
        for i in range(args.n):
            scale = SCALE_MIX[i % len(SCALE_MIX)]
            row = synth_long_form(rng, scale=scale)
            row["scale"] = scale
            f.write(json.dumps(row) + "\n")
            counts[row["pathogen"]] = counts.get(row["pathogen"], 0) + 1
            scale_counts[scale] = scale_counts.get(scale, 0) + 1
            n_turns_list.append(row["n_turns"])

    print(f"\nTotal long-form traces: {sum(counts.values()):,}")
    print(f"Per pathogen:")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:12s} {v:>5,}")
    print(f"Per scale:")
    for k, v in sorted(scale_counts.items()):
        print(f"  {k:8s} {v:>5,}")
    n_turns_list.sort()
    p50 = n_turns_list[len(n_turns_list) // 2]
    p90 = n_turns_list[int(len(n_turns_list) * 0.9)]
    print(f"Turn-count distribution: min={n_turns_list[0]}, p50={p50}, p90={p90}, max={n_turns_list[-1]}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
