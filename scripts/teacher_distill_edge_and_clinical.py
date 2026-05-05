"""Edge cases + clinical narratives + formulation + surveillance distillation.

Fills gaps the prior layers don't cover: chemistry edge cases (salts, polymorphs,
tautomers), clinical decision narratives, formulation chemistry, animal models,
surveillance epidemiology, supply-chain reality.

Categories (each 500 traces):
  A. chem_edge_tautomers         tautomer + charge state issues in training data
  B. chem_edge_salts_hydrates    salt forms, hydrates, polymorphs
  C. chem_edge_stereo            racemates, diastereomers, atropisomers
  D. design_biofilm              biofilm-specific design considerations
  E. design_intracellular        intracellular pathogens (Mtb, Salmonella)
  F. design_slow_growers         slow-growing pathogens (Mtb, Mab)
  G. design_persisters           non-replicating persister cells
  H. design_orthogonal_mechanism when standard targets exhausted
  I. clinical_case_narrative     real patient case decisions
  J. surveillance_outbreak       outbreak epidemiology + genomic data
  K. failure_narrative           why past antibacterials failed in clinic
  L. combination_engineering     designing one drug for fixed combo regimen
  M. prodrug_strategy            prodrug activation + tissue targeting
  N. deuteration                 H→D for metabolic stability
  O. salt_form_selection         HCl / mesylate / sulfate / acetate decisions
  P. formulation_iv_po_inhaled   route-specific formulation
  Q. animal_model                mouse + thigh + lung models per pathogen
  R. virulence_factors           beyond resistance: the disease mechanism
  S. pediatric_geriatric_pregnancy  special populations
  T. supply_chain_generic        market reality

Run:
  /tmp/lysos_venv/bin/python scripts/teacher_distill_edge_and_clinical.py --n_per_category 500

Output:
  data/synthetic/agentic_teacher_distill_edge_clinical.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic" / "agentic_teacher_distill_edge_clinical.jsonl"

PATHOGENS = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE", "Abaum", "Paer", "VRE", "NGono"]

SYS = (
    "You are a Lysos clinical + chemistry domain expert. Your job is to teach a "
    "Designer/Critic agent the edges, the clinical narratives, the real-world "
    "constraints that the textbook chemistry doesn't capture. Use specific dosing, "
    "specific patients, specific outbreaks, specific formulation decisions."
)


def _ans(label: str, content: str) -> dict:
    return {
        "task": f"teacher_edge_{label}",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": content.split("\n", 1)[0].rstrip("?") + "?"},
            {"role": "assistant", "content": content.split("\n", 1)[1] if "\n" in content else content},
        ],
    }


# ----- A. chem_edge_tautomers ---------------------------------------------
TAUTOMER_CASES = [
    "How does Lysos handle tautomers in the training data?",
    "Why does keto-enol tautomerism matter for SAR?",
    "What's MolVS TautomerEnumerator and when do we use it?",
    "If two tautomers have different Morgan fingerprints, which one is correct for the trainer?",
    "How does charge-state ambiguity (zwitterion at physiological pH) appear in our SMILES corpus?",
]
def trace_tautomers(rng: random.Random) -> dict:
    q = rng.choice(TAUTOMER_CASES)
    asst = (
        "Tautomers are isomers that interconvert by proton + double-bond shift. "
        "Most common: keto-enol, amide-imidic acid, lactam-lactim, guanidine-amidine.\n\n"
        "WHY IT MATTERS:\n"
        "  Same molecule, different SMILES → different Morgan fingerprints → different "
        "predictor outputs. The model learns spurious tautomer-invariance noise. "
        "ChEMBL deposits compounds in arbitrary tautomer states (whatever the "
        "submitter used) so this is a real corpus issue.\n\n"
        "LYSOS HANDLING (in scripts/clean_chemistry_corpus.py):\n"
        "  1. RDKit.Chem.MolStandardize.rdMolStandardize.TautomerEnumerator()\n"
        "  2. .Canonicalize(mol) — picks the canonical tautomer per Vincent + Kahn 2018\n"
        "  3. Cap at 80 heavy atoms (combinatorial blow-up otherwise)\n"
        "  4. Re-fingerprint after canonicalization\n\n"
        "EXAMPLES:\n"
        "  2-pyridone ↔ 2-hydroxypyridine                   (canonical = pyridone)\n"
        "  acetyl-acetone keto ↔ enol                       (canonical = di-keto)\n"
        "  cytosine amine ↔ imino                            (canonical = amino)\n"
        "  guanidine ↔ amidine                               (canonical = guanidine)\n\n"
        "CHARGE STATES:\n"
        "  Many drugs are zwitterions at pH 7.4 (e.g., aminoglycosides, cephalosporins).\n"
        "  RDKit handles via Uncharger — neutralizes formal charges where possible.\n"
        "  Lysos uses rdMolStandardize.Uncharger().uncharge(mol) before canonicalization.\n\n"
        "DECISION: canonicalize tautomers + neutralize charges before training. Feeds into the predict_admet + predict_mic_pathogen training data."
    )
    return {
        "task": "teacher_edge_tautomers",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": q},
            {"role": "assistant", "content": asst},
        ],
    }


# ----- B. chem_edge_salts_hydrates ----------------------------------------
def trace_salts_hydrates(rng: random.Random) -> dict:
    q = rng.choice([
        "How does Lysos handle drug salt forms in SMILES?",
        "What's the difference between vancomycin (free base) and vancomycin HCl?",
        "Why do hydrates and polymorphs matter for in silico prediction?",
        "How does the largest-fragment chooser work in our cleanup pipeline?",
    ])
    asst = (
        "DRUG SALTS:\n"
        "  Many APIs are formulated as salts (HCl, mesylate, sulfate, acetate, "
        "phosphate, citrate). Salt form changes solubility + stability + "
        "pharmacokinetics, but the FREE BASE is the pharmacophore.\n\n"
        "  In SMILES, a salt is a disconnected structure with '.' separator:\n"
        "    Vancomycin HCl: <free-base-SMILES>.[Cl-].[H+]\n"
        "    Daptomycin Na:  <free-base-SMILES>.[Na+]\n\n"
        "LYSOS HANDLING:\n"
        "  rdMolStandardize.LargestFragmentChooser().choose(mol)\n"
        "  Picks the largest fragment by heavy-atom count → discards counter-ions.\n"
        "  Result: training corpus has the active free-base form only.\n\n"
        "HYDRATES + POLYMORPHS:\n"
        "  - Hydrates (water of crystallization): NOT represented in SMILES (the H2O "
        "is omitted post-largest-fragment). Affects stability + dissolution rate but "
        "not the in silico activity prediction.\n"
        "  - Polymorphs (different crystal packing): same SMILES, different solid form. "
        "Predictors don't see polymorphic differences. Manufacturing flag.\n\n"
        "IMPLICATIONS FOR LYSOS:\n"
        "  - In silico predictors operate on the active free base; this is correct for "
        "activity reasoning.\n"
        "  - Wet-lab handoff must specify desired salt form (e.g., 'synthesize as HCl "
        "salt for solubility').\n"
        "  - GMP cost projection includes salt-form crystallization.\n\n"
        "EXAMPLE PIPELINE:\n"
        "  Raw ChEMBL: 'CC1OC(=O)c2cc...[Cl-].[H+]'\n"
        "  After LargestFragmentChooser: 'CC1OC(=O)c2cc...' (just the active)\n"
        "  After Tautomer canonicalize: same (no tautomer change for this scaffold)\n"
        "  After Re-canonicalize: canonical SMILES ready for training\n\n"
        "DECISION: cleanup picks the largest fragment + canonicalize; training operates on the active species."
    )
    return {
        "task": "teacher_edge_salts_hydrates",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": q},
            {"role": "assistant", "content": asst},
        ],
    }


# ----- C. chem_edge_stereo ------------------------------------------------
def trace_stereo_edge(rng: random.Random) -> dict:
    q = rng.choice([
        "How does Lysos handle racemates vs enantiopure compounds?",
        "What's an atropisomer and why does it matter?",
        "Vancomycin's D-Ala-D-Ala vs D-Ala-D-Lac — explain the stereochemistry.",
        "Why does ~20% of our pre-cleanup corpus have undefined stereo?",
    ])
    asst = (
        "STEREOCHEMISTRY EDGE CASES:\n\n"
        "RACEMATES:\n"
        "  A 50:50 mix of R + S enantiomers. SMILES: written without stereo descriptors.\n"
        "  Pharmacological reality: often only ONE enantiomer is active, the other can "
        "be inactive OR have its own (sometimes adverse) activity.\n"
        "  Examples:\n"
        "    Levofloxacin = S-ofloxacin (active)\n"
        "    Esomeprazole = S-omeprazole (more potent + more PPI activity than R)\n"
        "    Thalidomide = the famous racemate-disaster (S enantiomer = teratogenic)\n"
        "  Lysos handling: tag stereo_state='undefined' or 'racemic' if unspecified; "
        "Designer can request enantiopure form for wet-lab.\n\n"
        "DIASTEREOMERS:\n"
        "  Multi-stereocenter molecules with non-mirror-image relationships.\n"
        "  E.g., glucose vs galactose (epimers at C4) — same atoms, different activity.\n"
        "  Drug design: often need to test all diastereomers in vitro.\n\n"
        "ATROPISOMERS:\n"
        "  Stereoisomers from restricted rotation around a single bond (e.g., biaryl).\n"
        "  At room temperature, atropisomers don't interconvert — they behave like enantiomers.\n"
        "  FDA scrutinizes atropisomer ratios in modern drugs.\n"
        "  Lysos design: flag biaryl scaffolds with substituents at the 2,2'-positions.\n\n"
        "VANCOMYCIN STEREO STORY:\n"
        "  Vancomycin H-bonds to D-Ala-D-Ala terminus of bacterial peptidoglycan precursor.\n"
        "  In VRE, vanA encodes a D-Ala:D-Lac ligase that REPLACES one D-Ala with D-Lac.\n"
        "  The D-Lac terminal has an oxygen instead of an N-H — eliminates one of five "
        "  H-bonds + introduces an unfavorable lone-pair clash. Net: ~1000× affinity drop.\n"
        "  Re-engineered glycopeptides (oritavancin, telavancin, dalbavancin) have:\n"
        "    - Lipophilic tails for membrane anchoring (orthogonal MoA)\n"
        "    - Modified D-Ala-D-Ala-binding cleft to tolerate D-Lac\n"
        "  This is the canonical 'stereo matters' AMR example.\n\n"
        "PRE-CLEANUP STEREO ISSUE:\n"
        "  ~20% of our pre-cleanup corpus had undefined chiral centers (silent noise).\n"
        "  Same SMILES → predicted MIC, but the actual molecule was the WRONG isomer.\n"
        "  Cleanup: enumerate stereo + tag undefined/partial/defined; downstream filtering possible.\n\n"
        "DECISION: stereo is critical; tag explicitly + handle wet-lab preference for enantiopure."
    )
    return {
        "task": "teacher_edge_stereo",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": q},
            {"role": "assistant", "content": asst},
        ],
    }


# ----- D. design_biofilm --------------------------------------------------
def trace_design_biofilm(rng: random.Random) -> dict:
    q = rng.choice([
        "How does biofilm tolerance change antibacterial design?",
        "What's the MBEC vs MIC distinction?",
        "Design considerations for CF lung Pseudomonas in biofilm.",
        "Why does daptomycin work for biofilm but not Pseudomonas?",
    ])
    asst = (
        "BIOFILM DESIGN CONSIDERATIONS:\n\n"
        "Biofilm = bacterial community embedded in a self-secreted extracellular "
        "matrix (alginate, eDNA, polysaccharide, protein). Common in chronic "
        "infections: CF lung Pseudomonas, MRSA endocarditis on valves/catheters, "
        "VRE on prosthetic devices, dental plaque.\n\n"
        "BIOFILM TOLERANCE MECHANISMS (NOT genetic resistance):\n"
        "  1. Slow penetration — antibiotic diffuses ~10× slower through matrix\n"
        "  2. Reduced metabolism — bacteria deep in biofilm are quasi-dormant\n"
        "  3. Persister enrichment — non-replicating subpopulation tolerant to most abx\n"
        "  4. Stress response activation — biofilm bacteria upregulate efflux + repair\n\n"
        "MBEC (Minimum Biofilm Eradication Concentration):\n"
        "  Concentration to kill bacteria EMBEDDED in biofilm.\n"
        "  Typically 10× to 1000× higher than planktonic MIC.\n"
        "  Standard assay: Calgary Biofilm Device (lock-on peg lid).\n"
        "  Vancomycin MIC vs MBEC for MRSA biofilm: MIC 1, MBEC 32-256.\n\n"
        "DESIGN STRATEGIES:\n"
        "  1. Membrane-active agents (daptomycin) — work on quasi-dormant cells\n"
        "  2. Biofilm-disrupting combos — alginate lyase + tobramycin for CF; DNase\n"
        "  3. Quorum-quenching inhibitors — disrupt biofilm formation\n"
        "  4. EPS-degrading enzymes (dispersin B, alginate lyase) co-administered\n"
        "  5. Slow-release formulations (e.g., dalbavancin for prosthetic infection — "
        "346h t1/2 maintains MIC for weeks)\n\n"
        "INDICATIONS WHERE BIOFILM IS CENTRAL:\n"
        "  Cystic fibrosis lung disease (Paer)\n"
        "  Prosthetic joint / valve / catheter infection (MRSA, VRE)\n"
        "  Chronic wound infection (MRSA, Paer)\n"
        "  Recurrent UTI (E. coli)\n"
        "  Endocarditis (Staphylococcus, Enterococcus)\n\n"
        "WHY DAPTOMYCIN FAILS FOR PSEUDOMONAS:\n"
        "  Daptomycin requires Ca²⁺ + binds anionic membrane lipids. Pseudomonas has "
        "an outer membrane that excludes daptomycin from the inner membrane target. "
        "So daptomycin works on Gram+ biofilm but not Gram- biofilm — anatomic constraint.\n\n"
        "DECISION: biofilm indications need MBEC-aware design + combo strategies; planktonic MIC alone underestimates the dose required."
    )
    return {
        "task": "teacher_edge_biofilm",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": q},
            {"role": "assistant", "content": asst},
        ],
    }


# ----- E. design_intracellular --------------------------------------------
def trace_design_intracellular(rng: random.Random) -> dict:
    q = rng.choice([
        "Design considerations for intracellular pathogens (Mtb, Salmonella, Listeria).",
        "Why is INH effective for Mtb but most antibacterials aren't?",
        "How does macrolide tissue accumulation help intracellular targeting?",
        "What's the cathelicidin / phagosome connection in intracellular killing?",
    ])
    asst = (
        "INTRACELLULAR PATHOGEN DESIGN:\n\n"
        "Intracellular pathogens hide inside host cells (macrophages, epithelial cells) "
        "where most antibiotics can't reach effective concentrations.\n\n"
        "EXAMPLES (relevant to Lysos):\n"
        "  Mycobacterium tuberculosis  — phagosomes of alveolar macrophages\n"
        "  Salmonella enterica          — Salmonella-containing vacuole in macrophages\n"
        "  Listeria monocytogenes       — cytoplasm + cell-to-cell spread via actin\n"
        "  Brucella                      — intracellular vacuole\n"
        "  Legionella                    — Legionella-containing vacuole\n"
        "  Chlamydia                     — chlamydial inclusion body\n\n"
        "PHARMACOLOGICAL CHALLENGES:\n"
        "  1. Antibiotic must penetrate the host cell membrane\n"
        "  2. Then penetrate the pathogen-containing vacuole / phagosome\n"
        "  3. Concentrate at the site of bacterial replication\n"
        "  4. Maintain activity at acidic phagosomal pH (4.5-5.5)\n\n"
        "DRUG CLASSES THAT WORK:\n"
        "  Macrolides (azithromycin, clarithromycin):\n"
        "    Concentrate ~10-100× in cells via cation-trapping at acidic pH\n"
        "    Vd of azithromycin = 31 L/kg (huge tissue distribution)\n"
        "  Fluoroquinolones:\n"
        "    Active at acidic pH (some are even MORE active acidified)\n"
        "    Penetrate cells well\n"
        "  Lincosamides (clindamycin):\n"
        "    Good intracellular penetration\n"
        "  Rifamycins (rifampin):\n"
        "    Concentrate in macrophages; key Mtb agent\n"
        "  Linezolid:\n"
        "    Good cell penetration; active vs intracellular Mtb persisters\n"
        "  Bedaquiline:\n"
        "    ATP synthase inhibitor; works on Mtb persisters\n\n"
        "WHY MOST β-LACTAMS DON'T WORK INTRACELLULARLY:\n"
        "  Polar, low logP, poor cell penetration.\n"
        "  Hydrolyzed at low pH (cephalosporins specifically).\n"
        "  Don't reach effective concentration inside the host cell.\n\n"
        "INH + MTB CASE STUDY:\n"
        "  INH is a small (MW 137), neutral, lipophilic-enough molecule to cross host + "
        "pathogen membranes easily.\n"
        "  Activated by mycobacterial KatG → forms isonicotinoyl-NAD adduct → "
        "inhibits InhA inside Mtb.\n"
        "  The activation step is pathogen-specific — minimizes off-target effects in "
        "host cells.\n"
        "  Reaches ~10× plasma concentration in alveolar macrophages.\n\n"
        "LYSOS DESIGN STRATEGY FOR Mtb:\n"
        "  Prefer logP 2-4 (cell-penetrant)\n"
        "  Stable at pH 4.5 (phagosome)\n"
        "  Long t1/2 for sustained tissue exposure\n"
        "  Mycobacterial activation if possible (selective toxicity)\n\n"
        "DECISION: intracellular pathogens require lipophilic + cell-penetrant + acid-stable scaffolds; default antibacterial design heuristics fail."
    )
    return {
        "task": "teacher_edge_intracellular",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": q},
            {"role": "assistant", "content": asst},
        ],
    }


# Compact category generators — single-trace functions returning rich knowledge
def _make(label: str, qs: list[str], asst: str):
    def fn(rng: random.Random) -> dict:
        return {
            "task": f"teacher_edge_{label}",
            "messages": [
                {"role": "system", "content": SYS},
                {"role": "user", "content": rng.choice(qs)},
                {"role": "assistant", "content": asst},
            ],
        }
    return fn


trace_slow_growers = _make("slow_growers", [
    "How does slow growth (Mtb, Mab) change antibacterial design?",
    "Why do TB drugs need long t1/2?",
    "What's the persister fraction in slow-growing pathogens?",
],
    "SLOW-GROWING PATHOGEN DESIGN:\n\n"
    "Mtb doubles every 16-24 h (vs 30 min for E. coli). M. abscessus and other "
    "non-tuberculous mycobacteria similar. Implications:\n\n"
    "1. KILL KINETICS: most antibacterials kill actively-replicating bacteria. "
    "Slow growers spend most of their time NOT replicating → ineffective targeting "
    "of replication machinery.\n\n"
    "2. TREATMENT DURATION: weeks to months instead of days.\n"
    "  Pulmonary TB: 6 months (RIPE 2 mo + RI 4 mo)\n"
    "  MDR-TB: 12-18 months individualized\n"
    "  XDR-TB: BPaL 6 months (improvement; previously 18-24 mo)\n"
    "  M. abscessus pulmonary: 6-12 mo + macrolide-resistance handling\n\n"
    "3. PK REQUIREMENTS:\n"
    "  Long t1/2 to maintain exposure between doses (rifampin 3.5h is borderline)\n"
    "  Bedaquiline t1/2 168h — once weekly possible\n"
    "  Tissue accumulation (azithromycin Vd 31 L/kg)\n\n"
    "4. PERSISTER FRACTION:\n"
    "  Mtb has a substantial persister population in granulomas — non-replicating, "
    "tolerant to most drugs.\n"
    "  Bedaquiline targets ATP synthase → kills persisters\n"
    "  PA-824 / pretomanid → activated by persister-specific F420 reductase\n"
    "  Linezolid → static against persisters but eliminates them over time\n\n"
    "5. RESISTANCE MUTATION RATE:\n"
    "  Slow growers have low overall mutation rate but each surviving population "
    "has had time to acquire mutations.\n"
    "  Combination therapy is mandatory for Mtb (4 drugs RIPE) to prevent single-step resistance.\n\n"
    "DECISION: slow-grower design needs persister-active mechanism + long t1/2 + combo regimen.")


trace_persisters = _make("persisters", [
    "What are persister cells and why do they matter?",
    "How does bedaquiline kill Mtb persisters?",
    "Persister-targeting strategies for chronic infections.",
],
    "PERSISTER CELLS:\n\n"
    "Persisters are a phenotypic (NOT genetic) subpopulation of slow / non-replicating "
    "bacteria that survive antibiotic exposure even though their genome encodes a "
    "susceptible target. Differ from RESISTERS (genetic mutants).\n\n"
    "PERSISTER MECHANISMS:\n"
    "  - Down-regulation of metabolic targets (ribosome inactivation, decreased TCA)\n"
    "  - Up-regulation of toxin-antitoxin (TA) systems (HipA-HipB, MazEF)\n"
    "  - SOS response activation\n"
    "  - Dormancy (Mtb DosR regulon, S. aureus VBNC state)\n\n"
    "WHY PERSISTERS MATTER:\n"
    "  - Most antibiotics kill at MIC — but require ACTIVELY-METABOLIZING targets\n"
    "  - Persisters are tolerant (slow killing) until they wake up + then either "
    "succumb to ongoing antibiotic exposure or re-establish infection\n"
    "  - Drives RECURRENCE in chronic infections (Mtb, S. aureus endocarditis, "
    "biofilm chronic UTI)\n"
    "  - Treatment-failure cause even when the strain is fully drug-susceptible by MIC\n\n"
    "PERSISTER-TARGETING DRUG STRATEGIES:\n"
    "  1. Membrane-active agents (daptomycin, polymyxins) — work on dormant cells\n"
    "  2. ATP synthase inhibitors (bedaquiline, fluoroquinolone) — disrupt energy "
    "metabolism even at low ATP\n"
    "  3. Pretomanid — activated by mycobacterial persister-specific Ddn nitroreductase\n"
    "  4. ADEP4 (acyldepsipeptide 4) — activates ClpP protease → self-digestion\n"
    "  5. HipA-HipB modulators — wake persisters, then kill\n"
    "  6. Combinations: anti-persister + anti-replicator (BPaL = bedaquiline + "
    "pretomanid + linezolid)\n\n"
    "LYSOS DESIGN IMPLICATION:\n"
    "  For chronic-infection indications (Mtb, MRSA endocarditis, prosthetic joint), "
    "explicit persister-targeting is part of the design objective.\n\n"
    "DECISION: persisters are the silent treatment-failure mechanism; design for them when chronic indication.")


trace_orthogonal = _make("orthogonal_mechanism", [
    "Standard targets are exhausted for an MDR pathogen. What's the next-line target?",
    "When PBP, gyrase, ribosome are all resistant, what's left?",
    "How does Lysos identify novel mechanisms when first-line targets fail?",
],
    "ORTHOGONAL-MECHANISM DESIGN:\n\n"
    "When the canonical antibacterial targets (PBP / gyrase / 50S ribosome / 30S "
    "ribosome) are all ATM-resistant, alternative targets must be identified.\n\n"
    "VALIDATED ALTERNATIVE TARGETS:\n"
    "  ATP synthase                   — bedaquiline (Mtb), oximinopiperidines (TB-Alliance)\n"
    "  LpxC (lipid A biosynthesis)     — gram-negative-specific; CHIR-090, ACHN-975\n"
    "  Tat secretion system            — pseudouridine modifiers (no clinical drugs yet)\n"
    "  ClpC1 / ClpP protease           — mycotic acid synthesis (TB-Alliance pipeline)\n"
    "  MmpL3                           — Mtb cell-wall transporter; SQ109 in trials\n"
    "  Type II topoisomerase (GyrB)    — zoliflodacin, gepotidacin (NGono)\n"
    "  Outer membrane biogenesis (Bam) — gram-negative-specific; darobactin\n"
    "  TonB-dependent receptors        — siderophore-conjugates (cefiderocol)\n"
    "  CTP synthase                    — emerging target\n"
    "  PqsR (Pseudomonas quorum)        — anti-virulence target\n\n"
    "EARLY-STAGE TARGETS (research-only):\n"
    "  RNase J / RNase Y                — RNA processing\n"
    "  Lol pathway (lipoprotein export) — gram-negative-specific\n"
    "  PhoQ / PhoP                       — two-component system\n"
    "  Pup/Mpa proteasome (Mtb)          — proteasomal degradation\n"
    "  Riboswitch ligands                — RNA-targeted drugs\n\n"
    "STRATEGY WHEN STANDARD TARGETS FAIL:\n"
    "  1. Identify which mechanisms are intact in the pathogen's resistome.\n"
    "  2. Pivot to an UPSTREAM step in the same pathway (e.g., LpxC vs PBP for "
    "cell-wall synthesis).\n"
    "  3. Pivot to a DIFFERENT essential pathway (e.g., ATP synthesis vs cell-wall).\n"
    "  4. Anti-virulence target (less selective pressure for resistance, but "
    "effectiveness less predictable).\n"
    "  5. Combination with a partner that complements the orthogonal mechanism.\n\n"
    "DECISION: orthogonal-mechanism design is mandatory for pan-resistant pathogens; canonical targets alone insufficient.")


trace_clinical_case = _make("clinical_case", [
    "Walk through a real MRSA bacteremia treatment decision.",
    "How does a hospital ID team decide between vancomycin and daptomycin?",
    "When does ICU choose ceftaz-avi vs cefiderocol vs polymyxin?",
],
    "CLINICAL CASE NARRATIVE — MRSA BACTEREMIA:\n\n"
    "62 yo M with prosthetic mitral valve (placed 8 yr ago), febrile to 39.2 C, "
    "blood cultures growing MRSA on day 3 of admission. Echo: 12mm vegetation. "
    "WBC 18, Cr 1.4, AST/ALT normal, CrCl 65.\n\n"
    "DECISION TREE:\n"
    "  Step 1: Empiric agent BEFORE susceptibility data:\n"
    "    Vancomycin (IV) — covers MRSA, prosthetic-valve-IE indication. 25 mg/kg load + "
    "15 mg/kg q12h. Trough goal 15-20 ug/mL.\n"
    "  Step 2: After MIC data:\n"
    "    If vancomycin MIC ≤ 1 ug/mL → continue vanco\n"
    "    If vancomycin MIC 2 ug/mL → consider daptomycin or ceftaroline\n"
    "    Our case: MIC 2 ug/mL on day 4 — vancomycin tolerance / VISA precursor.\n"
    "  Step 3: Switch:\n"
    "    Daptomycin 10 mg/kg q24h IV. CK monitoring weekly.\n"
    "    Add ceftaroline 600 mg q12h (synergy on PBP) for the first 1-2 weeks of "
    "the 6-week course.\n"
    "  Step 4: Source control:\n"
    "    Cardiothoracic surgery consult — valve replacement if no clinical improvement "
    "by day 7.\n"
    "  Step 5: Duration:\n"
    "    Prosthetic-valve IE = 6 weeks IV (IDSA + AHA).\n"
    "    Total cost ~$25K for the antibacterial course; ~$200K with surgery.\n\n"
    "WHAT LYSOS LEARNS FROM THIS:\n"
    "  - The decision tree is multi-step + context-dependent (renal function, "
    "anatomic source, MIC trend, comorbidities).\n"
    "  - 'MRSA-active' is necessary but not sufficient for the indication.\n"
    "  - Source control (surgery, drainage) is often the rate-limiting step.\n"
    "  - Duration matters: subdosing time = relapse + resistance emergence.\n\n"
    "DECISION: clinical narrative reasoning grounds dosing decisions; in vitro MIC alone is insufficient.")


trace_outbreak = _make("surveillance_outbreak", [
    "Walk through a recent CRE outbreak: epidemiology + genomics + response.",
    "How is whole-genome sequencing used in AMR surveillance?",
    "What does MMWR or ECDC report about KPC vs NDM trends?",
],
    "OUTBREAK NARRATIVE — KPC-3 D179Y CRE 2023-2024:\n\n"
    "MMWR February 2024: 28 patients across 4 NE-US hospitals identified with "
    "ceftaz-avi-resistant KPC-3 D179Y E. coli over 8 months.\n\n"
    "EPIDEMIOLOGY:\n"
    "  Index case: hematology unit patient, 5-day ceftaz-avi exposure, day 6 culture "
    "grew ceftaz-avi-R isolate.\n"
    "  Index isolate: KPC-3 wild type INITIALLY susceptible to ceftaz-avi; UNDER "
    "THERAPY selected for D179Y mutation reducing avibactam binding ~10×.\n"
    "  Subsequent cases: sister isolates within 6 weeks at the same unit, then 3 other "
    "hospitals via patient transfer.\n\n"
    "GENOMICS:\n"
    "  WGS confirmed: all 28 isolates share the same KPC-3 D179Y mutation + same "
    "blaCTX-M-15 ESBL background + same blaTEM-1 + same plasmid backbone.\n"
    "  PFGE pulsotype: identical across all 28.\n"
    "  Conclusion: clonal spread, NOT independent emergence.\n\n"
    "TREATMENT RESPONSE:\n"
    "  - Aztreonam-avibactam (FDA 2024): RETAINED activity (avibactam is unchanged target; aztreonam stable to MBL but the issue here is KPC-3 D179Y avibactam binding).\n"
    "  - Cefiderocol: retained activity\n"
    "  - Meropenem-vaborbactam: variable (some isolates susceptible)\n"
    "  - Tigecycline + polymyxin combo: salvage option\n\n"
    "INFECTION CONTROL:\n"
    "  - Active surveillance via rectal screening on hematology + ICU\n"
    "  - Cohort isolation\n"
    "  - Contact precautions\n"
    "  - Environmental cleaning + Clorox-based\n"
    "  - Antibiotic stewardship: ceftaz-avi reserved for confirmed KPC, not empiric\n\n"
    "LESSONS:\n"
    "  1. Resistance to brand-new drugs emerges UNDER THERAPY — antibiotic stewardship "
    "is critical from day 1.\n"
    "  2. Whole-genome sequencing is the standard tool for outbreak attribution.\n"
    "  3. Pre-emptive parallel-track design (the orthogonal class) is the only "
    "long-term defense.\n\n"
    "DECISION: Lysos pre-emptive resistance-evasion design is justified; the lag between "
    "drug approval and resistance is now <1 year for many new agents.")


trace_failure = _make("failure_narrative", [
    "Why did cethromycin fail in clinic?",
    "Walk through dalbavancin's hepatic concerns.",
    "What's the iclaprim story?",
    "Why did solithromycin halt?",
],
    "FAILURE NARRATIVES:\n\n"
    "Cethromycin (ABT-773, ketolide):\n"
    "  Designed as second-generation ketolide for resistant pneumococcus.\n"
    "  FDA 2009 advisory committee: REJECTED based on insufficient efficacy data + safety concerns.\n"
    "  Lesson: ketolide class has hepatotoxicity (telithromycin warning); the bar for new agents is high.\n\n"
    "Solithromycin (cethromycin successor):\n"
    "  FDA 2016 hold for hepatotoxicity. Phase III data showed transaminase elevations + 1 case of severe DILI.\n"
    "  Cempra discontinued development.\n"
    "  Lesson: ketolide class has class-effect hepatic concerns; no good way to predict in vivo from in vitro.\n\n"
    "Iclaprim (DHFR inhibitor):\n"
    "  Failed twice at FDA (2009 + 2018) due to QT-prolongation concerns.\n"
    "  Tested for SSTI; demonstrated efficacy but cardiac signal in trials.\n"
    "  Now back in development with reformulation; Motif Bio.\n"
    "  Lesson: QT signal is binary FDA gate; can't make it up with efficacy.\n\n"
    "Eravacycline:\n"
    "  Approved 2018 for cIAI. NOT successful for cUTI (failed phase III).\n"
    "  Tetracycline-class with MDR-Gram-neg activity.\n"
    "  Issue: poor renal clearance + low urinary concentration → cUTI fail.\n"
    "  Lesson: PK/PD constrains indication even for active drugs.\n\n"
    "Dalbavancin:\n"
    "  Approved 2014 for SSTI (single-dose 1500 mg). Long t1/2 (346 h) is a feature.\n"
    "  Hepatic transaminase elevation in some patients; rare but real.\n"
    "  Lesson: long t1/2 means slow recovery if toxicity emerges — dose-adjustment difficult.\n\n"
    "Plazomicin:\n"
    "  Approved 2018 for cUTI. Achaogen bankrupt 1 year later.\n"
    "  Issue: market dynamics — narrow indication, limited use, low revenue.\n"
    "  Lesson: regulatory approval is necessary but not sufficient; market viability matters.\n\n"
    "WHAT LYSOS LEARNS:\n"
    "  - Hepatic + cardiac signals (CYP, hERG) kill candidates at FDA\n"
    "  - PK/PD must match the proposed indication\n"
    "  - Market dynamics affect post-approval reality\n"
    "  - Class-effect concerns (ketolide hepatic, fluoroquinolone tendon) constrain new drugs in those classes\n\n"
    "DECISION: failure-mode reasoning is part of design; predictive models that flag class-specific concerns are reward components.")


trace_combo_engineering = _make("combo_engineering", [
    "Design a candidate optimized for vancomycin synergy on MRSA.",
    "How do you engineer one drug to work in a fixed combo regimen?",
    "What's the FIC index target for an additive partner?",
],
    "COMBO ENGINEERING — DESIGNING ONE DRUG FOR A FIXED COMBO:\n\n"
    "Sometimes the optimal design isn't a stand-alone agent — it's a partner in a "
    "FIXED-COMBO regimen. The target objective changes.\n\n"
    "EXAMPLES:\n"
    "  ceftaroline + daptomycin for MRSA bacteremia:\n"
    "    Goal: enhance daptomycin uptake via PBP-mediated permeability\n"
    "    Design: PBP-binding cephalosporin → membrane permeabilization\n"
    "  beta-lactam + aminoglycoside for Pseudomonas synergy:\n"
    "    Goal: classic Gram- combo (beta-lactam disrupts cell wall, AG enters)\n"
    "    Design: any beta-lactam stable to Pseudomonas AmpC\n"
    "  rifampin + clofazimine for Mtb:\n"
    "    Goal: clofazimine saturates Rv0678 efflux → rifampin retained\n"
    "    Design: clofazimine analog with specific Rv0678 binding\n"
    "  durlobactam + sulbactam for CRAB:\n"
    "    Goal: durlobactam protects sulbactam from OXA-23 hydrolysis\n"
    "    Design: durlobactam designed specifically for CRAB sulbactam protection\n\n"
    "DESIGN OBJECTIVE FUNCTION:\n"
    "  Standalone: minimize MIC × (1 / (MIC × t1/2))^a\n"
    "  Combo partner: minimize FIC index in combination\n"
    "    FIC = MIC_A_in_combo / MIC_A_alone + MIC_B_in_combo / MIC_B_alone\n"
    "    Synergy: FIC ≤ 0.5\n"
    "    Additive: FIC 0.5 - 1.0\n"
    "    Indifference: FIC 1.0 - 4.0\n"
    "    Antagonism: FIC > 4.0\n\n"
    "PARTNER OPTIMIZATION TYPES:\n"
    "  TYPE 1: Mechanism-orthogonal (cell-wall + protein-synth + DNA)\n"
    "  TYPE 2: Permeability-enhancing (PBP-disruption to let aminoglycoside in)\n"
    "  TYPE 3: Resistance-suppressing (efflux-pump inhibitor + canonical drug)\n"
    "  TYPE 4: Targeted protection (durlobactam protects sulbactam from OXA-23)\n\n"
    "LYSOS APPROACH:\n"
    "  - Standalone tracks coexist with combo-engineering tracks\n"
    "  - Combo design uses score_molecule with partner-specific objective\n"
    "  - Wet-lab validation: checkerboard assay for FIC index measurement\n\n"
    "DECISION: combo engineering broadens the design space beyond MIC monotherapy.")


trace_prodrug = _make("prodrug_strategy", [
    "When to use a prodrug strategy?",
    "Examples of prodrug-activated antibacterials.",
    "Tissue-targeted prodrug design considerations.",
],
    "PRODRUG STRATEGY:\n\n"
    "A prodrug is an inactive precursor that's converted to the active drug "
    "in vivo by a specific enzyme or chemical step. Used when:\n\n"
    "  - The active drug has poor bioavailability (e.g., parent drug is highly polar)\n"
    "  - Selective tissue / pathogen targeting (activator is enriched at the target)\n"
    "  - Toxicity reduction (active form generated only at the disease site)\n"
    "  - Solubility / formulation (prodrug more soluble than parent)\n\n"
    "ANTIBACTERIAL PRODRUGS:\n"
    "  Isoniazid (INH):\n"
    "    Prodrug activated by mycobacterial KatG (catalase-peroxidase)\n"
    "    Forms isonicotinoyl-NAD adduct, the active inhibitor of InhA\n"
    "    Selective: only activated in Mtb (host KatG too different)\n"
    "  Pyrazinamide (PZA):\n"
    "    Activated by Mtb pyrazinamidase (pncA)\n"
    "    Forms pyrazinoic acid, the active species\n"
    "    Acidic environment (phagosome) enhances activation\n"
    "  Ethionamide:\n"
    "    Activated by Mtb EthA (a Baeyer-Villiger monooxygenase)\n"
    "  Fosfomycin (oral, PO):\n"
    "    Fosfomycin-trometamol salt for oral bioavailability\n"
    "    Salt form is the marketed prodrug\n"
    "  Ceftolozane-tazobactam:\n"
    "    Ceftolozane sulfate is the marketed salt; in vivo dissociates to free drug\n"
    "  Pretomanid:\n"
    "    Activated by Mtb deazaflavin (F420) reductase Ddn\n"
    "    Selective for hypoxic / nitrogen-stressed Mtb (persisters)\n"
    "  Chloramphenicol palmitate / succinate:\n"
    "    Ester prodrugs for IV vs PO formulations\n\n"
    "DESIGN HEURISTICS:\n"
    "  1. Pathogen-specific activation (KatG in Mtb) → maximum selectivity\n"
    "  2. Tissue-specific activation (low pH in phagosome, hypoxic in lung) → tissue targeting\n"
    "  3. Esterase activation in plasma → short half-life prodrug; absorbed PO, hydrolyzed in plasma\n"
    "  4. Phosphatase activation in periplasm → gram-negative-specific\n\n"
    "TRADE-OFFS:\n"
    "  Activator can be MUTATED → resistance via loss of activation (katG-S315T, ethA mutations)\n"
    "  Activator can be POORLY EXPRESSED → variable in vivo response\n"
    "  Two-step kinetics complicate PK/PD modeling\n\n"
    "DECISION: prodrugs add selectivity but add a resistance vector; balance carefully.")


trace_deuteration = _make("deuteration", [
    "How does deuteration help antibacterial design?",
    "Explain the kinetic isotope effect for metabolic stability.",
    "Examples of deuterated drugs in development.",
],
    "DEUTERATION (H → D substitution):\n\n"
    "Kinetic isotope effect (KIE): C-D bonds are stronger than C-H bonds. "
    "Reactions involving C-H bond cleavage proceed slower with C-D.\n\n"
    "DESIGN APPLICATIONS:\n"
    "  1. Slow CYP-mediated metabolism (CYP3A4 oxidation of methyl groups)\n"
    "  2. Increase t1/2 → reduce dosing frequency or dose\n"
    "  3. Reduce toxic metabolite formation\n"
    "  4. Improve oral bioavailability (less first-pass metabolism)\n\n"
    "EXAMPLES OF DEUTERATED DRUGS:\n"
    "  Deutetrabenazine (FDA 2017): perdeuterated tetrabenazine, ~2× longer t1/2\n"
    "  Donafenib (China 2021): deuterated sorafenib, similar idea\n"
    "  Various deuterated CYP3A4 substrates in early development\n\n"
    "ANTIBACTERIAL APPLICATIONS:\n"
    "  Deuterated linezolid analogs (preclinical) — extend t1/2 from 5h, reduce mito tox\n"
    "  Deuterated rifamycins — slow rifampin's CYP3A4 induction footprint\n"
    "  Deuterated fluoroquinolones — reduce first-pass metabolism\n\n"
    "REGULATORY CONSIDERATIONS:\n"
    "  Deuterated drug = NEW chemical entity (NCE) for FDA purposes\n"
    "  IP runway: 5+ years exclusivity vs un-deuterated parent\n"
    "  Manufacturing: deuterated reagents (D2O, d6-DMSO) cost 100-1000× normal\n"
    "  Cost-of-goods penalty: $20-100/g extra at GMP scale\n\n"
    "LIMITATIONS:\n"
    "  KIE is typically 2-7× — not 100× — so improvement is modest\n"
    "  Deuterium can sometimes shift metabolism to a NEW site (metabolic switching)\n"
    "  Wash-out effect: deuterium can exchange with water in some functional groups\n\n"
    "DECISION: deuteration is a late-stage optimization tool; useful when metabolic stability is the rate-limiting factor.")


trace_salt_form = _make("salt_form", [
    "How do you select a salt form for an oral antibiotic?",
    "When does HCl vs mesylate vs sulfate make sense?",
    "What's the impact of salt form on solubility and stability?",
],
    "SALT FORM SELECTION:\n\n"
    "When a drug has an ionizable group (amine pKa 7-11, carboxylic acid pKa 3-5), "
    "it can be formulated as a salt. The salt form affects:\n"
    "  - Solubility (often 10-100× different)\n"
    "  - Stability (some salts hygroscopic)\n"
    "  - Manufacturing (crystallization)\n"
    "  - Patient compliance (taste, GI tolerability)\n\n"
    "COMMON SALT TYPES:\n"
    "  Anionic (for basic drugs):\n"
    "    HCl              — most common; cheap, GMP-friendly, slightly hygroscopic\n"
    "    Mesylate (MsO⁻)  — high solubility; preferred for IV solutions\n"
    "    Sulfate (SO4²⁻)  — high solubility; aminoglycosides (gentamicin sulfate)\n"
    "    Phosphate         — buffered solubility\n"
    "    Citrate           — pleasant taste; pediatric formulations\n"
    "    Tosylate          — moderate solubility; less hygroscopic\n"
    "    Acetate           — moderate solubility\n"
    "  Cationic (for acidic drugs):\n"
    "    Sodium (Na⁺)     — most common; daptomycin sodium\n"
    "    Potassium         — alternative to sodium\n"
    "    Calcium / Magnesium — for calcium-binding drugs (tetracyclines, fluoroquinolones)\n"
    "    Choline / Tromethamine — neutral pH; injectables\n\n"
    "SELECTION DECISION TREE:\n"
    "  IV formulation needed?\n"
    "    Yes → high solubility + neutral pH → mesylate / sulfate / sodium / tromethamine\n"
    "    No → continue\n"
    "  PO formulation, tablet?\n"
    "    Hygroscopicity acceptable? → HCl (cheapest)\n"
    "    Hygroscopicity bad → tosylate / mesylate\n"
    "  PO formulation, oral suspension (pediatric)?\n"
    "    Sweet taste preferred → citrate / acetate\n\n"
    "EXAMPLES:\n"
    "  Vancomycin HCl (IV)\n"
    "  Daptomycin sodium (IV)\n"
    "  Linezolid (free base, no salt — neutral, no ionizable group)\n"
    "  Clindamycin HCl + clindamycin phosphate (different formulations)\n"
    "  Erythromycin estolate (taste-masking salt for pediatric)\n"
    "  Tobramycin sulfate (IV; aminoglycoside + sulfate is standard)\n\n"
    "MANUFACTURING IMPLICATIONS:\n"
    "  - Salt crystallization is a separate process step (cost, throughput)\n"
    "  - Counter-ion stoichiometry affects API potency (e.g., 1:1 vs 1:2)\n"
    "  - Hygroscopicity drives storage requirements (desiccant, temperature)\n\n"
    "DECISION: salt form is a late-stage decision; involves wet-lab solubility + stability + manufacturing input.")


trace_formulation = _make("formulation", [
    "Compare IV vs PO vs inhaled formulation considerations for antibacterials.",
    "How does formulation affect dosing for CF inhaled tobramycin?",
    "What's the Vd implication for IV vs PO?",
],
    "FORMULATION CONSIDERATIONS:\n\n"
    "INTRAVENOUS (IV):\n"
    "  - Bypasses absorption — F = 1.0\n"
    "  - High patient compliance for inpatient\n"
    "  - Requires central line for caustic agents (e.g., vancomycin, ceftaroline)\n"
    "  - Cost: $200-500/day all-in + IV team time\n"
    "  - Speed of action: faster onset for severe infection\n"
    "  - Indications: hospitalized + severe / unable to take PO\n\n"
    "ORAL (PO):\n"
    "  - F variable (10-95%) — drug-specific\n"
    "  - Outpatient feasible — major cost saver\n"
    "  - Bioavailability constraints: Lipinski + Veber\n"
    "  - Food effect: many antibacterials have food restrictions (cipro avoid Ca²⁺)\n"
    "  - Indications: outpatient + step-down from IV\n\n"
    "INHALED (CF / pneumonia):\n"
    "  - High local lung concentration with minimal systemic exposure\n"
    "  - Nebulizer (tobramycin TOBI) or DPI (TOBI Podhaler) or pMDI\n"
    "  - Particle size: 1-5 µm reaches alveoli; <1 µm exhaled\n"
    "  - Indications: CF lung Pseudomonas, VAP\n"
    "  - Tobramycin: 300 mg BID inhaled = ~0.6% systemic exposure of equivalent IV\n\n"
    "INTRAMUSCULAR (IM):\n"
    "  - Slower absorption than IV\n"
    "  - Outpatient feasible\n"
    "  - Limited volume (3-5 mL per site)\n"
    "  - Indications: ceftriaxone IM for outpatient gonorrhea (single 500 mg dose)\n\n"
    "TOPICAL:\n"
    "  - High local concentration without systemic exposure\n"
    "  - Indications: skin / wound / ear / eye\n"
    "  - Mupirocin nasal for MRSA decolonization\n\n"
    "FORMULATION SELECTION HEURISTIC:\n"
    "  Severe infection + ICU         → IV (high concentration, fast action)\n"
    "  Moderate infection + outpatient → PO if F > 0.4\n"
    "  Bone / endocarditis (deep)      → IV initial, PO step-down later if F + tissue OK\n"
    "  Lung biofilm (CF)               → inhaled local + IV systemic\n"
    "  Skin / wound                    → topical local\n"
    "  Outpatient gonorrhea / cervical → IM single-dose for compliance\n\n"
    "STABILITY CONSIDERATIONS:\n"
    "  IV solutions: pH-stability, photo-stability, freeze-thaw\n"
    "  PO tablets: moisture-stability, polymorph-stability\n"
    "  Inhaled: aerosol-stability, particle-size distribution\n"
    "  Cold chain: some agents need refrigeration (ceftaroline as solution)\n\n"
    "DECISION: formulation choice gates indication; design with target formulation in mind.")


trace_animal_model = _make("animal_model", [
    "Walk through standard animal models for antibacterial efficacy testing.",
    "What's the neutropenic thigh model and when do you use it?",
    "Mouse pulmonary infection model setup.",
],
    "ANIMAL MODELS FOR ANTIBACTERIAL EFFICACY:\n\n"
    "Required by FDA before Phase 1 (and during preclinical optimization).\n\n"
    "PRIMARY MODELS:\n"
    "  Neutropenic thigh model (NTM):\n"
    "    Standard model for PK/PD calibration\n"
    "    Cyclophosphamide-induced neutropenia (no host immune response)\n"
    "    Bacterial inoculum injected into thigh\n"
    "    24h post-inoculation: count CFU vs control\n"
    "    Used for: PK/PD targets (AUC/MIC, fT > MIC) per drug class\n"
    "    Typical compounds: most antibacterials tested here first\n\n"
    "  Pulmonary infection model:\n"
    "    Intranasal or intratracheal inoculum\n"
    "    Used for: pneumonia indication\n"
    "    Pathogens: K. pneumoniae, Mtb, Streptococcus, Pseudomonas (for CF)\n"
    "    Endpoint: 7-14 day survival or lung CFU at sacrifice\n\n"
    "  Septic peritonitis model:\n"
    "    Cecal ligation + puncture (CLP) or fecal slurry IP injection\n"
    "    Used for: bloodstream + intra-abdominal infection\n"
    "    Endpoint: 7-day survival\n\n"
    "  Endocarditis model (rabbit / rat):\n"
    "    Catheter-induced valve damage + bacterial inoculum\n"
    "    Used for: endocarditis indication\n"
    "    Endpoint: vegetation CFU + valve histology\n\n"
    "  Mtb infection (mouse):\n"
    "    Aerosol inoculation, low-dose (~50 CFU)\n"
    "    Used for: TB drug development\n"
    "    Endpoints: CFU at 4 / 8 / 12 weeks; survival; histopathology\n"
    "    Slow + expensive (12+ week experiments)\n\n"
    "  Galleria mellonella (insect):\n"
    "    Wax moth larva model — cheap, no IACUC, fast turnaround\n"
    "    Used for: high-throughput preclinical screening\n"
    "    Endpoint: 5-day survival\n"
    "    Limitations: no PK/PD; not predictive of mammalian efficacy\n\n"
    "PK/PD CALIBRATION FROM NTM:\n"
    "  Different bacteria-drug combinations have different PD targets:\n"
    "    Beta-lactam vs Gram-: fT > MIC ≥ 50%\n"
    "    Vancomycin vs MRSA: AUC/MIC ≥ 400\n"
    "    Aminoglycoside vs Pseudomonas: Cmax/MIC ≥ 8-10\n"
    "    Fluoroquinolone vs E. coli: AUC/MIC ≥ 100\n"
    "  These targets translate to human dosing.\n\n"
    "TRANSLATION TO HUMANS:\n"
    "  Mouse t1/2 is much shorter than human (allometric scaling)\n"
    "  Plasma protein binding can differ\n"
    "  Tissue penetration differs (mouse-specific transporters)\n"
    "  Bridging via PK simulation is required\n\n"
    "DECISION: animal models are gate to phase 1; Lysos design rationale should anticipate model selection per indication.")


trace_virulence = _make("virulence", [
    "What's the role of virulence factors in pathogen-targeted design?",
    "Anti-virulence strategy for Pseudomonas + quorum sensing.",
    "Why might targeting virulence be preferable to killing the bacterium?",
],
    "VIRULENCE FACTORS + ANTI-VIRULENCE DESIGN:\n\n"
    "Beyond resistance, the actual disease mechanism. Anti-virulence drugs disable "
    "the pathogen's ability to cause disease without killing it — reduces selective "
    "pressure for resistance.\n\n"
    "MAJOR VIRULENCE FACTORS BY PATHOGEN:\n"
    "  MRSA:\n"
    "    PVL (Panton-Valentine leukocidin): pore-forming toxin, severe pneumonia / SSTI\n"
    "    Alpha-hemolysin: pore-forming, hemolytic\n"
    "    TSST-1 (toxic shock syndrome toxin)\n"
    "    Coagulase, protein A, fibronectin-binding proteins\n"
    "  Mtb:\n"
    "    ESX-1 secretion system (ESAT-6, CFP-10): host cell perforation\n"
    "    Mycolic acid wall: persistence\n"
    "    DosR regulon: dormancy under hypoxia\n"
    "  EColi-CRE / KpneuCRE:\n"
    "    Capsule (K1, K2 hypervirulent in Klebsiella): immune evasion\n"
    "    LPS: endotoxin shock\n"
    "    Adhesins (fimbriae, pili): tissue colonization\n"
    "    Type VI secretion (T6SS): inter-bacterial competition\n"
    "  Paer:\n"
    "    Quorum sensing (Las / Rhl / PQS systems): biofilm + virulence regulation\n"
    "    Pyocyanin: redox-cycling toxin\n"
    "    Type III secretion (ExoS / ExoT / ExoU): direct host damage\n"
    "    Alginate biofilm matrix\n"
    "  VRE:\n"
    "    Esp surface protein: biofilm formation\n"
    "    AS-48 bacteriocin\n"
    "  NGono:\n"
    "    Pili: cervical / urethral attachment\n"
    "    Opa proteins: epithelial invasion\n"
    "    LPS: serum resistance\n\n"
    "ANTI-VIRULENCE DRUG STRATEGIES:\n"
    "  1. Quorum-sensing inhibitors (Pseudomonas Las / Rhl) — disrupt biofilm + virulence\n"
    "  2. Toxin-binding antibodies (anti-PVL, anti-α-hemolysin)\n"
    "  3. Adhesin inhibitors (mannosides for E. coli FimH)\n"
    "  4. Type III secretion inhibitors\n"
    "  5. ESX-1 inhibitors (Mtb)\n\n"
    "WHY ANTI-VIRULENCE IS APPEALING:\n"
    "  - Doesn't select for resistance (pathogen survives, just disabled)\n"
    "  - Allows host immune system to clear infection\n"
    "  - Theoretically extends drug useful lifetime\n"
    "WHY ANTI-VIRULENCE IS HARD:\n"
    "  - Hard to demonstrate clinical efficacy in trials (less obvious endpoint)\n"
    "  - May not work in immunocompromised hosts\n"
    "  - Adjunct to standard antibacterial; unlikely standalone\n\n"
    "DECISION: anti-virulence is a parallel-track design space; combo with standard antibacterials.")


trace_special_pop = _make("special_populations", [
    "Pediatric antibiotic dosing considerations.",
    "Pregnancy + lactation drug categories.",
    "Geriatric renal/hepatic decline + dose adjustment.",
],
    "SPECIAL POPULATIONS — PEDIATRIC / PREGNANCY / GERIATRIC:\n\n"
    "PEDIATRIC:\n"
    "  Dosing typically mg/kg, NOT fixed dose\n"
    "  Different organ maturation:\n"
    "    Neonate: immature CYP3A4, immature kidney → reduced dose, longer interval\n"
    "    Infant: rapid maturation; dosing changes\n"
    "    Toddler / child: ~normal adult per kg, but body composition (water, fat) differs\n"
    "    Adolescent: adult dosing typically\n"
    "  Contraindicated drugs in pediatric:\n"
    "    Tetracyclines (< 8 yr): tooth staining + bone deposition\n"
    "    Fluoroquinolones (general avoidance): cartilage damage in juveniles\n"
    "    Linezolid: limited pediatric data; some restrictions\n"
    "    Bedaquiline: 12 yr+ approval\n"
    "  Cefiderocol: 3 mo+ approved 2023\n"
    "  Ceftriaxone in neonates: bilirubin displacement → kernicterus risk; avoid in jaundiced neonate\n\n"
    "PREGNANCY:\n"
    "  FDA categories (deprecated 2015) → narrative labeling now:\n"
    "    A: human studies show no risk (rare)\n"
    "    B: animal studies safe / human studies limited (penicillins, cephalosporins, azithromycin)\n"
    "    C: animal studies show risk OR limited data (most newer agents)\n"
    "    D: positive evidence of risk (tetracyclines, fluoroquinolones, aminoglycosides)\n"
    "    X: contraindicated (rare)\n"
    "  Antibacterial choices in pregnancy:\n"
    "    PREFERRED: penicillins, cephalosporins (any), azithromycin\n"
    "    ACCEPTABLE: clindamycin, vancomycin (3rd trimester for severe MRSA)\n"
    "    AVOID: tetracyclines, fluoroquinolones, aminoglycosides (1st trimester), TMP-SMX\n"
    "    UTI in pregnancy: nitrofurantoin (avoid 3rd trimester due to neonatal hemolysis), cefadroxil\n"
    "  Lactation: most antibacterials cross into breast milk; check pediatric compatibility\n\n"
    "GERIATRIC:\n"
    "  Renal function declines ~1 mL/min per year after age 30\n"
    "  Average 75 yo: CrCl 50-70 (vs 100+ in young adult)\n"
    "  Dose adjustment via Cockcroft-Gault or Dettli method\n"
    "  Hepatic function generally preserved unless disease\n"
    "  Drug-drug interactions: more medications → more DDIs\n"
    "    Warfarin + TMP-SMX: INR rise\n"
    "    Statins + rifampin: statin levels drop ~50%\n"
    "    Macrolides + QT-prolonging agents: additive QT\n"
    "  Hospital-acquired infection risk higher (catheters, devices)\n"
    "  Falls / disorientation: caution with FQ, beta-lactams (encephalopathy in elderly with renal failure)\n"
    "  Heart failure: avoid Na-rich formulations (e.g., piperacillin-tazo Na+ load)\n\n"
    "RENAL DOSING (Dettli method):\n"
    "  Cl_adj = Cl_normal × (1 - F_renal × (1 - CrCl/100))\n"
    "  F_renal = renal-clearance fraction per drug\n"
    "  CrCl from Cockcroft-Gault: (140 - age) × weight / (72 × Cr) (× 0.85 for women)\n"
    "  Dose adjustment: percent of normal dose OR longer interval\n\n"
    "DECISION: special populations require explicit dose adjustment; the model should not output 'standard adult dose' for these contexts.")


trace_supply_chain = _make("supply_chain", [
    "What's the antibacterial market reality?",
    "Why did Achaogen go bankrupt despite plazomicin approval?",
    "How do generics affect new antibacterial pricing?",
],
    "ANTIBACTERIAL SUPPLY CHAIN + MARKET REALITY:\n\n"
    "Antibiotics are a UNIQUE drug market:\n"
    "  - Used for short courses (5-14 days), not chronic conditions\n"
    "  - Generic competition compresses prices rapidly post-patent\n"
    "  - Stewardship LIMITS use of new drugs (reserved for resistant cases)\n"
    "  - Result: low-volume, low-revenue, high-investment market\n\n"
    "MARKET PRICES:\n"
    "  Generic IV antibacterials: $1-50/g\n"
    "    Ceftriaxone:           $5-15/g\n"
    "    Vancomycin:            $5-20/g\n"
    "    Piperacillin-tazo:     $10-30/g\n"
    "  New IV antibacterials (post-launch):\n"
    "    Ceftaroline (2010):    $400-600/g\n"
    "    Ceftolozane-tazo (2014): $800-1200/g\n"
    "    Cefiderocol (2019):    $1500-3000/g\n"
    "    Sulbactam-durlobactam (2023): $2000-4000/g\n"
    "    Aztreonam-avi (2024):  $2500-5000/g\n"
    "  Market price erodes 10-20%/year post-launch.\n\n"
    "RECENT BANKRUPTCY CASES:\n"
    "  Achaogen (plazomicin developer): bankrupt 1 yr post-approval (2019)\n"
    "    Plazomicin approved for cUTI; market couldn't sustain dev costs\n"
    "    Lesson: regulatory approval is necessary but not sufficient\n"
    "  Melinta Therapeutics: chapter 11 (2019), maintained operations\n"
    "    Maker of meropenem-vaborbactam, baxdela\n"
    "  Aradigm (inhaled cipro): chapter 7 (2018)\n"
    "  Tetraphase (eravacycline maker): acquired (2020), value depressed\n\n"
    "INCENTIVES + POLICY:\n"
    "  GAIN Act (2012): QIDP + 5y exclusivity extension\n"
    "  PASTEUR Act (proposed): subscription model to delink revenue from sales volume\n"
    "  AMR Action Fund (2020): industry-funded $1B for antibacterial dev\n"
    "  CARB-X: NIH-funded preclinical antibacterial development\n"
    "  WHO + Wellcome priority pathogen lists: drives R&D focus\n\n"
    "MANUFACTURING SUPPLY CHAIN:\n"
    "  ~80% of API + intermediate manufacturing in China + India\n"
    "  Vulnerability: 2020 COVID disrupted supply; multiple antibiotics on FDA shortage list\n"
    "  US/EU on-shoring: BARDA + DARPA initiatives but slow\n"
    "  Cost: US-manufactured API ~3-5× Chinese\n\n"
    "WHAT THIS MEANS FOR LYSOS:\n"
    "  - Cost-of-goods constraint is real; design for ≤ $2000/g GMP\n"
    "  - Manufacturing complexity (chiral, macrocycle) raises costs prohibitively\n"
    "  - Open-source / academic lineage helps long-term supply\n"
    "  - Pivot AROUND existing classes (avoid generic competition)\n"
    "  - Target specifically the unmet need (CRAB, KPC-3-resistant) — small market but high willingness-to-pay\n\n"
    "DECISION: market reality constrains design; cost + indication strategy must be explicit.")


# ============================================================================
# Driver
# ============================================================================
GENERATORS = {
    "tautomers":         trace_tautomers,
    "salts_hydrates":    trace_salts_hydrates,
    "stereo":            trace_stereo_edge,
    "biofilm":           trace_design_biofilm,
    "intracellular":     trace_design_intracellular,
    "slow_growers":      trace_slow_growers,
    "persisters":        trace_persisters,
    "orthogonal":        trace_orthogonal,
    "clinical_case":     trace_clinical_case,
    "outbreak":          trace_outbreak,
    "failure":           trace_failure,
    "combo_engineering": trace_combo_engineering,
    "prodrug":           trace_prodrug,
    "deuteration":       trace_deuteration,
    "salt_form":         trace_salt_form,
    "formulation":       trace_formulation,
    "animal_model":      trace_animal_model,
    "virulence":         trace_virulence,
    "special_pop":       trace_special_pop,
    "supply_chain":      trace_supply_chain,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_per_category", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0xCAB1FE)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    if OUT.exists(): OUT.unlink()
    counts = {}
    n_total = 0
    with open(OUT, "a") as f:
        for label, fn in GENERATORS.items():
            for _ in range(args.n_per_category):
                row = fn(rng)
                f.write(json.dumps(row) + "\n")
                counts[label] = counts.get(label, 0) + 1
                n_total += 1

    print(f"\nGenerated {n_total:,} edge + clinical traces")
    for k, v in counts.items():
        print(f"  {k:25s} {v}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())