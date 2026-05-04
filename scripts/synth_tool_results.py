"""Synthesize tool-call → result → continuation traces (#8 from audit).

Goal: train Designer to handle structured tool RESULTS, not just emit calls.
Each row: (system, user, assistant=tool_call, tool=result, assistant=continuation).

For each of the 25 Lysos tools, we generate ~150 traces:
  - args sampled from the tool's input_model
  - results sampled from realistic distributions matching the output_model
  - continuation written by templated reasoning over the result fields

Output:
  data/synthetic/agentic_tool_results.jsonl  (~3,750 rows)

Run:
  /tmp/lysos_venv/bin/python scripts/synth_tool_results.py
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

OUT = ROOT / "data" / "synthetic" / "agentic_tool_results.jsonl"

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

# Real PDB ids for 8 priority pathogens
PDB_BY_PATHOGEN = {
    "MRSA": ["1VQQ", "3ZG0", "5M18"],          # PBP2a
    "Mtb": ["1ZID", "2NSD", "4BG8"],           # InhA, KatG, RpoB
    "EColi-CRE": ["6Q9B", "5HVI", "3OQB"],     # KPC-2, OXA-48, NDM-1
    "KpneuCRE": ["3DW0", "5VFA", "5KSC"],      # KPC-3, KPC + avi
    "Abaum": ["3GP8", "7LZQ", "3X64"],         # OXA-23, sulbactam-durlobactam target
    "Paer": ["3OG7", "5O8R", "6QU4"],          # PBP3, MexAB
    "VRE": ["1IOG", "3F4U"],                    # VanA, D-Ala-D-Ala ligase
    "NGono": ["6P58", "5N6S"],                 # PBP2 (penA), GyrB
}

DRUG_CLASS_BY_RESISTOME = {
    "MRSA":      [("beta-lactam", ["mecA", "blaZ"]),
                  ("glycopeptide", ["vanA acquired"]),
                  ("oxazolidinone", ["cfr", "23S G2576T"])],
    "Mtb":       [("rifamycin", ["rpoB-S531L", "rpoB-H526Y"]),
                  ("INH-class", ["katG-S315T", "inhA promoter"]),
                  ("fluoroquinolone", ["gyrA-A90V"])],
    "EColi-CRE": [("carbapenem", ["KPC-2", "NDM-1", "OXA-48"]),
                  ("3GC", ["CTX-M-15", "ESBL"])],
    "KpneuCRE":  [("carbapenem", ["KPC-3", "KPC-31", "OXA-48"])],
    "Abaum":     [("carbapenem", ["OXA-23", "OXA-24", "OXA-58"])],
    "Paer":      [("anti-pseudomonal cephalosporin", ["AmpC-derepressed", "MexAB-OprM"]),
                  ("carbapenem", ["VIM", "IMP", "porin loss"])],
    "VRE":       [("glycopeptide", ["vanA", "vanB"]),
                  ("oxazolidinone", ["23S G2576T", "cfr"])],
    "NGono":     [("3GC", ["penA-mosaic-XXXIV", "penA-mosaic-XXXV"]),
                  ("fluoroquinolone", ["gyrA-S91F", "parC-D86N"])],
}

# A small library of realistic SMILES anchors for each pathogen
SMILES_LIB = {
    "MRSA": [
        "CC(=O)N[C@@H](Cc1ccc(O)cc1)C(=O)O",
        "CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O",  # benzylpenicillin scaffold
        "OC(=O)[C@H]1N2C(=O)[C@@H](NC(=O)Cn3cnnn3)[C@H]2SC1(C)C",   # cefazolin-style
    ],
    "Mtb": [
        "OC(=O)c1cnccc1N",          # INH-like
        "Cc1cc(C(=O)O)cnc1Cl",      # PZA-like
        "CCC(C)C[C@@H]1[C@@H](O)[C@H](O)[C@@H](O)[C@H](C)O1",
    ],
    "EColi-CRE": [
        "CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O",
    ],
    "KpneuCRE": [
        "[C@H]1(C(=O)O)[C@H]2[C@@H](N1C(=O)O)C[C@H](O)C2",
    ],
    "Abaum": [
        "CC(C)(C)Oc1nc2c(C(=O)O)cccc2[nH]1",
    ],
    "Paer": [
        "OC(=O)[C@H]1N2C(=O)[C@@H](NC(=O)/C(=N\\OC)/c3csc(N)n3)[C@H]2SC1=C",
    ],
    "VRE": [
        "CC(=O)N[C@@H](Cc1ccc(O)cc1)C(=O)O",
    ],
    "NGono": [
        "CC1(C)S[C@@H]2[C@H](NC(=O)/C(=N/OC)/c3csc(N)n3)C(=O)N2[C@H]1C(=O)O",
    ],
}


def _round(x: float, n: int = 3) -> float:
    return round(float(x), n)


# ----------------------------------------------------------------------------
# Per-tool result generators (return dict matching output_model)
# ----------------------------------------------------------------------------
def res_predict_mic_pathogen(rng, smiles, pathogen):
    log_mic = rng.gauss(0.0, 1.2)
    mic = 10 ** log_mic
    interp = "active" if log_mic < 0.7 else ("borderline" if log_mic < 1.5 else "inactive")
    return {
        "smiles": smiles,
        "pathogen": pathogen,
        "log_mic_predicted": _round(log_mic, 3),
        "mic_ug_ml": _round(mic, 3),
        "reward": _round(max(0.0, 1.0 - log_mic / 2.0), 3),
        "confidence": _round(rng.uniform(0.45, 0.92), 3),
        "interpretation": (f"Predicted log10(MIC)={log_mic:.2f} → "
                           f"MIC≈{mic:.2f} µg/mL against {pathogen}; "
                           f"classified {interp}."),
        "predictor": "xgboost_morgan_fp_v2",
    }


def res_check_resistance_genes(rng, pathogen, drug_class_or_smiles):
    drug_class, genes = rng.choice(DRUG_CLASS_BY_RESISTOME[pathogen])
    return {
        "pathogen": pathogen,
        "drug_class_inferred": drug_class,
        "relevant_genes": genes,
        "summary": (f"{pathogen} carries {', '.join(genes)} as the primary "
                    f"resistance determinants for {drug_class}."),
    }


def res_get_pathogen_resistome(rng, pathogen):
    classes = DRUG_CLASS_BY_RESISTOME[pathogen]
    resistome = {cls: genes for cls, genes in classes}
    return {
        "pathogen": pathogen,
        "full_name": PATHOGEN_FULL[pathogen],
        "resistome": resistome,
        "intrinsic_features": {
            "MRSA": ["thick peptidoglycan", "PBP2a low affinity"],
            "Mtb": ["mycolic acid wall", "slow growth", "intracellular"],
            "EColi-CRE": ["outer membrane porins", "AcrAB efflux"],
            "KpneuCRE": ["capsule", "K1/K2 hypervirulence in some lineages"],
            "Abaum": ["biofilm", "OprD-like porin loss"],
            "Paer": ["MexAB-OprM efflux", "AmpC inducible", "alginate biofilm"],
            "VRE": ["van operon", "intrinsic cephalosporin tolerance"],
            "NGono": ["penA mosaic", "porin loss", "IS elements"],
        }.get(pathogen, []),
        "first_line_therapy": {
            "MRSA": "vancomycin + ceftaroline backup",
            "Mtb": "RIPE (rifampin/INH/PZA/EMB)",
            "EColi-CRE": "ceftaz-avi or meropenem-vaborbactam",
            "KpneuCRE": "ceftaz-avi or aztreonam-avi",
            "Abaum": "sulbactam-durlobactam",
            "Paer": "ceftolozane-tazo or cefiderocol",
            "VRE": "linezolid or daptomycin",
            "NGono": "ceftriaxone IM",
        }[pathogen],
        "common_syndromes": {
            "MRSA": ["SSTI", "bacteremia", "endocarditis", "osteomyelitis"],
            "Mtb": ["pulmonary TB", "miliary", "extrapulmonary"],
            "EColi-CRE": ["UTI", "bacteremia", "intra-abdominal"],
            "KpneuCRE": ["pneumonia", "UTI", "liver abscess"],
            "Abaum": ["VAP", "wound infection", "bacteremia"],
            "Paer": ["VAP", "CF lung", "burn wound"],
            "VRE": ["bacteremia in immunocompromised", "endocarditis"],
            "NGono": ["urethritis", "PID", "DGI"],
        }[pathogen],
        "clinical_context": (
            f"{PATHOGEN_FULL[pathogen]} is a {'WHO priority' if pathogen in ['MRSA','Mtb','EColi-CRE','KpneuCRE','Abaum','Paer'] else 'critical'} "
            f"AMR pathogen."),
    }


def res_predict_admet(rng, smiles):
    mw = rng.uniform(180, 600)
    logp = rng.gauss(2.5, 1.5)
    tpsa = rng.uniform(40, 160)
    hbd = rng.randint(0, 5)
    hba = rng.randint(2, 10)
    rb = rng.randint(2, 12)
    ar = rng.randint(0, 4)
    lip_v = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    veber = (rb <= 10 and tpsa <= 140)
    bbb = (logp >= 1.5 and tpsa <= 90 and mw <= 450)
    bioav = max(0.0, min(1.0, 0.55 + (3 - lip_v) * 0.1 - (rb / 30)))
    return {
        "smiles": smiles,
        "mw": _round(mw, 2),
        "logp": _round(logp, 2),
        "tpsa": _round(tpsa, 2),
        "hbd": hbd,
        "hba": hba,
        "rotatable_bonds": rb,
        "aromatic_rings": ar,
        "lipinski_violations": lip_v,
        "veber_pass": veber,
        "bbb_likely": bbb,
        "bioavailability_score": _round(bioav, 3),
        "cyp_3a4_substrate_likely": rng.random() < 0.35,
        "metabolic_concerns": (
            ["CYP3A4 substrate"] if logp > 4 else []
        ) + (["aromatic amine"] if rng.random() < 0.05 else []),
        "interpretation": (
            f"MW={mw:.0f}, logP={logp:.1f}, TPSA={tpsa:.0f}; "
            f"Lipinski violations={lip_v}; Veber={'pass' if veber else 'fail'}; "
            f"oral bioavailability score≈{bioav:.2f}."),
    }


def res_predict_hemolysis(rng, smiles):
    score = rng.uniform(0, 1)
    risk = "low" if score < 0.3 else ("medium" if score < 0.7 else "high")
    return {
        "smiles": smiles,
        "safety_score": _round(score, 3),
        "risk_class": risk,
        "confidence": _round(rng.uniform(0.5, 0.9), 3),
        "interpretation": (f"Predicted hemolysis risk={risk} (score={score:.2f}); "
                           f"{'OK for development' if risk=='low' else 'flag for in vitro RBC assay'}."),
        "predictor": "xgboost_dbaasp_hemolysis_v1",
    }


def res_score_molecule(rng, smiles, target_pathogen):
    components = {
        "mic": _round(rng.uniform(0, 1), 3),
        "admet": _round(rng.uniform(0.3, 1.0), 3),
        "novelty": _round(rng.uniform(0, 1), 3),
        "synth": _round(rng.uniform(0.2, 1.0), 3),
        "hemolysis": _round(rng.uniform(0.2, 1.0), 3),
    }
    composite = _round(sum(components.values()) / len(components), 3)
    weakest = min(components, key=components.get)
    strongest = max(components, key=components.get)
    return {
        "smiles": smiles,
        "target_pathogen": target_pathogen,
        "components": components,
        "composite": composite,
        "weakest": weakest,
        "strongest": strongest,
    }


def res_estimate_synth_cost(rng, smiles):
    cost = rng.choice([20, 50, 120, 300, 850, 2500])
    cls = "easy" if cost < 100 else ("moderate" if cost < 500 else "hard")
    return {
        "smiles": smiles,
        "cost_usd_per_g_lab_scale": cost,
        "cost_class": cls,
        "confidence": _round(rng.uniform(0.4, 0.85), 3),
        "interpretation": f"Estimated lab-scale synthesis cost ${cost}/g (class={cls}).",
    }


def res_predict_synthesis_route(rng, target_smiles):
    sa = _round(rng.uniform(2.0, 6.0), 2)
    steps = rng.randint(2, 8)
    cost = round(rng.uniform(60, 1200))
    return {
        "target_smiles": target_smiles,
        "sa_score": sa,
        "estimated_steps": steps,
        "estimated_cost_usd_per_g": cost,
        "confidence_route_found": _round(rng.uniform(0.5, 0.95), 3),
        "backend": "aizynthfinder_uspto_corpus",
        "interpretation": f"SA={sa}, ~{steps} steps to synthesize.",
        "steps": [
            {"step": i+1, "transform": rng.choice(["amide_coupling", "Suzuki", "SNAr", "reductive_amination"])}
            for i in range(steps)
        ],
    }


def res_predict_binding_affinity(rng, smiles, target):
    dg = rng.gauss(-7.0, 2.0)
    pkd = -dg / 1.36
    cls = "tight" if dg < -8 else ("moderate" if dg < -6 else "weak")
    return {
        "smiles": smiles,
        "target": target,
        "delta_g_kcal_mol": _round(dg, 2),
        "pkd_predicted": _round(pkd, 2),
        "affinity_class": cls,
        "confidence": _round(rng.uniform(0.4, 0.9), 3),
        "interpretation": f"ΔG={dg:.1f} kcal/mol → pKd≈{pkd:.1f} ({cls} binder).",
        "backend": "boltz2",
    }


def res_dock_against_target(rng, smiles, pdb_id):
    n_poses = rng.randint(3, 8)
    poses = [
        {"rank": i+1, "score": _round(rng.gauss(-7, 1.5), 2),
         "rmsd": _round(rng.uniform(0.3, 2.0), 2)}
        for i in range(n_poses)
    ]
    best = min(poses, key=lambda p: p["score"])
    return {
        "smiles": smiles,
        "pdb_id": pdb_id,
        "poses": poses,
        "best_score": best["score"],
        "best_rmsd": best["rmsd"],
        "backend": "smina_vina2",
        "interpretation": f"Best dock score {best['score']} kcal/mol on {pdb_id}.",
        "pose_download_url": f"local://docks/{pdb_id}_{rng.randint(1000,9999)}.sdf",
    }


def res_propose_pocket_aware(rng, target_pdb, pocket_class, smiles_pool):
    n = rng.randint(3, 8)
    proposals = [
        {"smiles": rng.choice(smiles_pool),
         "score": _round(rng.uniform(0.4, 0.9), 3),
         "rationale": f"matches {pocket_class} pharmacophore"}
        for _ in range(n)
    ]
    return {
        "target_pdb": target_pdb,
        "pocket_class": pocket_class,
        "proposals": proposals,
        "backend": "moldqn+pharmacophore",
        "interpretation": f"{n} proposals scored against {target_pdb} {pocket_class} pocket.",
    }


def res_compare_molecules(rng, a, b):
    sim = _round(rng.uniform(0.2, 0.95), 3)
    return {
        "smiles_a": a, "smiles_b": b,
        "tanimoto_similarity": sim,
        "same_scaffold": sim > 0.6,
        "mw_delta": _round(rng.gauss(0, 50), 2),
        "logp_delta": _round(rng.gauss(0, 1.0), 2),
        "hbd_delta": rng.randint(-2, 2),
        "hba_delta": rng.randint(-3, 3),
        "qed_delta": _round(rng.gauss(0, 0.15), 3),
        "composite_delta": _round(rng.gauss(0, 0.3), 3),
        "interpretation": f"Tanimoto={sim:.2f}; {'analogs' if sim>0.6 else 'distinct'}.",
    }


def res_explain_mechanism(rng, smiles):
    cls = rng.choice(["beta-lactam", "fluoroquinolone", "aminoglycoside", "macrolide",
                      "glycopeptide", "oxazolidinone", "tetracycline", "peptide"])
    return {
        "smiles": smiles,
        "inferred_class": cls,
        "mechanism_narrative": (f"Likely {cls}: SAR fits the canonical pharmacophore."),
        "resistance_concerns": rng.choice([
            "PBP target — mecA-class escape",
            "DNA gyrase — gyrA-S91F escape",
            "30S ribosome — 16S rRNA methylation",
            "23S ribosome — Erm methylation",
            "cell wall — vanA acquired",
        ]),
    }


def res_find_target_structure(rng, pathogen):
    pdb_list = PDB_BY_PATHOGEN.get(pathogen, ["1ABC"])
    targets = [
        {"pdb_id": p, "target_name": rng.choice(["PBP2a", "GyrA", "RpoB", "InhA", "KPC", "OXA-23", "VanA", "PBP3"]),
         "resolution_A": _round(rng.uniform(1.5, 3.0), 2)}
        for p in pdb_list
    ]
    return {
        "pathogen": pathogen,
        "targets": targets,
        "primary_target": targets[0],
        "interpretation": f"{len(targets)} clinically-relevant targets cataloged for {pathogen}.",
    }


def res_get_drug_history(rng, drug_name):
    return {
        "drug_name": drug_name,
        "drug_class": rng.choice(["beta-lactam", "fluoroquinolone", "macrolide", "glycopeptide"]),
        "moa": "cell-wall synthesis inhibitor",
        "year_approved": rng.randint(1960, 2024),
        "discoverer": rng.choice(["Pfizer", "Merck", "Cubist", "Achaogen", "Spero"]),
        "scaffold_origin": rng.choice(["natural product", "rational design", "scaffold hop"]),
        "primary_targets": ["PBP3", "PBP2a"],
        "key_trials": ["NCT01234567", "NCT07654321"],
        "notable": "FDA approved with QIDP designation",
        "found": True,
    }


def res_search_literature(rng, query):
    n = rng.randint(3, 8)
    papers = [
        {"pmid": f"PMID:{rng.randint(20000000, 39000000)}",
         "title": f"Activity of {rng.choice(['novel beta-lactam','peptide-conjugate','nano-enabled'])} compound on AMR pathogens",
         "year": rng.randint(2018, 2026),
         "abstract_snippet": "We report MIC values consistent with mid-nM activity..."}
        for _ in range(n)
    ]
    return {
        "query": query,
        "papers": papers,
        "backend": "pubmed_via_entrez",
        "interpretation": f"{n} papers retrieved.",
    }


def res_find_active_against_mdr(rng, pathogens):
    drugs = [
        {"name": rng.choice(["ceftaz-avi", "ceftolozane-tazo", "sulbactam-durlobactam", "cefiderocol",
                              "tedizolid", "delafloxacin", "eravacycline"]),
         "mic_range": f"{rng.uniform(0.06, 8.0):.2f}-{rng.uniform(8, 64):.0f} µg/mL",
         "spectrum": rng.sample(pathogens, min(2, len(pathogens)))}
        for _ in range(5)
    ]
    return {
        "pathogens": pathogens,
        "drugs": drugs,
        "summary": f"5 drugs with measured activity vs {', '.join(pathogens)}.",
    }


def res_predict_resistance_escape(rng, smiles, pathogen):
    classes = DRUG_CLASS_BY_RESISTOME.get(pathogen, [("beta-lactam", ["mecA"])])
    cls, genes = rng.choice(classes)
    n = rng.randint(2, 5)
    escapes = [
        {"gene": rng.choice(genes), "mutation": rng.choice(["S531L", "H526Y", "D516V", "A90V", "S91F", "T315I"]),
         "fold_change": rng.choice([4, 8, 16, 32, 64, 128])}
        for _ in range(n)
    ]
    likely_escape = sum(1 for e in escapes if e["fold_change"] >= 16)
    return {
        "smiles": smiles, "pathogen": pathogen, "drug_class": cls,
        "escape_mutations": escapes,
        "summary": f"{n} likely escape mutations modeled for {cls} class.",
        "red_team_verdict": "high-risk" if likely_escape >= 3 else ("moderate-risk" if likely_escape >= 1 else "low-risk"),
    }


def res_predict_complex_structure(rng, smiles, target_pdb_id):
    pose_count = rng.randint(2, 5)
    poses = [
        {"rank": i+1,
         "ipTM": _round(rng.uniform(0.3, 0.85), 3),
         "pTM": _round(rng.uniform(0.4, 0.9), 3),
         "ligand_RMSD": _round(rng.uniform(0.5, 4.0), 2)}
        for i in range(pose_count)
    ]
    affinity = _round(rng.uniform(-10.5, -5.5), 2)
    return {
        "smiles": smiles, "target_pdb_id": target_pdb_id,
        "target_name": rng.choice(["PBP2a", "GyrA", "RpoB", "InhA", "KPC-2"]),
        "poses": poses,
        "affinity": {"delta_g_kcal_mol": affinity, "pkd_predicted": _round(-affinity/1.36, 2)},
        "backend": "boltz2",
        "interpretation": f"Best ipTM={poses[0]['ipTM']}, ΔG={affinity} kcal/mol.",
        "download_url": f"local://complexes/{target_pdb_id}_{rng.randint(1000,9999)}.cif",
    }


def res_find_similar_drugs(rng, query_smiles):
    matches = [
        {"name": f"CHEMBL{rng.randint(100000, 999999)}",
         "smiles": rng.choice(["CC(=O)O", "OCCN", "c1ccccc1"]),
         "similarity": _round(rng.uniform(0.5, 0.92), 3)}
        for _ in range(rng.randint(3, 8))
    ]
    return {
        "query_smiles": query_smiles,
        "similarity_metric": "morgan_fp_tanimoto",
        "matches": matches,
        "interpretation": f"{len(matches)} similar drugs in known-antibiotic index (Tanimoto≥0.5).",
    }


def res_optimize_iteratively(rng, starting_smiles, target_pathogen, objective):
    n = rng.randint(4, 10)
    traj = []
    composite = 0.4
    for i in range(n):
        composite += rng.uniform(-0.05, 0.12)
        composite = max(0, min(1.0, composite))
        traj.append({"iter": i+1,
                     "smiles": f"{starting_smiles}_v{i+1}",
                     "composite": _round(composite, 3),
                     "delta": _round(rng.gauss(0.05, 0.05), 3)})
    best = max(traj, key=lambda t: t["composite"])
    return {
        "starting_smiles": starting_smiles,
        "target_pathogen": target_pathogen,
        "objective": objective,
        "trajectory": traj,
        "best_smiles": best["smiles"],
        "best_composite": best["composite"],
        "interpretation": f"Optimization {n} iters; composite {traj[0]['composite']}→{best['composite']}.",
    }


def res_scaffold_hop(rng, source_smiles):
    alts = [
        {"smiles": f"{source_smiles}_hop{i+1}",
         "scaffold_class": rng.choice(["pyridine→pyrimidine", "phenyl→thiazole", "ester→amide"]),
         "score": _round(rng.uniform(0.3, 0.85), 3)}
        for i in range(rng.randint(3, 7))
    ]
    return {
        "source_smiles": source_smiles,
        "alternatives": alts,
        "bioisostere_classes_tried": ["heteroaryl-swap", "amide-bioisostere", "ring-contraction"],
        "backend": "rule_based+matched_pair_db",
        "interpretation": f"{len(alts)} scaffold-hop alternatives proposed.",
    }


def res_transform_structure(rng, source_smiles):
    op = rng.choice(["add_methyl", "add_fluorine", "remove_OH", "ring_expand", "amide_to_amine"])
    return {
        "source_smiles": source_smiles,
        "op": op,
        "op_description": f"Apply {op} transformation",
        "op_rationale": "improve metabolic stability",
        "products": [f"{source_smiles}_{op}"],
        "success": True,
        "note": "1 product, sanitized by RDKit",
    }


def res_render_3d_scene(rng, structure, ligand_smiles):
    return {
        "structure": structure,
        "ligand_smiles": ligand_smiles,
        "style": "cartoon+stick",
        "color_scheme": "spectrum",
        "highlight_residues": [f"{rng.choice(['SER','HIS','LYS','ASP','GLU'])}{rng.randint(50,500)}" for _ in range(3)],
        "camera_preset": "active_site_close",
        "annotations": ["catalytic triad", "binding pocket"],
    }


def res_execute_python(rng, code_summary):
    return {
        "stdout": f"computed result for {code_summary}",
        "stderr": "",
        "return_value": _round(rng.uniform(0, 100), 3),
        "success": True,
        "timed_out": False,
    }


def _continuation(tool_name, result, pathogen_label):
    """Templated reasoning over the tool result. Gives Designer a continuation."""
    if tool_name == "predict_mic_pathogen":
        log_mic = result["log_mic_predicted"]
        if log_mic < 0.7:
            return (f"Reading the result: log10(MIC)={log_mic} → MIC≈{result['mic_ug_ml']} µg/mL "
                    f"is in the active range for {pathogen_label}. Confidence "
                    f"{result['confidence']}. Reward={result['reward']}. Proceed to "
                    f"`predict_admet` to check developability.")
        else:
            return (f"log10(MIC)={log_mic} sits at the inactive boundary for "
                    f"{pathogen_label}. Will route this candidate to `scaffold_hop` "
                    f"for a structural revision before re-scoring.")
    if tool_name == "predict_admet":
        v = result["lipinski_violations"]
        if v <= 1 and result["bioavailability_score"] >= 0.55:
            return (f"ADMET clean: Lipinski violations={v}, "
                    f"bioavailability score={result['bioavailability_score']}. "
                    f"Pass to `predict_hemolysis` for safety screen.")
        else:
            return (f"ADMET fail-state: Lipinski violations={v}, "
                    f"bioavailability score={result['bioavailability_score']}. "
                    f"Routing to `transform_structure` to drop logP / HBD.")
    if tool_name == "score_molecule":
        return (f"Composite={result['composite']}; weakest pillar={result['weakest']}, "
                f"strongest={result['strongest']}. Will spend the next iteration "
                f"strengthening the weakest pillar.")
    if tool_name == "predict_hemolysis":
        return (f"Hemolysis risk={result['risk_class']} "
                f"(safety_score={result['safety_score']}). "
                f"{'Approved for in silico panel completion.' if result['risk_class']=='low' else 'Flagging for in vitro RBC assay before commit.'}")
    if tool_name == "estimate_synth_cost":
        return (f"Cost estimate ${result['cost_usd_per_g_lab_scale']}/g "
                f"({result['cost_class']}). "
                f"{'Affordable for medchem.' if result['cost_class']=='easy' else 'Will probe cheaper alternatives via scaffold_hop.'}")
    if tool_name == "check_resistance_genes":
        return (f"{pathogen_label} resistance for {result['drug_class_inferred']} class "
                f"is mediated by {', '.join(result['relevant_genes'])}. Designer will "
                f"avoid scaffolds whose pharmacophore depends on any of these.")
    if tool_name == "get_pathogen_resistome":
        return (f"Resistome briefing absorbed. Primary first-line: "
                f"{result['first_line_therapy']}. Will design beyond this class to "
                f"avoid cross-resistance.")
    if tool_name == "predict_binding_affinity":
        return (f"ΔG={result['delta_g_kcal_mol']} kcal/mol → "
                f"pKd≈{result['pkd_predicted']} ({result['affinity_class']}). "
                f"{'Strong enough to advance.' if result['affinity_class']=='tight' else 'Below tight-binder threshold; iterate.'}")
    if tool_name == "dock_against_target":
        return (f"Best dock score={result['best_score']} kcal/mol with RMSD "
                f"{result['best_rmsd']} Å. Pose looks productive — pulling top "
                f"residues into the rationale.")
    if tool_name == "predict_synthesis_route":
        return (f"AizynthFinder returns SA={result['sa_score']}, "
                f"{result['estimated_steps']} steps, ${result['estimated_cost_usd_per_g']}/g. "
                f"Confidence={result['confidence_route_found']}. Synthesizable.")
    if tool_name == "compare_molecules":
        if result["tanimoto_similarity"] > 0.85:
            return (f"Tanimoto={result['tanimoto_similarity']} — too similar to known "
                    f"corpus, novelty issue. Scaffold-hopping required.")
        return (f"Tanimoto={result['tanimoto_similarity']} — sufficient novelty "
                f"vs reference. Scaffold delta acceptable.")
    if tool_name == "find_similar_drugs":
        return (f"{len(result['matches'])} similar drugs in known-antibiotic index. "
                f"Top match similarity={result['matches'][0]['similarity']}. "
                f"Cross-checking IP / patent overlap.")
    if tool_name == "predict_resistance_escape":
        return (f"Red-team verdict: {result['red_team_verdict']}. "
                f"{len(result['escape_mutations'])} likely escape mutations modeled. "
                f"Designer will iterate on the {result['drug_class']} backbone to "
                f"reduce escape pressure.")
    if tool_name == "explain_mechanism":
        return (f"Inferred class: {result['inferred_class']}. "
                f"Resistance concern: {result['resistance_concerns']}. Routing "
                f"the design to evade the named mechanism.")
    if tool_name == "find_target_structure":
        return (f"Primary target: {result['primary_target']['target_name']} "
                f"(PDB: {result['primary_target']['pdb_id']}, "
                f"{result['primary_target']['resolution_A']} Å). "
                f"Will pass to `propose_pocket_aware`.")
    if tool_name == "get_drug_history":
        return (f"{result['drug_name']} ({result['drug_class']}, approved "
                f"{result['year_approved']} by {result['discoverer']}). "
                f"Scaffold origin: {result['scaffold_origin']}. Useful as anchor "
                f"for analog series.")
    if tool_name == "search_literature":
        return (f"{len(result['papers'])} papers retrieved. Most recent: "
                f"{max(p['year'] for p in result['papers'])}. Pulling activity "
                f"data into the design rationale.")
    if tool_name == "find_active_against_mdr":
        return (f"{len(result['drugs'])} late-stage drugs with measured activity. "
                f"Pulling the best MIC ranges into the comparator panel.")
    if tool_name == "predict_complex_structure":
        return (f"Boltz-2 returns ipTM={result['poses'][0]['ipTM']}, "
                f"ΔG={result['affinity']['delta_g_kcal_mol']} kcal/mol. "
                f"3D pose stored at {result['download_url']}.")
    if tool_name == "propose_pocket_aware":
        return (f"{len(result['proposals'])} proposals generated for the "
                f"{result['pocket_class']} pocket of {result['target_pdb']}. "
                f"Top candidate score={max(p['score'] for p in result['proposals'])}.")
    if tool_name == "scaffold_hop":
        return (f"{len(result['alternatives'])} scaffold-hop alternatives generated. "
                f"Best score={max(a['score'] for a in result['alternatives'])}. "
                f"Routing top hits to `predict_mic_pathogen`.")
    if tool_name == "transform_structure":
        return (f"Applied {result['op']} → {len(result['products'])} product(s). "
                f"Will re-score the top product.")
    if tool_name == "render_3d_scene":
        return (f"3D scene rendered with {len(result['highlight_residues'])} "
                f"highlighted residues. Visualization OK.")
    if tool_name == "execute_python":
        return (f"Python returned {result['return_value']}. {'OK.' if result['success'] else 'Re-run.'}")
    return "Result captured. Continuing."


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------
TOOLS_PLAN = [
    # (tool_name, n_traces, args_fn, result_fn, optional_pathogen_use)
    ("predict_mic_pathogen", 200),
    ("check_resistance_genes", 200),
    ("get_pathogen_resistome", 150),
    ("predict_admet", 200),
    ("predict_hemolysis", 150),
    ("score_molecule", 200),
    ("estimate_synth_cost", 150),
    ("predict_synthesis_route", 150),
    ("predict_binding_affinity", 200),
    ("dock_against_target", 200),
    ("compare_molecules", 150),
    ("explain_mechanism", 150),
    ("find_target_structure", 150),
    ("get_drug_history", 100),
    ("search_literature", 100),
    ("find_active_against_mdr", 150),
    ("predict_resistance_escape", 200),
    ("predict_complex_structure", 200),
    ("find_similar_drugs", 150),
    ("optimize_iteratively", 150),
    ("scaffold_hop", 150),
    ("transform_structure", 150),
    ("propose_pocket_aware", 150),
    ("render_3d_scene", 100),
    ("execute_python", 100),
]


def synth_one_trace(rng, tool_name) -> dict:
    pathogen = rng.choice(PATHOGENS)
    smiles_pool = SMILES_LIB.get(pathogen) or ["CC(=O)O"]
    smiles = rng.choice(smiles_pool)
    pathogen_label = PATHOGEN_FULL[pathogen]

    # Build args per tool
    if tool_name == "predict_mic_pathogen":
        args = {"smiles": smiles, "pathogen": pathogen}
        result = res_predict_mic_pathogen(rng, smiles, pathogen)
    elif tool_name == "check_resistance_genes":
        drug_class = rng.choice(["beta-lactam", "fluoroquinolone", "macrolide", "aminoglycoside"])
        args = {"pathogen": pathogen, "drug_class_or_smiles": drug_class}
        result = res_check_resistance_genes(rng, pathogen, drug_class)
    elif tool_name == "get_pathogen_resistome":
        args = {"pathogen": pathogen}
        result = res_get_pathogen_resistome(rng, pathogen)
    elif tool_name == "predict_admet":
        args = {"smiles": smiles}
        result = res_predict_admet(rng, smiles)
    elif tool_name == "predict_hemolysis":
        args = {"smiles": smiles}
        result = res_predict_hemolysis(rng, smiles)
    elif tool_name == "score_molecule":
        args = {"smiles": smiles, "target_pathogen": pathogen}
        result = res_score_molecule(rng, smiles, pathogen)
    elif tool_name == "estimate_synth_cost":
        args = {"smiles": smiles}
        result = res_estimate_synth_cost(rng, smiles)
    elif tool_name == "predict_synthesis_route":
        args = {"target_smiles": smiles}
        result = res_predict_synthesis_route(rng, smiles)
    elif tool_name == "predict_binding_affinity":
        target = rng.choice(["PBP2a", "GyrA", "RpoB", "InhA", "KPC", "PBP3"])
        args = {"smiles": smiles, "target": target}
        result = res_predict_binding_affinity(rng, smiles, target)
    elif tool_name == "dock_against_target":
        pdb = rng.choice(PDB_BY_PATHOGEN[pathogen])
        args = {"smiles": smiles, "pdb_id": pdb}
        result = res_dock_against_target(rng, smiles, pdb)
    elif tool_name == "compare_molecules":
        a, b = rng.sample(SMILES_LIB.get(pathogen) or ["CC(=O)O", "CCO"], 1)[0], smiles
        if a == b:
            b = "CCN"
        args = {"smiles_a": a, "smiles_b": b}
        result = res_compare_molecules(rng, a, b)
    elif tool_name == "explain_mechanism":
        args = {"smiles": smiles}
        result = res_explain_mechanism(rng, smiles)
    elif tool_name == "find_target_structure":
        args = {"pathogen": pathogen}
        result = res_find_target_structure(rng, pathogen)
    elif tool_name == "get_drug_history":
        drug = rng.choice(["vancomycin", "ceftaroline", "rifampin", "linezolid", "ceftolozane"])
        args = {"drug_name": drug}
        result = res_get_drug_history(rng, drug)
    elif tool_name == "search_literature":
        q = rng.choice([f"{pathogen} novel beta-lactam", f"{pathogen} resistance mechanisms",
                        f"{pathogen} clinical trial 2024"])
        args = {"query": q}
        result = res_search_literature(rng, q)
    elif tool_name == "find_active_against_mdr":
        args = {"pathogens": [pathogen]}
        result = res_find_active_against_mdr(rng, [pathogen])
    elif tool_name == "predict_resistance_escape":
        args = {"smiles": smiles, "pathogen": pathogen}
        result = res_predict_resistance_escape(rng, smiles, pathogen)
    elif tool_name == "predict_complex_structure":
        pdb = rng.choice(PDB_BY_PATHOGEN[pathogen])
        args = {"smiles": smiles, "target_pdb_id": pdb}
        result = res_predict_complex_structure(rng, smiles, pdb)
    elif tool_name == "find_similar_drugs":
        args = {"query_smiles": smiles}
        result = res_find_similar_drugs(rng, smiles)
    elif tool_name == "optimize_iteratively":
        obj = rng.choice(["lowest_mic", "best_admet", "novelty_max", "pareto"])
        args = {"seed_smiles": smiles, "target_pathogen": pathogen, "objective": obj, "max_iters": 8}
        result = res_optimize_iteratively(rng, smiles, pathogen, obj)
    elif tool_name == "scaffold_hop":
        args = {"smiles": smiles, "n_proposals": 6}
        result = res_scaffold_hop(rng, smiles)
    elif tool_name == "transform_structure":
        op = rng.choice(["add_methyl", "add_fluorine", "remove_OH", "ring_expand"])
        args = {"smiles": smiles, "op": op}
        result = res_transform_structure(rng, smiles)
    elif tool_name == "propose_pocket_aware":
        pdb = rng.choice(PDB_BY_PATHOGEN[pathogen])
        pocket = rng.choice(["active_site", "allosteric", "interface"])
        args = {"target_pdb": pdb, "pocket_class": pocket}
        smiles_pool_local = SMILES_LIB.get(pathogen) or ["CC(=O)O"]
        result = res_propose_pocket_aware(rng, pdb, pocket, smiles_pool_local)
    elif tool_name == "render_3d_scene":
        pdb = rng.choice(PDB_BY_PATHOGEN[pathogen])
        args = {"structure": pdb, "ligand_smiles": smiles, "style": "cartoon+stick"}
        result = res_render_3d_scene(rng, pdb, smiles)
    elif tool_name == "execute_python":
        code = "n_active = sum(1 for r in batch if r.composite > 0.7)"
        args = {"code": code}
        result = res_execute_python(rng, "active count")
    else:
        raise ValueError(tool_name)

    continuation = _continuation(tool_name, result, pathogen_label)

    msgs = [
        {"role": "system", "content":
            "You are the Lysos Designer agent. You call tools and reason over the "
            "structured JSON results. Each tool's output schema is enforced. After "
            "every tool result, summarise the salient fields and decide the next "
            "step."},
        {"role": "user", "content":
            f"Designer task: investigate a candidate against {pathogen_label} ({pathogen})."},
        {"role": "assistant", "content":
            (f"<tool_call>\n"
             f"  name: {tool_name}\n"
             f"  args: {json.dumps(args)}\n"
             f"</tool_call>")},
        {"role": "tool", "name": tool_name, "content": json.dumps(result)},
        {"role": "assistant", "content": continuation},
    ]
    return {
        "task": "tool_call_with_result",
        "tool": tool_name,
        "pathogen": pathogen,
        "messages": msgs,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0xB1ADE_42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    counts = {}
    if OUT.exists(): OUT.unlink()
    with open(OUT, "a") as f:
        for tool_name, n in TOOLS_PLAN:
            for _ in range(n):
                row = synth_one_trace(rng, tool_name)
                f.write(json.dumps(row) + "\n")
            counts[tool_name] = n

    total = sum(counts.values())
    print(f"\nTotal tool-result traces: {total:,}")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:32s} {v:>5,}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
