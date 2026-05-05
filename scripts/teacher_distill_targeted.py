"""Targeted teacher distillation — niche gaps after broad layers.

6 categories:
  A. pdb_pocket_deep_dive       15 PDBs x 250 = 3,750  per-PDB residue + ligand interaction
  B. mutation_deep_dive          30 mutations x 150 = 4,500  per-mutation molecular reasoning
  C. three_way_dialogue          2,500  Designer<->Critic<->Strategist with handoffs
  D. chemistry_self_correction   2,000  Designer catches own mistake mid-trace
  E. indication_deep_dive        12 indications x 200 = 2,400  per-indication design
  F. tool_call_chain             2,000  multi-tool sequences solving one problem

Total: ~17,150 traces

Run:
  /tmp/lysos_venv/bin/python scripts/teacher_distill_targeted.py

Output: data/synthetic/agentic_teacher_distill_targeted.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic" / "agentic_teacher_distill_targeted.jsonl"

PATHOGENS = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE", "Abaum", "Paer", "VRE", "NGono"]

SYS = (
    "You are the Lysos drug-design team — Designer, Critic, Strategist agents "
    "collaborating with deep AMR knowledge. Use real PDB residues, real escape "
    "mutations with molecular detail, and structured handoff envelopes. "
    "Concrete > abstract."
)


# ============================================================================
# A. Per-PDB pocket deep dives
# ============================================================================
PDB_POCKETS = {
    "1VQQ": {  # MRSA / PBP2a apo
        "pathogen": "MRSA", "target": "PBP2a apo",
        "key_residues": [
            ("Ser-403", "catalytic transpeptidase serine; nucleophilic attack on β-lactam carbonyl"),
            ("Lys-406", "general base — abstracts proton from Ser-403 to enable acylation"),
            ("Asn-464", "positions Ser-403 via H-bond network"),
            ("Tyr-446", "aromatic stacking with bicyclic β-lactam"),
            ("Met-641", "hairpin gate that constricts the active site in apo state"),
        ],
        "geometry": "constricted active-site cleft (~6Å narrower than PBP2 of MSSA); the β1-β2 loop occludes substrate entry. Allosteric site sits ~60Å away on the opposite face.",
        "design_notes": "Engaging Ser-403 directly is geometrically blocked in apo PBP2a. Ceftaroline solves this by binding the allosteric site first (via aminothiadiazole-oxime tail), causing M641 hairpin displacement and opening the active site.",
    },
    "5M18": {
        "pathogen": "MRSA", "target": "PBP2a + ceftaroline complex",
        "key_residues": [
            ("Ser-403", "covalently acylated by ceftaroline β-lactam"),
            ("Met-641", "displaced 1.4Å from apo state — gate now open"),
            ("Asn-464", "stabilizes acyl-enzyme intermediate"),
            ("E239", "allosteric residue; backbone NH H-bonds the oxime"),
        ],
        "geometry": "open conformation. Active site cleft expanded by ~1.4 Å vs apo. C7 amide of ceftaroline contacts allosteric pocket; C3 thiopyridyl reaches into catalytic site.",
        "design_notes": "Use the C7 amide → allosteric tail vector to design 5GC analogs. Extending the thiopyridyl one carbon (homologation) probes deeper allosteric contact.",
    },
    "2NSD": {
        "pathogen": "Mtb", "target": "InhA + INH-NAD adduct",
        "key_residues": [
            ("Tyr-158", "key catalytic residue; H-bonds INH-NAD adduct"),
            ("Lys-165", "stabilizes substrate via salt bridge"),
            ("Phe-149", "hydrophobic pocket for NAD ribose"),
            ("Met-103", "lines the substrate-binding groove"),
            ("Pro-193", "forms hydrophobic floor of binding cleft"),
        ],
        "geometry": "NAD-cofactor-binding cleft + substrate pocket. INH-NAD adduct occupies both — the isonicotinoyl group projects into the substrate pocket while the NAD adenine is in the cofactor cleft.",
        "design_notes": "Triclosan-class direct InhA inhibitors (no katG activation) bind the substrate pocket only; bypass the katG resistance issue. Diphenyl ether scaffold occupies the same Phe-149/Met-103 hydrophobic pocket.",
    },
    "5UAQ": {
        "pathogen": "Mtb", "target": "RpoB + rifampin",
        "key_residues": [
            ("Ser-456 (canonical S531 numbering, S531L most common R mutation)", "key H-bond acceptor for rifampin naphthol"),
            ("His-451 (H526 numbering)", "stacks with rifampin chromone"),
            ("Asp-441 (D516)", "salt bridge to rifampin amino group"),
            ("Gln-435 (Q510)", "H-bond to ansa bridge"),
        ],
        "geometry": "rifampin binds in the RNA exit channel of RNA polymerase, blocking nascent RNA elongation. The 81-bp RRDR encodes residues 507-533 (E. coli numbering 426-452 — Mtb 507-533).",
        "design_notes": "Single point mutations in any of S531/H526/D516 reduce rifampin affinity 100-1000x. Lysos design strategy: extend the ansa bridge to contact residues OUTSIDE the RRDR (e.g., the beta-prime subunit interface), so single point mutation can't escape.",
    },
    "1SJ2": {
        "pathogen": "Mtb", "target": "KatG (catalase-peroxidase)",
        "key_residues": [
            ("His-108", "axial heme ligand"),
            ("Trp-321", "compound I oxidation site"),
            ("Ser-315", "key residue; S315T mutation = INH-R via reduced INH activation"),
            ("Asn-138", "substrate-binding wall"),
            ("Tyr-229", "covalent Trp-Tyr-Met adduct (catalytic)"),
        ],
        "geometry": "heme b prosthetic group with His-108 axial ligand; substrate channel runs perpendicular to heme plane. INH enters via lateral channel, oxidized to isonicotinoyl radical near Trp-321.",
        "design_notes": "S315T narrows the substrate channel — INH activation drops 200x while H2O2 catalysis is preserved. Direct InhA inhibitors (triclosan-class) bypass KatG entirely.",
    },
    "6Q9B": {
        "pathogen": "EColi-CRE", "target": "KPC-2 + avibactam",
        "key_residues": [
            ("Ser-70", "catalytic; covalent attachment to avibactam β-lactam-mimic"),
            ("Lys-73", "general base for Ser-70 nucleophile activation"),
            ("Trp-105", "substrate stacking; key for carbapenem recognition"),
            ("Asn-132", "H-bond to substrate carbonyl"),
            ("Asp-179", "secondary residue; D179Y mutation reduces avibactam binding 10x"),
        ],
        "geometry": "Class A β-lactamase fold; active site cleft accommodates β-lactam ring. Omega loop (residues 164-179) controls substrate specificity.",
        "design_notes": "Avibactam covalently + REVERSIBLY binds Ser-70 — unique among DBOs. KPC-3 D179Y emerged under ceftaz-avi clinical pressure; ~10x reduced avibactam affinity. Lysos design for next-gen DBO: contact residues in the omega loop NOT D179, so D179Y doesn't escape.",
    },
    "5VFA": {
        "pathogen": "KpneuCRE", "target": "KPC-3 (D179Y emerging variant)",
        "key_residues": [
            ("Ser-70", "catalytic"),
            ("Tyr-179", "MUTATION FROM Asp-179 in WT — reduces avibactam affinity"),
            ("Trp-105", "substrate stacking"),
        ],
        "geometry": "same overall fold as KPC-2 but D179Y disrupts the local H-bond network. Avibactam still binds but with ~10x reduced affinity.",
        "design_notes": "Need a DBO variant whose covalent geometry is insensitive to position 179. Recent publications (2024) suggest nacubactam-class with extra polar handle works.",
    },
    "3SPU": {
        "pathogen": "EColi-CRE", "target": "NDM-1 (Zn²⁺ MBL)",
        "key_residues": [
            ("His-116, His-118, His-196 (Zn1 site)", "tetrahedral Zn²⁺ coordination — acts as Lewis acid for water activation"),
            ("Asp-120, Cys-221, His-263 (Zn2 site)", "second Zn²⁺ — stabilizes leaving group"),
            ("Asn-220", "H-bonds substrate carbonyl"),
        ],
        "geometry": "binuclear Zn²⁺ active site; substrate binds across both metals. Class B MBL — fundamentally different mechanism from Class A serine carbapenemases.",
        "design_notes": "Avibactam DOES NOT inhibit MBLs — Zn²⁺ chemistry is orthogonal to Ser-70. Cefiderocol bypasses by entering via TonB-dependent receptors. Future MBL inhibitors: Zn²⁺ chelators, DPA (dipicolinic acid) analogs, taniborbactam (boronate that bridges both Zn²⁺).",
    },
    "3HBR": {
        "pathogen": "EColi-CRE", "target": "OXA-48",
        "key_residues": [
            ("Ser-70", "catalytic"),
            ("Lys-73 (carbamylated)", "general base — REQUIRES CO2 for activity"),
            ("Tyr-211", "lines the substrate channel"),
            ("Trp-105 equivalent", "substrate stacking"),
        ],
        "geometry": "Class D fold; active site requires CO2-mediated Lys-73 carbamylation to activate Ser-70. Unique substrate spectrum: hydrolyzes carbapenems but not extended-spectrum cephalosporins.",
        "design_notes": "DBO inhibitors variable efficacy; durlobactam works (uniquely among DBOs). Avibactam ~partial activity. Lysos design: extend the DBO scaffold with bridge to Tyr-211 contact.",
    },
    "4JF6": {
        "pathogen": "Abaum", "target": "OXA-23",
        "key_residues": [
            ("Ser-79", "catalytic"),
            ("Lys-82 (carbamylated)", "general base — CO2-dependent"),
            ("Trp-104", "substrate stacking"),
            ("Met-211", "hydrophobic floor"),
            ("Phe-110", "aromatic wall"),
        ],
        "geometry": "Class D similar to OXA-48 but with deeper substrate channel; accommodates carbapenems with bulky substituents.",
        "design_notes": "Durlobactam binds covalently to Ser-79; unique among DBOs (avibactam doesn't fit). The sulbactam-durlobactam combo (FDA 2023 for CRAB) exploits this — sulbactam direct PBP3 + durlobactam protects sulbactam from OXA-23 hydrolysis.",
    },
    "3OG7": {
        "pathogen": "Paer", "target": "PBP3",
        "key_residues": [
            ("Ser-294", "catalytic transpeptidase"),
            ("Lys-297", "general base"),
            ("Asn-353", "H-bond to substrate"),
            ("Tyr-409", "aromatic stacking"),
            ("Trp-422", "substrate channel wall"),
        ],
        "geometry": "Pseudomonas-specific PBP3; structurally similar to E. coli PBP3 but with key residue changes that affect substrate selectivity. Active site accommodates ceftolozane's modified side chain.",
        "design_notes": "Ceftolozane has a bulky aminothiadiazolyl side chain that PREVENTS recognition by MexAB-OprM efflux. Lysos design: any new Pseudomonas cephalosporin needs explicit anti-efflux feature.",
    },
    "5O8R": {
        "pathogen": "Paer", "target": "MexAB-OprM efflux complex",
        "key_residues": [
            ("MexB inner-membrane RND transporter", "12 transmembrane helices; substrate binding pocket in periplasmic loops"),
            ("MexA periplasmic adapter", "connects MexB to OprM"),
            ("OprM outer-membrane channel", "trimeric β-barrel"),
        ],
        "geometry": "tripartite efflux pump spanning inner membrane → periplasm → outer membrane. Substrate enters MexB from cytoplasm or periplasm, transported across via proton-motive force, exits through OprM into extracellular space.",
        "design_notes": "Designing scaffolds that ESCAPE MexAB recognition: avoid known substrate features (planar aromatic + cationic + amphiphilic). Add bulky polar groups that don't fit the substrate pocket. Ceftolozane's aminothiadiazolyl tail is the canonical escape feature.",
    },
    "1IOG": {
        "pathogen": "VRE", "target": "VanA D-Ala:D-Lac ligase",
        "key_residues": [
            ("Lys-216", "ATP-binding"),
            ("Glu-294", "metal coordination (Mg²⁺/Mn²⁺)"),
            ("Tyr-216", "stabilizes substrate"),
            ("D-Ala₁ pocket", "first D-alanine binding"),
            ("D-Ala₂/D-Lac₂ pocket", "second binding pocket — KEY: VanA accepts D-Lac instead of D-Ala₂ here"),
        ],
        "geometry": "D-Ala:D-Ala ligase fold (modified). The C-terminal D-Ala-binding pocket has been remodeled in VanA — accepts D-Lac (oxygen-substituted) instead of D-Ala (NH-substituted).",
        "design_notes": "Vancomycin H-bonds with the D-Ala-D-Ala terminal — loses one of five H-bonds when pocket is D-Ala-D-Lac (the one to N-H is replaced by O-H repulsion). Lysos design: re-engineered glycopeptide with modified binding cleft to tolerate D-Lac (oritavancin, telavancin, dalbavancin).",
    },
    "6P58": {
        "pathogen": "NGono", "target": "PBP2 (penA mosaic XXXIV)",
        "key_residues": [
            ("Ser-310", "catalytic"),
            ("Lys-313", "general base"),
            ("Asn-365", "substrate H-bond"),
            ("Phe-504, Pro-552", "key mosaic-XXXIV positions — chimeric segments from commensal Neisseria"),
        ],
        "geometry": "PBP2 with mosaic transpeptidase domain. Wild-type penA binds ceftriaxone at sub-µg/mL; mosaic XXXIV introduces ~30 amino acid changes that reshape the active site, raising ceftriaxone MIC to 0.5-2 mg/L.",
        "design_notes": "Lysos design for ceftriaxone-R NGono: extend C3 substituent to compensate for mosaic-XXXIV pocket changes. Or pivot to GyrB target (zoliflodacin-class).",
    },
    "5N6S": {
        "pathogen": "NGono", "target": "GyrB (zoliflodacin pocket)",
        "key_residues": [
            ("Lys-447", "ATP binding"),
            ("Asp-449", "Mg²⁺ coordination"),
            ("Asn-477", "novel pocket residue contacted by zoliflodacin"),
            ("Glu-466", "secondary contact"),
        ],
        "geometry": "GyrB ATP-binding pocket — distinct from the GyrA quinolone-binding pocket. Type II topoisomerase α₂β₂ heterotetramer.",
        "design_notes": "Zoliflodacin (FDA submitted 2025) is the prototype. Mechanism orthogonal to fluoroquinolones (gyrA target) — so gyrA-S91F + parC-D86N FQ-R doesn't cross-resist. Lysos design: spiropyrimidine class for novel-mechanism NGono drugs.",
    },
    "3ZG0": {
        "pathogen": "MRSA", "target": "PBP2a + ceftaroline (alternative crystal form)",
        "key_residues": [
            ("Ser-403", "covalent acylation"),
            ("Met-641", "hairpin in open state"),
            ("Asn-464", "stabilizes acyl-enzyme"),
        ],
        "geometry": "shows the allosteric site occupancy — ceftaroline aminothiadiazole-oxime engages the allosteric pocket; this conformational change opens the catalytic site for a second molecule to bind Ser-403.",
        "design_notes": "Validates the two-binding-mode hypothesis: allosteric engagement enables catalytic-site acylation. New 5GC analogs should preserve both binding modes.",
    },
}


def trace_pdb_pocket(rng: random.Random) -> dict:
    pdb = rng.choice(list(PDB_POCKETS.keys()))
    p = PDB_POCKETS[pdb]
    user = f"Walk me through the binding pocket of {pdb} ({p['target']} in {p['pathogen']}). Key residues, geometry, design implications."
    asst = (
        f"[PDB Pocket Deep-Dive — {pdb}]:\n\n"
        f"PDB: {pdb}\n"
        f"Pathogen: {p['pathogen']}\n"
        f"Target: {p['target']}\n\n"
        f"KEY RESIDUES (catalytic + binding):\n"
    )
    for res, role in p['key_residues']:
        asst += f"  {res:30s} — {role}\n"
    asst += (
        f"\nPOCKET GEOMETRY:\n  {p['geometry']}\n\n"
        f"DESIGN IMPLICATIONS FOR LYSOS:\n  {p['design_notes']}\n\n"
        f"DECISION: when designing against {p['pathogen']} via {p['target']}, anchor candidates that contact the residues listed above; avoid known escape mutations at the same residues."
    )
    return {
        "task": "teacher_pdb_pocket",
        "pathogen": p['pathogen'],
        "pdb": pdb,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# B. Per-mutation molecular deep dives
# ============================================================================
MUTATIONS = {
    "mecA-N146K": ("MRSA", "PBP2a", "asparagine to lysine at position 146", "introduces a positive charge in the allosteric pocket; disrupts the ceftaroline aminothiadiazole-oxime binding via electrostatic clash. Reduces ceftaroline affinity ~8x. Emerged in clinical case reports 2018-2023."),
    "mecA-E150K": ("MRSA", "PBP2a", "glutamate to lysine at position 150", "charge reversal in allosteric pocket; reduces ceftaroline affinity ~4x. Often co-occurs with N146K."),
    "mecA-E239K": ("MRSA", "PBP2a", "glutamate to lysine at position 239", "disrupts H-bond network around catalytic Ser-403; reduces 5GC binding ~6x."),
    "vanA-acquired": ("MRSA / VRE", "cell wall precursor", "transferable D-Ala:D-Lac ligase", "remodels peptidoglycan precursor terminus from D-Ala-D-Ala to D-Ala-D-Lac; vancomycin loses one of five H-bonds + introduces O-O lone-pair clash; ~1000x reduced vancomycin affinity."),
    "rpoB-S531L": ("Mtb", "RNA polymerase", "serine to leucine at position 531 (Mtb numbering)", "removes the H-bond donor that anchors rifampin's naphthol oxygen; bulky leucine sterically clashes with rifampin chromone. Reduces rifampin binding 100-1000x. Most common rifampin-R mutation in clinical MDR-TB (>80% of cases)."),
    "rpoB-H526Y": ("Mtb", "RNA polymerase", "histidine to tyrosine at position 526", "loss of imidazole side chain that stacks with rifampin chromone; tyrosine OH provides incomplete substitute. ~100x reduced rifampin affinity."),
    "rpoB-D516V": ("Mtb", "RNA polymerase", "aspartate to valine at position 516", "loss of negative charge that salt-bridges rifampin amine; valine is hydrophobic, no electrostatic stabilization. ~50x reduced rifampin affinity."),
    "katG-S315T": ("Mtb", "catalase-peroxidase", "serine to threonine at position 315", "narrows the substrate channel of KatG; INH still enters but activation rate drops 200x — too slow to generate enough INH-NAD adduct in cell. Most common INH-R mutation."),
    "inhA-promoter-15": ("Mtb", "InhA promoter", "C->T at -15 of inhA promoter", "increases InhA transcription 20x; titrates out INH-NAD adduct via target overexpression."),
    "gyrA-A90V": ("Mtb", "DNA gyrase", "alanine to valine at position 90", "bulky valine sterically clashes with FQ in quinolone-binding pocket. Reduces FQ affinity 30x."),
    "gyrA-D94G": ("Mtb", "DNA gyrase", "aspartate to glycine at position 94", "loss of Mg²⁺-coordinating residue critical for FQ activity. Reduces FQ affinity 100x."),
    "KPC-3-D179Y": ("KpneuCRE", "KPC-3 carbapenemase", "aspartate to tyrosine at position 179", "disrupts H-bond network between avibactam carbonyl and the omega loop; reduces avibactam binding ~10x. Selected under ceftaz-avi clinical pressure 2018+."),
    "KPC-31": ("KpneuCRE", "KPC variant", "D179Y + secondary mutations", "second-generation ceftaz-avi-R variant. Variable activity vs aztreonam-avi."),
    "OXA-23-WT": ("Abaum", "OXA-23 carbapenemase", "wild-type", "intrinsic carbapenem hydrolysis; CO2-dependent (carbamylated Lys-82). ~70% of CRAB worldwide."),
    "porB1b-loss": ("NGono", "outer membrane porin", "loss of porB1b porin", "reduces β-lactam entry into periplasm; increases ceftriaxone MIC 4x. Often combined with mtrR up-regulation."),
    "mtrR-up": ("NGono", "efflux regulator", "mtrR promoter mutation increasing efflux pump expression", "MtrCDE pump exports broad spectrum; increases macrolide + β-lactam MIC 2-4x."),
    "penA-mosaic-XXXIV": ("NGono", "PBP2", "mosaic transpeptidase domain", "chimeric segments from commensal Neisseria reshape active site; ceftriaxone MIC rises 100-1000x. FC428 and GU140106 lineages carry this."),
    "penA-mosaic-XXXV": ("NGono", "PBP2", "alternative mosaic", "similar mechanism to XXXIV; slightly different residue exchanges. Both confer ceftriaxone MIC 0.5-2 mg/L."),
    "23S-G2576T": ("MRSA / VRE", "23S ribosomal RNA", "guanine to thymine at position 2576", "alters linezolid binding cleft on 50S ribosome; reduces linezolid binding 5-10x."),
    "cfr": ("MRSA / VRE", "23S A2503", "Cfr methyltransferase modification", "methylates A2503 of 23S — interferes with linezolid + lincosamides + chloramphenicol binding. Plasmid-borne, transferable."),
    "ompK35-loss": ("KpneuCRE", "outer membrane porin", "loss of OmpK35", "reduces β-lactam entry; combined with carbapenemase = high-level resistance."),
    "ompK36-loss": ("KpneuCRE", "outer membrane porin", "loss of OmpK36", "similar effect to ompK35-loss. Often both lost together."),
    "AmpC-derepression": ("Paer", "AmpC β-lactamase", "ampD mutation derepressing chromosomal AmpC", "constitutive AmpC expression; raises β-lactam + 3GC MIC ~10-100x. Common in MDR-Pseudomonas."),
    "MexAB-up": ("Paer", "MexAB-OprM efflux", "promoter mutation increasing MexAB expression", "broad-spectrum efflux up-regulation; affects FQ + β-lactam + tetracycline + linezolid."),
    "OmpD-loss": ("Paer", "outer membrane porin", "loss of OmpD (OprD)", "reduces meropenem entry specifically. Common in carbapenem-R Pseudomonas."),
    "blaCTX-M-15-acquired": ("EColi-CRE", "ESBL", "acquired blaCTX-M-15 ESBL", "hydrolyzes 3GC efficiently; widespread in E. coli. Background mutation for many MDR strains."),
    "blaNDM-1-acquired": ("EColi-CRE / KpneuCRE", "MBL", "acquired blaNDM-1 metallo-β-lactamase", "Zn²⁺-dependent; hydrolyzes ALL β-lactams except aztreonam. Plasmid-borne, transferable."),
    "blaOXA-48-acquired": ("EColi-CRE / KpneuCRE", "OXA carbapenemase", "acquired blaOXA-48", "weak carbapenem hydrolysis; combined with porin loss = high-level R. Endemic in N. Africa, Middle East."),
    "23S-A2058G": ("Various", "23S rRNA", "adenine to guanine at position 2058", "reduces macrolide binding; common in Mycobacterium abscessus erm gene."),
    "blaTEM-acquired": ("Various", "ESBL", "extended-spectrum TEM β-lactamase", "hydrolyzes penicillins + 3GC; older but still relevant background."),
}


def trace_mutation_deep_dive(rng: random.Random) -> dict:
    mut_id = rng.choice(list(MUTATIONS.keys()))
    pathogen, target, change, mech = MUTATIONS[mut_id]
    user = f"Explain the resistance mutation {mut_id} at the molecular level."
    asst = (
        f"[Mutation Deep-Dive — {mut_id}]:\n\n"
        f"PATHOGEN: {pathogen}\n"
        f"TARGET: {target}\n"
        f"CHANGE: {change}\n\n"
        f"MOLECULAR MECHANISM:\n  {mech}\n\n"
        f"DESIGN IMPLICATIONS FOR LYSOS:\n"
    )
    if "mecA" in mut_id:
        asst += "  - Avoid contacts at residue 146/150/239 in the allosteric site\n  - Use covalent attachment to Ser-403 to override allosteric requirement\n"
    elif "vanA" in mut_id:
        asst += "  - Re-engineered glycopeptide with modified D-Ala-binding cleft (oritavancin-class)\n  - Or pivot to membrane-active MoA (daptomycin-class)\n"
    elif "rpoB" in mut_id:
        asst += "  - Extend rifampin scaffold with contacts OUTSIDE the RRDR (residues 451-475 or 535-560)\n  - Or pivot to second-target combo (rifampin + clofazimine via Rv0678)\n"
    elif "katG" in mut_id:
        asst += "  - Direct InhA inhibitor (triclosan-class diphenyl ether) — bypasses katG activation entirely\n"
    elif "inhA" in mut_id:
        asst += "  - Higher-affinity InhA binder; or upstream pathway target (FAS-II)\n"
    elif "gyrA" in mut_id:
        asst += "  - Quinolone with modified contact at residue 90/94; or pivot to GyrB target (zoliflodacin)\n"
    elif "KPC" in mut_id:
        asst += "  - Next-gen DBO with covalent geometry insensitive to position 179\n  - Or aztreonam-avibactam combo (aztreonam stable to KPC)\n"
    elif "penA" in mut_id:
        asst += "  - Extend C3 of ceftriaxone to compensate for mosaic pocket\n  - Or pivot to GyrB (zoliflodacin)\n"
    elif "23S" in mut_id or "cfr" in mut_id:
        asst += "  - Tedizolid (oxazolidinone with different binding mode)\n  - Or pivot to daptomycin (membrane-active, orthogonal MoA)\n"
    elif "OXA" in mut_id:
        asst += "  - Durlobactam (DBO with class D activity)\n"
    elif "ompK" in mut_id or "OmpD" in mut_id or "porB" in mut_id:
        asst += "  - Siderophore-conjugate that enters via TonB-dependent receptors (cefiderocol-class)\n"
    elif "Mex" in mut_id or "AmpC" in mut_id:
        asst += "  - Modified scaffold that escapes MexAB recognition (ceftolozane-class bulky tail)\n"
    elif "NDM" in mut_id:
        asst += "  - Cefiderocol bypass; aztreonam stable to MBL; Zn²⁺ chelator MBL inhibitor\n"
    else:
        asst += "  - Pivot to orthogonal mechanism class\n"
    asst += "\nDECISION: encode this escape mechanism into the resistance_robustness reward component; train the policy to evade it."
    return {
        "task": "teacher_mutation_deep_dive",
        "pathogen": pathogen,
        "mutation": mut_id,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# C. Three-way Designer ↔ Critic ↔ Strategist dialogues
# ============================================================================
def trace_three_way(rng: random.Random) -> dict:
    pathogen = rng.choice(PATHOGENS)
    user = f"Run a complete three-way Designer ↔ Critic ↔ Strategist dialogue for a {pathogen} campaign with a stage-gate handoff."
    composite = round(rng.uniform(0.6, 0.92), 2)
    mic = round(rng.uniform(0.1, 2.5), 2)
    weakest = rng.choice(["novelty", "synth", "hemolysis"])
    asst = (
        f"[Three-Way Dialogue — {pathogen}]:\n\n"
        f"--- DESIGNER turn ---\n"
        f"[Designer]: Iteration 4 complete. Top candidate composite={composite}, "
        f"MIC={mic} ug/mL. Weakest pillar: {weakest}. Submitting to Critic.\n\n"
        f"<handoff_envelope>\n"
        f"{{\"type\":\"handoff\",\"from\":\"designer\",\"to\":\"critic\","
        f"\"candidate_id\":\"L74-3\",\"composite\":{composite},\"weakest\":\"{weakest}\","
        f"\"ask\":\"verify novelty + escape risk before stage-gate\"}}\n"
        f"</handoff_envelope>\n\n"
        f"--- CRITIC turn ---\n"
        f"[Critic]: Per-dimension review of L74-3:\n"
        f"  chemistry_validity: PASS (RDKit clean)\n"
        f"  drug_likeness:      PASS (Lipinski 1 violation, acceptable)\n"
        f"  PAINS_actors:       PASS (no flags)\n"
        f"  novelty:            {'PASS' if weakest != 'novelty' else 'WARN'} (Tanimoto 0.42 vs ceftaroline)\n"
        f"  escape_mutations:   PASS (low-risk verdict)\n"
        f"  manufacturability:  {'WARN' if weakest == 'synth' else 'PASS'} (~$650/g GMP estimate)\n"
        f"  clinical_viability: PASS (IV-only, hospital indication)\n"
        f"  cross_resistance:   PASS (orthogonal MoA to vancomycin)\n"
        f"OVERALL: CONDITIONAL\n"
        f"REVISIONS: address the {weakest} flag; otherwise advance.\n\n"
        f"<handoff_envelope>\n"
        f"{{\"type\":\"handoff\",\"from\":\"critic\",\"to\":\"strategist\","
        f"\"candidate_id\":\"L74-3\",\"verdict\":\"CONDITIONAL\","
        f"\"single_warning\":\"{weakest}\","
        f"\"recommended_action\":\"advance_with_iteration\"}}\n"
        f"</handoff_envelope>\n\n"
        f"--- STRATEGIST turn ---\n"
        f"[Strategist]: Reviewing the ledger. Iteration 4, composite plateau "
        f"around {composite}. Critic CONDITIONAL on {weakest}. Compute remaining: "
        f"~6h on this campaign.\n\n"
        f"DECISION TREE:\n"
        f"  Option A: 1-2 more iterations focused on {weakest} (+2-3h). Risk: "
        f"plateau persists.\n"
        f"  Option B: stage-gate to wet-lab now; address {weakest} during synthesis. "
        f"Risk: wet-lab time wasted if {weakest} kills it.\n"
        f"  Option C: kill + restart on a different scaffold class. Risk: lose 4 "
        f"iterations of progress.\n\n"
        f"DECISION: Option A. Designer focuses on {weakest} pillar; +2 iterations "
        f"max. If composite hasn't moved by iter 6, then Option B.\n\n"
        f"<handoff_envelope>\n"
        f"{{\"type\":\"handoff\",\"from\":\"strategist\",\"to\":\"designer\","
        f"\"action\":\"iterate_focused\",\"focus_pillar\":\"{weakest}\","
        f"\"max_iterations\":2,\"timeout_h\":3}}\n"
        f"</handoff_envelope>\n\n"
        f"--- DESIGNER resumes ---\n"
        f"[Designer]: Acknowledged. Calling scaffold_hop with constraint "
        f"'preserve composite ≥ {composite} while improving {weakest}'."
    )
    return {
        "task": "teacher_three_way_dialogue",
        "pathogen": pathogen,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# D. Mid-trace chemistry self-correction
# ============================================================================
def trace_chemistry_self_correction(rng: random.Random) -> dict:
    pathogen = rng.choice(PATHOGENS)
    self_corrections = [
        ("PAINS catechol substructure detected mid-design — revise scaffold to bioisostere",
         "swap catechol for 3-pyridinol (loses one OH but preserves H-bond geometry)"),
        ("Michael acceptor (acrylamide) on the proposed structure — Lilly-MedChem flag",
         "saturate the alpha-beta double bond to a saturated amide; preserves backbone geometry"),
        ("Aldehyde liability (formyl group) — Ames mutagenicity risk",
         "convert to amide or oxetane bioisostere; bioavailability preserved"),
        ("Aromatic amine (aniline) — Ames concern + DILI risk",
         "convert to amide via N-acetyl protection; reduces electrophilic aromatic substitution"),
        ("Nitro group on aromatic ring — bacterial mutagenesis flag",
         "replace with -CN or -CF3 isostere; preserves electronic profile"),
        ("logP > 6 — likely hemolytic + poor solubility",
         "add polar group (introduce -OH or -NH2 at periphery); aim for logP 2-4"),
        ("MW > 700 — bioavailability concern; will be IV-only",
         "trim peripheral methyl groups; aim for MW ≤ 500 if PO desired"),
        ("Para-OMe blocks own metabolism via CYP3A4 substrate",
         "replace para-OMe with -F (similar electronics, no CYP3A4 substrate)"),
        ("Non-Lipinski: 6 H-bond donors",
         "convert one -OH to -OMe (preserves H-bond acceptor, removes donor)"),
        ("Cephem against MRSA needs PBP2a opener — current scaffold lacks allosteric tail",
         "add aminothiadiazole-oxime tail at C7 position (ceftaroline-class anchor)"),
    ]
    issue, fix = rng.choice(self_corrections)
    user = f"Designer started a candidate against {pathogen}; mid-trace, catch-and-correct a chemistry issue."
    asst = (
        f"[Chemistry Self-Correction — {pathogen}]:\n\n"
        f"[Designer]: Initial proposal:\n"
        f"  PROPOSAL: <SMILES with the issue>\n"
        f"  RATIONALE: targeting {pathogen} primary target with the standard scaffold.\n"
        f"  Calling predict_admet for stoplight check.\n\n"
        f"<tool_call>name: predict_admet\nargs: {{\"smiles\": \"<proposal>\"}}</tool_call>\n"
        f"[Tool]: returns ADMET panel (assume reasonable values for first pass)\n\n"
        f"--- self-check ---\n"
        f"[Designer]: Wait — re-reviewing the structure I just proposed.\n"
        f"  ISSUE DETECTED: {issue}.\n"
        f"  This is a stop-light failure that the predict_admet tool may not catch alone "
        f"(it reports MW/logP/HBD/HBA but doesn't flag specific substructure liabilities).\n"
        f"  Revising before passing to Critic.\n\n"
        f"REVISED PROPOSAL:\n"
        f"  Action: {fix}\n"
        f"  RATIONALE update: same scaffold but {fix.split(';')[0]}. The fix "
        f"removes the showstopper while preserving the active pharmacophore.\n\n"
        f"<tool_call>name: score_molecule\nargs: {{\"smiles\": \"<revised>\", \"target_pathogen\": \"{pathogen}\"}}</tool_call>\n"
        f"[Tool]: composite={round(rng.uniform(0.7, 0.88), 2)}\n\n"
        f"[Designer]: Composite improved post-correction. Self-correction was the right call. "
        f"Submitting revised candidate to Critic.\n\n"
        f"DECISION: don't suppress catch-and-correct; surfacing it in the trace teaches Designer to flag-and-revise when seeing PAINS / reactive groups / property violations."
    )
    return {
        "task": "teacher_chemistry_self_correction",
        "pathogen": pathogen,
        "issue": issue,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# E. Per-indication design deep dives
# ============================================================================
INDICATIONS = [
    ("MRSA bacteremia",         "MRSA",      "high MIC threshold, IV-only OK, 14-day course minimum, vancomycin-MIC creep concern"),
    ("MRSA endocarditis",       "MRSA",      "6-week IV course, biofilm tolerance on valve, source control via surgery"),
    ("Mtb pulmonary",           "Mtb",       "6-month course, granuloma penetration, persister-active needed, oral preferred for compliance"),
    ("MDR-TB",                  "Mtb",       "12-18 months, individualized regimen, BPaL backbone for XDR, tox monitoring"),
    ("CRE bacteremia",          "EColi-CRE", "carbapenemase-class-specific therapy, IV-only, ~14 day course, ceftaz-avi vs cefiderocol"),
    ("CF pulmonary Pseudomonas","Paer",      "chronic suppression vs acute exacerbation, inhaled tobramycin standard, IV reserve for exacerbation"),
    ("CRAB pneumonia",          "Abaum",     "VAP context, sulbactam-durlobactam first-line (FDA 2023), polymyxin salvage"),
    ("VRE endocarditis",        "VRE",       "linezolid 4-6 weeks, daptomycin alternative, surgical replacement common"),
    ("DGI (disseminated gonorrhea)","NGono", "ceftriaxone IV 7 days, FQ-R prevalent, GyrB target emerging"),
    ("Hospital-acquired pneumonia (HAP/VAP)", "Mixed", "ICU setting, broad-spectrum initially, narrow per cultures, AUC/MIC = 100"),
    ("Diabetic foot infection", "Mixed",     "polymicrobial, often MRSA + Enterobacterales + anaerobes, source control + abx"),
    ("Cystic fibrosis lung infection", "Paer", "biofilm-tolerant chronic colonization, inhaled vs IV, alternating tobramycin/aztreonam"),
]


def trace_indication(rng: random.Random) -> dict:
    indication, pathogen_label, notes = rng.choice(INDICATIONS)
    user = f"Design considerations for a candidate targeting {indication}."
    asst = (
        f"[Indication Deep-Dive — {indication}]:\n\n"
        f"PATHOGEN: {pathogen_label}\n"
        f"CLINICAL NOTES: {notes}\n\n"
        f"DESIGN CONSIDERATIONS:\n"
        f"  1. PK/PD profile required:\n"
    )
    if "endocarditis" in indication or "osteomyelitis" in indication:
        asst += "     - Long course (4-6+ weeks); chronic exposure tolerated\n     - Tissue penetration: bone, valve, biofilm-permeable\n     - AUC/MIC > 400 sustained\n"
    elif "TB" in indication or "Mtb" in indication or "pulmonary" in indication:
        asst += "     - PO preferred (compliance), F > 0.5\n     - Long t1/2 (≥ 8h) for once/twice-daily dosing\n     - Tissue penetration: lung + macrophage; granuloma if Mtb\n     - Persister-active for Mtb\n"
    elif "VAP" in indication or "HAP" in indication or "pneumonia" in indication:
        asst += "     - Lung ELF concentration ≥ MIC for ≥ 50% of dosing interval\n     - IV initial; PO step-down if appropriate\n     - 8-day short-course sufficient (IDSA)\n"
    elif "bacteremia" in indication:
        asst += "     - IV always; high Cmax\n     - 14 days from first negative blood culture\n     - Clear source: line removal if applicable\n"
    elif "UTI" in indication:
        asst += "     - Urinary concentration ≥ 100x plasma\n     - PO acceptable (F > 0.4)\n     - Short course OK for uncomplicated\n"
    elif "CF" in indication:
        asst += "     - Inhaled formulation for chronic suppression (TOBI Podhaler)\n     - IV for acute exacerbation\n     - Biofilm-tolerant — combo with biofilm-disrupting agent ideal\n"
    else:
        asst += "     - Indication-specific PK/PD targets\n     - Source control + abx as per IDSA guidelines\n"
    asst += (
        f"  2. PATHOGEN-SPECIFIC FACTORS:\n"
        f"     - Resistome briefing (call get_pathogen_resistome)\n"
        f"     - First-line therapy class (pivot AROUND, not toward)\n"
        f"     - Common combo partners\n\n"
        f"  3. ADMET CONSTRAINTS:\n"
        f"     - Hemolysis: low risk required for IV\n"
        f"     - hERG: critical for outpatient (QT-prolongation flag)\n"
        f"     - Hepatic: avoid DILI signal\n"
        f"     - Renal: dose-adjustable per Dettli\n\n"
        f"  4. MARKET / REGULATORY:\n"
        f"     - QIDP-eligible (covers our 8 priority pathogens)\n"
        f"     - LPAD pathway feasible for narrow indication\n"
        f"     - GMP cost ≤ $2000/g target for hospital IV pricing\n\n"
        f"DECISION: {indication} candidate spec written; Designer iterates within these constraints."
    )
    return {
        "task": "teacher_indication_deep_dive",
        "indication": indication,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# F. Tool-call chains (multi-tool sequences solving one problem)
# ============================================================================
def trace_tool_chain(rng: random.Random) -> dict:
    pathogen = rng.choice(PATHOGENS)
    user = f"Show a multi-tool chain that takes a candidate against {pathogen} from initial proposal to wet-lab handoff."
    asst = (
        f"[Tool-Call Chain — {pathogen}]:\n\n"
        f"PHASE 1 — CONTEXT (resistome + target):\n"
        f"<tool_call>name: get_pathogen_resistome\nargs: {{\"pathogen\": \"{pathogen}\"}}</tool_call>\n"
        f"[Tool]: returns resistome briefing + first-line therapy + common syndromes\n"
        f"<tool_call>name: find_target_structure\nargs: {{\"pathogen\": \"{pathogen}\"}}</tool_call>\n"
        f"[Tool]: returns primary_target + PDB id\n\n"
        f"PHASE 2 — INITIAL PROPOSALS (pocket-aware):\n"
        f"<tool_call>name: propose_pocket_aware\nargs: {{\"target_pdb\": \"<pdb>\", \"pocket_class\": \"active_site\"}}</tool_call>\n"
        f"[Tool]: returns 5-7 candidate proposals\n\n"
        f"PHASE 3 — PER-CANDIDATE PANEL (cheap parallel):\n"
        f"For each candidate (parallel):\n"
        f"  <tool_call>name: predict_mic_pathogen\nargs: {{\"smiles\":\"<C>\",\"pathogen\":\"{pathogen}\"}}</tool_call>\n"
        f"  <tool_call>name: predict_admet\nargs: {{\"smiles\":\"<C>\"}}</tool_call>\n"
        f"  <tool_call>name: predict_hemolysis\nargs: {{\"smiles\":\"<C>\"}}</tool_call>\n"
        f"Kill candidates with composite < 0.5.\n\n"
        f"PHASE 4 — TOP-K CONFIRMATION (medium cost):\n"
        f"For top-3 candidates:\n"
        f"  <tool_call>name: score_molecule\nargs: {{\"smiles\":\"<C>\",\"target_pathogen\":\"{pathogen}\"}}</tool_call>\n"
        f"  <tool_call>name: predict_resistance_escape\nargs: {{\"smiles\":\"<C>\",\"pathogen\":\"{pathogen}\"}}</tool_call>\n"
        f"  <tool_call>name: find_similar_drugs\nargs: {{\"query_smiles\":\"<C>\"}}</tool_call>\n"
        f"Kill if escape verdict = high-risk OR Tanimoto > 0.6 to known.\n\n"
        f"PHASE 5 — TOP-1 SYNTHESIS + 3D (expensive):\n"
        f"<tool_call>name: predict_synthesis_route\nargs: {{\"target_smiles\":\"<top>\"}}</tool_call>\n"
        f"<tool_call>name: predict_complex_structure\nargs: {{\"smiles\":\"<top>\",\"target_pdb_id\":\"<pdb>\"}}</tool_call>\n"
        f"<tool_call>name: dock_against_target\nargs: {{\"smiles\":\"<top>\",\"pdb_id\":\"<pdb>\"}}</tool_call>\n"
        f"Verify pose + cost; if pose is reliable + cost < $2000/g GMP → handoff.\n\n"
        f"PHASE 6 — CRITIC + STRATEGIST HANDOFF:\n"
        f"Critic 8-dim review → Strategist stage-gate → wet-lab handoff envelope.\n\n"
        f"WALL-CLOCK BUDGET ESTIMATE:\n"
        f"  Phase 1: ~600ms (cheap, sequential)\n"
        f"  Phase 2: ~2000ms (medium)\n"
        f"  Phase 3: ~500ms × 5 candidates = 2.5s parallel (or 12.5s sequential)\n"
        f"  Phase 4: ~1.5s × 3 candidates = 4.5s parallel\n"
        f"  Phase 5: ~14s for the top-1 (Boltz-2 + dock + synthroute)\n"
        f"  Total: ~25-30s wall-clock for a complete iteration\n\n"
        f"DECISION: cheap-first orchestration is THE pattern; never run Phase 5 on candidates that fail Phase 3."
    )
    return {
        "task": "teacher_tool_chain",
        "pathogen": pathogen,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# Driver
# ============================================================================
GENERATORS = {
    "pdb_pocket":              (3750, trace_pdb_pocket),
    "mutation_deep_dive":      (4500, trace_mutation_deep_dive),
    "three_way_dialogue":      (2500, trace_three_way),
    "chemistry_self_correct":  (2000, trace_chemistry_self_correction),
    "indication_deep_dive":    (2400, trace_indication),
    "tool_call_chain":         (2000, trace_tool_chain),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0xCAFEBABE_99)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    if OUT.exists(): OUT.unlink()
    counts = {}
    n_total = 0
    with open(OUT, "a") as f:
        for label, (n, fn) in GENERATORS.items():
            for _ in range(n):
                row = fn(rng)
                f.write(json.dumps(row) + "\n")
                counts[label] = counts.get(label, 0) + 1
                n_total += 1

    print(f"\nGenerated {n_total:,} targeted distillation traces")
    for k, v in counts.items():
        print(f"  {k:30s} {v:>5,}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
