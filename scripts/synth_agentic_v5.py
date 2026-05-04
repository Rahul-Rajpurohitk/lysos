"""All 16 remaining agentic-data gaps (~12.3K rows).

HIGH (loop-quality):
  1 self_correction       (~1,000)  agent catches own mistake mid-output
  2 confidence_calibration(~1,000)  expresses calibrated uncertainty
  3 counterfactual        (~1,000)  "if I remove F, MIC rises because..."
  4 failure_postmortem    (  800)   "candidate X failed because..."
  5 prior_art_collision   (  800)   Tanimoto vs known-corpus reasoning

MEDIUM (depth):
  6 multi_pathogen        (  800)   broad-spectrum design
  7 cross_resistance      (  500)   FQ-resistant → LVX-resistant?
  8 pkpd_agent            (  800)   AUC/MIC, Cmax, t1/2 reasoning
  9 stewardship           (  500)   "vancomycin shortage, alternatives"
 10 time_budget           (  500)   triage under time pressure
 11 disambiguation        (  500)   clarifying questions

LOW (polish):
 12 manufacturing         (  300)   chiral resolution cost trade-off
 13 clinical_population   (  500)   ICU vs outpatient route logic
 14 adverse_events        (  500)   mitochondrial / nephro / oto
 15 animal_translation    (  500)   mouse → human PK extrapolation
 16 combo_therapy         (  500)   synergy / antagonism pairs
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
from synth_agentic_v2 import DESIGNER_SYS, CRITIC_SYS, STRATEGIST_SYS

OUT = ROOT / "data" / "synthetic"


# ============================================================================
# 1. self_correction — agent catches its own mistake mid-output
# ============================================================================
SELF_CORRECT_CASES = [
    ("PAINS catechol warhead", "swap to bioisostere (3-pyridinol)"),
    ("Michael acceptor (acrylamide)", "saturate the alpha-beta double bond"),
    ("aldehyde liability", "convert to amide or oxetane bioisostere"),
    ("cephem against MRSA mecA", "switch to ceftaroline-class with PBP2a opener"),
    ("logP > 6 — likely hemolytic", "add polar group to drop logP < 4"),
    ("MW > 700 — bioavailability concern", "trim peripheral methyls"),
    ("blocks own metabolism — CYP3A4 substrate", "replace para-OMe with -F"),
    ("non-Lipinski: 5 H-bond donors", "convert one -OH to -OMe"),
    ("nitro group — Ames hit risk", "replace with -CN or -CF3"),
    ("aromatic amine — possible carcinogen", "replace with amide"),
]
def synth_self_correction(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    issue, fix = rng.choice(SELF_CORRECT_CASES)
    msgs = [
        {"role": "system", "content": DESIGNER_SYS},
        {"role": "user", "content": f"Propose a candidate against {pathogen}."},
        {"role": "assistant", "content":
            f"PROPOSAL: {smiles}\n"
            f"RATIONALE: Anchored on {name}.\n\n"
            f"--- self-check ---\n"
            f"Wait — re-reviewing the structure I just proposed: {issue}. "
            f"That's a stop-light failure. Revising before passing to Critic.\n\n"
            f"REVISED PROPOSAL: {smiles}_v2\n"
            f"REVISED RATIONALE: Same scaffold but {fix}. The fix removes the "
            f"showstopper while preserving the active pharmacophore."},
    ]
    return {"task": "self_correction", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 2. confidence_calibration — explicit uncertainty quantification
# ============================================================================
def synth_confidence(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    component = rng.choice(["MIC", "QED", "synth route", "hemolysis", "novelty"])
    high_conf = rng.random() < 0.4
    if high_conf:
        conf = round(rng.uniform(0.85, 0.98), 2)
        evidence = "5+ structural analogs in ChEMBL with matching activity profile"
    else:
        conf = round(rng.uniform(0.40, 0.70), 2)
        evidence = f"{rng.randint(0,3)} analogs found, all with mid-range data — extrapolating"
    msgs = [
        {"role": "system", "content":
            "You are a calibrated agent. Express uncertainty explicitly and tie "
            "every confidence number to evidence (similar drugs, SAR data, mechanism)."},
        {"role": "user", "content":
            f"Predict {component} for {smiles[:40]}... against {pathogen}, "
            f"and tell me your confidence."},
        {"role": "assistant", "content":
            f"PREDICTION: {component} estimate consistent with {name} class.\n"
            f"CONFIDENCE: {conf} ({'high' if high_conf else 'medium-low'}).\n"
            f"EVIDENCE: {evidence}.\n"
            f"CAVEAT: {'None major.' if high_conf else 'Wide SAR error bars; recommend wet-lab confirmation.'}"},
    ]
    return {"task": "confidence_calibration", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 3. counterfactual — "if I change X, Y will happen because..."
# ============================================================================
COUNTERFACTUAL_CASES = [
    ("remove the C7 fluorine", "predicted MIC rises 4-8x", "loss of gyrA-S91 fluorine contact"),
    ("swap C5 -OH for -OMe", "QED drops 0.05, hemolysis improves 0.10", "one less H-bond donor + reduced membrane interaction"),
    ("add a methyl on the morpholine", "synthesizability worsens (chiral center)", "introduces a stereocenter requiring resolution"),
    ("ring-open the dihydrothiazine", "loses β-lactam activity entirely", "destroys the strained 4-ring acylating group"),
    ("swap carboxylate for tetrazole", "AUC improves, MIC stays the same", "isosteric replacement preserves PBP binding while improving PK"),
    ("add a piperazine at C7", "logP drops 0.8, gram-negative entry improves", "more polar surface area + protonated nitrogen for porin recognition"),
    ("methylate the amide nitrogen", "loses metabolic stability", "removes a key H-bond and exposes the amide to amidase cleavage"),
    ("introduce an oxygen in the linker", "MIC stays, half-life drops 50%", "creates a CYP3A4 hot-spot for hydroxylation"),
    ("homologate the side chain by one CH2", "lipophilicity rises, hERG risk increases", "longer hydrophobic tail favors hERG K+ channel binding"),
]
def synth_counterfactual(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    edit, effect, reason = rng.choice(COUNTERFACTUAL_CASES)
    msgs = [
        {"role": "system", "content":
            "You reason counterfactually about structure-activity relationships. "
            "Given a proposed edit, predict the effect AND explain the molecular reason."},
        {"role": "user", "content":
            f"Current candidate: {smiles[:50]}... against {pathogen}.\n"
            f"What if we {edit}?"},
        {"role": "assistant", "content":
            f"COUNTERFACTUAL: {edit}\n"
            f"PREDICTED EFFECT: {effect}\n"
            f"REASON: {reason}\n"
            f"NET RECOMMENDATION: {'Try it — net positive' if 'improve' in effect else 'Skip — net negative'}."},
    ]
    return {"task": "counterfactual_sar", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 4. failure_postmortem
# ============================================================================
FAILURE_MODES = [
    ("hepatotoxic at 50 mg/kg in mouse",         "ester linker hydrolyzed by CES1 → acyl glucuronide adduct"),
    ("hERG IC50 1.5 µM",                          "lipophilic basic amine + extended aromatic system"),
    ("did not cross gram-negative outer mem",     "lacked anionic charge for porin recognition; logP 4.2 too high"),
    ("rapid clearance (t1/2 < 30 min)",           "para-O-methyl is a CYP3A4 hot-spot; aldehyde metabolite"),
    ("mitochondrial liability",                   "rotenoid scaffold inhibited Complex I in HepG2 high-content screen"),
    ("Ames positive on TA98",                     "aromatic nitro group reduced to nitroso intermediate"),
    ("phospholipidosis",                          "cationic amphiphilic profile (CAD): basic amine + ≥2 aromatics + logP > 3"),
    ("crystallized as the wrong polymorph",       "thermodynamic vs kinetic form; reformulation required"),
]
def synth_failure_postmortem(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    failure, root_cause = rng.choice(FAILURE_MODES)
    lesson = "in future iterations, screen for this signal at the in-silico stage."
    msgs = [
        {"role": "system", "content":
            "You write candid failure post-mortems. Identify the root cause + the lesson "
            "for future iterations."},
        {"role": "user", "content":
            f"Candidate {smiles[:40]}... (anchored on {name}) failed in pre-clinical "
            f"against {pathogen}: {failure}.\nWhat went wrong?"},
        {"role": "assistant", "content":
            f"FAILURE: {failure}\n"
            f"ROOT CAUSE: {root_cause}\n"
            f"LESSON: {lesson}\n"
            f"DESIGN-TIME COUNTERMEASURE: add a flag for this motif/property in the "
            f"Critic's structural-alerts pass; gate proposals before they reach scoring."},
    ]
    return {"task": "failure_postmortem", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 5. prior_art_collision — Tanimoto vs known corpus
# ============================================================================
def synth_prior_art(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    tanimoto = round(rng.uniform(0.55, 0.95), 2)
    is_collision = tanimoto > 0.85
    if is_collision:
        comparator = rng.choice(["ciprofloxacin (Bayer 1987)", "linezolid (Pharmacia 1996)", "vancomycin (Lilly 1958)", "amoxicillin (Beecham 1972)"])
        decision = "REJECT — too similar to expired patent; novelty score will tank"
        rationale = f"Tanimoto {tanimoto:.2f} vs {comparator}. Not patentable as a new chemical entity."
    else:
        comparator = rng.choice(["a 2018 GSK PCT", "a 2021 Roche bicycle", "a 2024 academic publication"])
        decision = "ACCEPT — distance from prior art adequate"
        rationale = f"Tanimoto {tanimoto:.2f} vs nearest match ({comparator}). Sufficient novelty."
    msgs = [
        {"role": "system", "content": CRITIC_SYS},
        {"role": "user", "content":
            f"Run prior-art collision check on {smiles[:50]}... for {pathogen}."},
        {"role": "assistant", "content":
            f"WEAKNESS: novelty (Tanimoto {tanimoto:.2f})\n"
            f"COMPARATOR: {comparator}\n"
            f"DECISION: {decision}\n"
            f"RATIONALE: {rationale}"},
    ]
    return {"task": "prior_art_collision", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 6. multi_pathogen — broad-spectrum design
# ============================================================================
def synth_multi_pathogen(rng, pathogens_pair, anchor) -> dict:
    p1, p2 = pathogens_pair
    name, smiles = anchor
    msgs = [
        {"role": "system", "content": DESIGNER_SYS},
        {"role": "user", "content":
            f"Design a candidate active against BOTH {p1} (gram +) and {p2} (gram -). "
            f"Reconcile the trade-offs."},
        {"role": "assistant", "content":
            f"PROPOSAL: {smiles}\n"
            f"RATIONALE: Broad-spectrum requires balanced lipophilicity (logP 1-3) + "
            f"cationic charge for porin entry into {p2} while retaining peptidoglycan "
            f"affinity for {p1}. Anchored on {name}'s zwitterionic profile.\n"
            f"TRADE-OFF: gives up some potency vs {p1} alone in exchange for the "
            f"gram-negative coverage; net composite higher because spectrum reward > narrow potency."},
    ]
    return {"task": "multi_pathogen_design", "pathogen": f"{p1}+{p2}", "messages": msgs}


# ============================================================================
# 7. cross_resistance
# ============================================================================
CROSS_RES_PAIRS = [
    ("gyrA S91F (CIP-resistant)",  "yes — 84% of clinical isolates also LVX-resistant",  "shared S91 contact"),
    ("ermB (clarithro-resistant)",  "yes — full cross-resistance to azithro, ery",         "shared 23S A2058 methylation site"),
    ("OXA-48 (carbapenem-R)",       "partial — meropenem only modestly raised, ertapenem more",  "differential affinity for the OXA-48 active site"),
    ("vanA (vancomycin-R)",         "yes — teicoplanin also affected",                     "both bind D-Ala-D-Ala terminus"),
    ("rmtB (gentamicin-R)",         "yes — tobra, amikacin, plazomicin also",              "16S methylation blocks all aminoglycosides"),
    ("ESBL CTX-M-15",               "yes for 3G ceph; aztreonam preserved",                "CTX-M doesn't hydrolyze monobactams"),
]
def synth_cross_resistance(rng, pathogen) -> dict:
    mut, answer, reason = rng.choice(CROSS_RES_PAIRS)
    msgs = [
        {"role": "system", "content":
            "You answer cross-resistance prediction queries with mechanism."},
        {"role": "user", "content":
            f"In {pathogen}, the strain carries: {mut}. Will it also be resistant to "
            f"the next-generation drug in the same class?"},
        {"role": "assistant", "content":
            f"ANSWER: {answer}\nMECHANISM: {reason}"},
    ]
    return {"task": "cross_resistance", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 8. pkpd_agent — Cmax, AUC, MIC/Cmax reasoning
# ============================================================================
def synth_pkpd(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    mic = round(rng.uniform(0.25, 4.0), 2)
    cmax = round(rng.uniform(2.0, 16.0), 2)
    auc24 = round(cmax * rng.uniform(8, 24), 1)
    drug_class = rng.choice(["fluoroquinolone", "β-lactam", "aminoglycoside", "macrolide"])
    if drug_class == "fluoroquinolone":
        target_metric = "AUC/MIC"; target_value = round(auc24 / mic, 1); threshold = 100
        verdict = "adequate" if target_value > threshold else "underdosed"
    elif drug_class == "β-lactam":
        target_metric = "T>MIC"; target_value = round(rng.uniform(40, 80), 1); threshold = 50
        verdict = "adequate" if target_value > threshold else "needs higher dose / longer infusion"
    elif drug_class == "aminoglycoside":
        target_metric = "Cmax/MIC"; target_value = round(cmax / mic, 1); threshold = 8
        verdict = "adequate" if target_value > threshold else "underdosed"
    else:
        target_metric = "AUC/MIC"; target_value = round(auc24 / mic, 1); threshold = 50
        verdict = "adequate" if target_value > threshold else "underdosed"
    msgs = [
        {"role": "system", "content":
            "You reason about PK/PD: pick the right metric for the drug class and "
            "compute it from MIC, Cmax, AUC."},
        {"role": "user", "content":
            f"Candidate ({drug_class} class) against {pathogen}:\n"
            f"  MIC: {mic} µg/mL\n  Cmax: {cmax} µg/mL\n  AUC0-24: {auc24} µg·hr/mL"},
        {"role": "assistant", "content":
            f"DRUG CLASS: {drug_class}\n"
            f"KEY METRIC: {target_metric} (threshold > {threshold})\n"
            f"COMPUTED: {target_metric} = {target_value}\n"
            f"VERDICT: {verdict.upper()}\n"
            f"NOTE: {drug_class}s are {'concentration' if drug_class in ('fluoroquinolone','aminoglycoside') else 'time'}-dependent killers."},
    ]
    return {"task": "pkpd_reasoning", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 9. stewardship — institutional / supply constraints
# ============================================================================
STEWARDSHIP_SCENARIOS = [
    ("vancomycin shortage", "daptomycin or linezolid alternatives"),
    ("formulary restriction on cefiderocol", "ceftolozane-tazobactam if gram-neg"),
    ("renal impairment patient pool", "avoid aminoglycosides + colistin; renally adjust everything"),
    ("oral-only outpatient setting", "avoid IV-only β-lactams; prefer oxazolidinones, FQs, doxy"),
    ("ICU with high CRE rate", "prioritize new cephalosporins + plazomicin"),
    ("pediatric cohort", "no FQs, no tetracyclines under 8"),
    ("cost ceiling $50/day", "older β-lactams + sulfa-trimeth combos"),
    ("antibiotic-induced C. diff outbreak", "narrow spectrum; avoid FQs and 3G ceph"),
]
def synth_stewardship(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    scenario, recommendation = rng.choice(STEWARDSHIP_SCENARIOS)
    msgs = [
        {"role": "system", "content":
            "You apply hospital antimicrobial stewardship constraints to drug recommendations."},
        {"role": "user", "content":
            f"Patient: {pathogen} infection.\n"
            f"Institutional constraint: {scenario}.\n"
            f"What's the design / treatment recommendation?"},
        {"role": "assistant", "content":
            f"CONSTRAINT: {scenario}\n"
            f"RECOMMENDATION: {recommendation}\n"
            f"DESIGN IMPLICATION: bias new candidates toward this profile; "
            f"de-prioritize the constrained class even if its raw composite is higher."},
    ]
    return {"task": "stewardship_reasoning", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 10. time_budget — triage under time pressure
# ============================================================================
def synth_time_budget(rng, pathogen) -> dict:
    minutes_left = rng.choice([1, 2, 3, 5, 10, 15, 30])
    composite = round(rng.uniform(0.55, 0.85), 3)
    n_pareto = rng.randint(1, 8)
    if minutes_left <= 3 and composite >= 0.75:
        decision, reason = "SHIP", f"composite {composite} is shippable; insufficient time for another iter."
    elif minutes_left >= 10 and composite < 0.75:
        decision, reason = "ITERATE", f"{minutes_left}min budget allows ~{minutes_left // 3} more rounds."
    elif minutes_left <= 3 and composite < 0.75:
        decision, reason = "BRANCH_FAST", "time-constrained; scaffold-hop once and ship the better of the two."
    else:
        decision, reason = "ONE_MORE", "single iter affordable; aim for composite > 0.80 then ship."
    msgs = [
        {"role": "system", "content": STRATEGIST_SYS},
        {"role": "user", "content":
            f"State: {pathogen}, composite {composite}, {n_pareto} candidates on Pareto, "
            f"{minutes_left} min of compute budget left. What now?"},
        {"role": "assistant", "content":
            f"DECISION: {decision}\nRATIONALE: {reason}"},
    ]
    return {"task": "time_budget_triage", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 11. disambiguation — ask clarifying when ambiguous
# ============================================================================
DISAMB_QUERIES = [
    ("design something for MRSA",                   "MRSA bacteremia (high-tier IV) or MRSA SSTI (oral)?"),
    ("propose a new TB drug",                       "drug-susceptible TB or MDR-TB / XDR? Different design priorities."),
    ("oral antibiotic for the elderly",             "elderly with normal vs impaired renal function? Affects dosing range."),
    ("broad-spectrum gram-negative",                "ESKAPE coverage including Acinetobacter or just Enterobacterales?"),
    ("pediatric-safe option",                       "neonate, infant, or older child? Drug class restrictions differ."),
    ("UTI candidate",                               "uncomplicated lower or pyelonephritis? Tissue penetration matters."),
]
def synth_disambiguation(rng, pathogen) -> dict:
    query, clarifying = rng.choice(DISAMB_QUERIES)
    msgs = [
        {"role": "system", "content":
            "You ask one clarifying question when the request is ambiguous, BEFORE proposing."},
        {"role": "user", "content": query},
        {"role": "assistant", "content":
            f"Before I propose: {clarifying}\n"
            f"(The answer will substantially change the optimal scaffold class.)"},
    ]
    return {"task": "disambiguation", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 12. manufacturing — chiral resolution / process cost trade-offs
# ============================================================================
MFG_SCENARIOS = [
    ("3 chiral centers requiring resolution",        "+ $8M dev cost", "use achiral analog if MIC stays within 2x"),
    ("Pd-catalyzed coupling (Pd > 10 ppm in API)",  "regulatory burden + cost", "switch to copper-mediated or photoredox"),
    ("late-stage hydrogenation under high pressure","capex + safety", "explore biocatalysis"),
    ("organotin reagent in route",                  "tin residue specs are $$",  "redesign to avoid Sn intermediate"),
    ("cryogenic step (-78 C)",                      "scale-up risk",              "find ambient-T alternative"),
]
def synth_manufacturing(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    issue, cost, fix = rng.choice(MFG_SCENARIOS)
    msgs = [
        {"role": "system", "content":
            "You reason about CMC / manufacturing constraints during design."},
        {"role": "user", "content":
            f"Candidate ({smiles[:40]}...) for {pathogen}; route inspection flags: {issue}."},
        {"role": "assistant", "content":
            f"MFG ISSUE: {issue} ({cost})\n"
            f"FIX: {fix}\n"
            f"DESIGN IMPLICATION: design around this constraint at the structure level — "
            f"easier than fighting it later in process development."},
    ]
    return {"task": "manufacturing_constraint", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 13. clinical_population — ICU vs outpatient route logic
# ============================================================================
POPULATIONS = [
    ("ICU bacteremia",            "IV only; oral bioavailability not required"),
    ("outpatient SSTI",           "oral preferred; IV unacceptable"),
    ("pediatric (>8y)",           "PO or IV; avoid FQs, tetracyclines"),
    ("pregnant patient",          "category B preferred; β-lactams, macrolides"),
    ("end-stage renal disease",   "no AGs, no colistin; renally cleared agents need adjustment"),
    ("transplant immunosuppressed","no live drug interactions with tacrolimus / cyclosporine"),
]
def synth_clinical_population(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    pop, recommendation = rng.choice(POPULATIONS)
    msgs = [
        {"role": "system", "content":
            "You tailor antibiotic selection to the clinical population."},
        {"role": "user", "content":
            f"Population: {pop}. Pathogen: {pathogen}. Constraints?"},
        {"role": "assistant", "content":
            f"POPULATION: {pop}\n"
            f"CONSTRAINT: {recommendation}\n"
            f"DESIGN IMPLICATION: candidate must satisfy these constraints AT THE MOLECULE LEVEL "
            f"(not just dosing) — drives the SAR target profile."},
    ]
    return {"task": "clinical_population", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 14. adverse_events — beyond hERG / hepatotox
# ============================================================================
ADVERSE_EVENTS = [
    ("mitochondrial liability",  "rotenoid scaffold; Complex I inhibition",                 "avoid quinone-rich aromatics"),
    ("nephrotoxicity",           "polyamine + lipophilicity → tubular accumulation",        "lower logP < 3"),
    ("ototoxicity",              "aminoglycoside cochlear hair-cell uptake",                "limit free-amine count"),
    ("photosensitivity",         "fluoroquinolone C8-halogen UV chromophore",               "swap C8-F for C8-OMe"),
    ("tendinopathy",             "Mg2+ chelation by C3-carboxyl + C4-keto",                 "consider tetrazole isostere of carboxyl"),
    ("Stevens-Johnson syndrome", "sulfonamide + slow acetylators",                          "minimize aromatic SO2NH2"),
    ("disulfiram reaction",      "tetrazole-thiomethyl + EtOH",                             "remove the methylthio-tetrazole side-chain"),
    ("cardiac arrhythmia",       "macrolide-induced QTc prolongation via hERG",             "reduce aromatic stacking with K+ channel"),
]
def synth_adverse_events(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    ae, mechanism, mitigation = rng.choice(ADVERSE_EVENTS)
    msgs = [
        {"role": "system", "content":
            "You predict adverse-event liabilities from structural features and propose mitigation."},
        {"role": "user", "content":
            f"Screen {smiles[:40]}... (anchored on {name}) against {pathogen} for adverse-event risk."},
        {"role": "assistant", "content":
            f"AE FLAG: {ae}\nMECHANISM: {mechanism}\nMITIGATION: {mitigation}\n"
            f"DESIGN IMPLICATION: incorporate the mitigation in the next iteration before "
            f"sending to in-vitro validation."},
    ]
    return {"task": "adverse_event_prediction", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 15. animal_translation — mouse → human PK extrapolation
# ============================================================================
def synth_animal_translation(rng, pathogen, anchor) -> dict:
    name, smiles = anchor
    mouse_t12 = round(rng.uniform(0.5, 4.0), 2)
    mouse_cl = round(rng.uniform(10, 60), 1)
    # Allometric scaling: human t1/2 ~ mouse * 4 (approximate)
    human_t12 = round(mouse_t12 * rng.uniform(3.0, 6.0), 2)
    human_cl = round(mouse_cl * 0.30, 1)  # roughly 30% of mouse Cl per kg
    msgs = [
        {"role": "system", "content":
            "You extrapolate animal-model PK to human via allometric scaling + species-difference reasoning."},
        {"role": "user", "content":
            f"Mouse PK for candidate against {pathogen}:\n"
            f"  t1/2: {mouse_t12} hr\n  Cl: {mouse_cl} mL/min/kg\n"
            f"Predict human PK."},
        {"role": "assistant", "content":
            f"ALLOMETRIC SCALING (mass-power 0.75 for Cl, 0.25 for t1/2):\n"
            f"  Predicted human t1/2: {human_t12} hr\n"
            f"  Predicted human Cl:   {human_cl} mL/min/kg\n"
            f"CAVEATS: differential CYP isoform expression (mouse Cyp3a11 vs human CYP3A4); "
            f"plasma protein binding may differ; renal vs hepatic clearance fraction may shift."},
    ]
    return {"task": "animal_translation", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# 16. combo_therapy — synergy / antagonism reasoning
# ============================================================================
COMBO_PAIRS = [
    ("rifampin + clofazimine",     "synergy",     "Rv0678 efflux affects both; rifampin saturates the pump"),
    ("β-lactam + aminoglycoside",  "synergy",     "β-lactam cell-wall disruption increases AG entry"),
    ("vancomycin + daptomycin",    "synergy",     "complementary cell-wall + membrane mechanisms"),
    ("colistin + meropenem",       "synergy",     "colistin permeabilizes outer membrane for meropenem"),
    ("rifampin + isoniazid",       "synergy",     "INH activates KatG; rifampin blocks RNA pol; bactericidal combo"),
    ("ciprofloxacin + nitrofurantoin","antagonism","NFT-induced quiescence reduces FQ uptake into actively dividing cells"),
    ("β-lactam + chloramphenicol", "antagonism",  "CHL is bacteriostatic; β-lactams need active growth"),
    ("trimethoprim + sulfamethoxazole","synergy", "sequential blockade of folate synthesis (DHFR + DHPS)"),
]
def synth_combo_therapy(rng, pathogen) -> dict:
    pair, kind, reason = rng.choice(COMBO_PAIRS)
    msgs = [
        {"role": "system", "content":
            "You reason about combination antibiotic therapy: synergy, antagonism, indifference."},
        {"role": "user", "content":
            f"For {pathogen}, would the combination of {pair} show synergy or antagonism?"},
        {"role": "assistant", "content":
            f"COMBO: {pair}\n"
            f"INTERACTION: {kind}\n"
            f"MECHANISM: {reason}\n"
            f"FRACTIONAL INHIBITORY CONCENTRATION (FIC) prediction: "
            + ("< 0.5 — synergy" if kind == "synergy" else "> 4 — antagonism")},
    ]
    return {"task": "combo_therapy", "pathogen": pathogen, "messages": msgs}


# ============================================================================
# Driver
# ============================================================================
GENERATORS = {
    "self_correction":         (1000, synth_self_correction,       True),
    "confidence":              (1000, synth_confidence,             True),
    "counterfactual":          (1000, synth_counterfactual,         True),
    "failure_postmortem":      ( 800, synth_failure_postmortem,     True),
    "prior_art":               ( 800, synth_prior_art,              True),
    "multi_pathogen":          ( 800, None,                         False),  # special — uses pair
    "cross_resistance":        ( 500, synth_cross_resistance,       False),
    "pkpd":                    ( 800, synth_pkpd,                   True),
    "stewardship":             ( 500, synth_stewardship,            True),
    "time_budget":             ( 500, synth_time_budget,            False),
    "disambiguation":          ( 500, synth_disambiguation,         False),
    "manufacturing":           ( 300, synth_manufacturing,          True),
    "clinical_population":     ( 500, synth_clinical_population,    True),
    "adverse_events":          ( 500, synth_adverse_events,         True),
    "animal_translation":      ( 500, synth_animal_translation,     True),
    "combo_therapy":           ( 500, synth_combo_therapy,          False),
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0xDEAF_BABE)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    counts: dict[str, int] = {}
    for label, (target, fn, needs_anchor) in GENERATORS.items():
        out_path = OUT / f"agentic_{label}.jsonl"
        if out_path.exists(): out_path.unlink()
        n_per_pathogen = max(1, target // len(PATHOGENS))
        with open(out_path, "a") as f:
            if label == "multi_pathogen":
                # Special: cross-pathogen pairs
                for _ in range(target):
                    pair = rng.sample(PATHOGENS, 2)
                    p_anchor = pair[0]
                    if p_anchor not in DRUG_ANCHORS: continue
                    anchor = rng.choice(DRUG_ANCHORS[p_anchor])
                    tr = synth_multi_pathogen(rng, pair, anchor)
                    f.write(json.dumps(tr) + "\n")
                    counts[label] = counts.get(label, 0) + 1
            else:
                for pathogen in PATHOGENS:
                    if pathogen not in DRUG_ANCHORS or not DRUG_ANCHORS[pathogen]:
                        continue
                    anchors = DRUG_ANCHORS[pathogen]
                    for _ in range(n_per_pathogen):
                        if needs_anchor:
                            tr = fn(rng, pathogen, rng.choice(anchors))
                        else:
                            tr = fn(rng, pathogen)
                        f.write(json.dumps(tr) + "\n")
                        counts[label] = counts.get(label, 0) + 1
    total = sum(counts.values())
    print(f"\nTotal new rows: {total:,}")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  agentic_{k:<26s}: {v:>5,}")


if __name__ == "__main__":
    main()
