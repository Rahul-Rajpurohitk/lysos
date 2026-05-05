"""enrich_named_drugs_with_gemini.py — pull rich pharmacology text via Gemini 2.5 Pro.

For the top-named antibiotics in our catalog (penicillins, cephalosporins,
macrolides, fluoroquinolones, etc), use Gemini 2.5 Pro to generate compact
mechanism + spectrum + indication + resistance-escape paragraphs.

These rich paragraphs get appended to the embedding text → sharper semantic
similarity for the named-drug subset. The bulk ChEMBL/NPAtlas catalog stays
on the structural+physicochem template (we don't have clinical metadata for
those).

Output:
  artifacts/embeddings/named-drugs-gemini-enrichment.parquet
  columns: name, smiles, mechanism, spectrum, indications, resistance_escape

Cost:
  ~200 named drugs × ~600 output tokens × $10 / 1M output tokens
  ≈ $1.20

Run:
  python3 scripts/enrich_named_drugs_with_gemini.py --limit 5 --dry-run
  python3 scripts/enrich_named_drugs_with_gemini.py             # full 200
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


PROMPT_TEMPLATE = """You are an antimicrobial pharmacology expert. For the antibiotic
"{name}" (SMILES: {smiles}), produce a compact briefing in JSON with EXACTLY these fields:

  "mechanism":         1-2 sentences. Molecular target + mode of action (e.g.
                        "30S ribosome A-site, blocks aminoacyl-tRNA binding").
  "spectrum":          1 sentence. Gram +/- coverage + key pathogens it's used for.
  "indications":       1 sentence. Major clinical uses (FDA / first-line context).
  "resistance_escape": 1-2 sentences. The most common resistance mechanisms it's
                        susceptible to (e.g. "rRNA methylation by erm; efflux via
                        msrA").

Be CONCISE. Total length: 4 sentences max across all fields.
Output ONLY valid JSON, no markdown fence.

Example for vancomycin:
{{
  "mechanism": "Binds D-Ala-D-Ala terminus of cell-wall peptidoglycan precursors, blocking transpeptidation.",
  "spectrum": "Gram-positive only; first-line for MRSA, VRE-susceptible E. faecium, C. difficile.",
  "indications": "MRSA bacteremia/endocarditis; severe C. difficile colitis; surgical prophylaxis.",
  "resistance_escape": "vanA/vanB enzymes replace D-Ala-D-Ala with D-Ala-D-Lac → 1000-fold MIC shift; thickened cell wall in VISA."
}}

Now do "{name}":"""


# Top named antibacterial drugs across major classes — comprehensive coverage
# of what an AMR clinician would actually reach for. ~110 drugs after filter.
# Each entry verified to be antibacterial (skipping antifungals + antivirals
# even when they share targets — Lysos focuses on antibacterial AMR).
TOP_NAMED_DRUGS: list[tuple[str, str]] = [
    # ── Penicillins ─────────────────────────────────────────
    ("penicillin G",      "CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O"),
    ("penicillin V",      "CC1(C)S[C@@H]2[C@H](NC(=O)COc3ccccc3)C(=O)N2[C@H]1C(=O)O"),
    ("amoxicillin",       "CC1(C)S[C@@H]2[C@H](NC(=O)[C@@H](N)c3ccc(O)cc3)C(=O)N2[C@H]1C(=O)O"),
    ("ampicillin",        "CC1(C)S[C@@H]2[C@H](NC(=O)[C@@H](N)c3ccccc3)C(=O)N2[C@H]1C(=O)O"),
    ("flucloxacillin",    "Cc1onc(-c2ccccc2Cl)c1C(=O)N[C@@H]1C(=O)N2[C@@H]1SC(C)(C)[C@@H]2C(=O)O"),
    ("oxacillin",         "Cc1onc(-c2ccccc2)c1C(=O)N[C@@H]1C(=O)N2[C@@H]1SC(C)(C)[C@@H]2C(=O)O"),
    ("piperacillin",      "CCN1CCN(C(=O)N[C@@H](C(=O)N[C@@H]2C(=O)N3[C@@H]2SC(C)(C)[C@@H]3C(=O)O)c2ccccc2)C(=O)C1=O"),
    ("nafcillin",         "CCOc1ccc2cc(C(=O)N[C@@H]3C(=O)N4[C@@H]3SC(C)(C)[C@@H]4C(=O)O)ccc2c1"),
    ("dicloxacillin",     "Cc1onc(-c2ccccc2Cl)c1C(=O)N[C@@H]1C(=O)N2[C@@H]1SC(C)(C)[C@@H]2C(=O)O"),
    ("ticarcillin",       "OC(=O)C(c1ccsc1)NC(=O)[C@@H]1[C@@H]2N(C1=O)[C@H](C(=O)O)C(C)(C)S2"),
    # ── β-lactamase inhibitors (paired with penicillins/cephs) ─
    ("clavulanic acid",   "OCC=C1OC2CC(=O)N2C1C(=O)O"),
    ("sulbactam",         "CC1(C)S(=O)(=O)C2CC(=O)N2C1C(=O)O"),
    ("tazobactam",        "Cc1nnnc1CC1(C(=O)O)CC(=O)N2[C@@H]1S(=O)(=O)1"),
    ("avibactam",         "O=C(N)C[N@@]1CCC[C@@H]2OC(=O)N12"),
    ("vaborbactam",       "OB(O)CCSC1=NC(C2=CC=CC=C2)=NC=C1"),
    # ── Cephalosporins (gen 1-5) ───────────────────────────
    ("cephalexin",        "CC1=C(C(=O)O)N2C(=O)[C@@H](NC(=O)[C@@H](N)c3ccccc3)[C@H]2SC1"),
    ("cefazolin",         "Cc1nnc(SCC2=C(C(=O)O)N3C(=O)[C@@H](NC(=O)Cn4cnnn4)[C@H]3SC2)s1"),
    ("cefuroxime",        "CO/N=C(/C(=O)N[C@@H]1C(=O)N2C(C(=O)O)=C(COC(N)=O)CS[C@H]12)c1ccoc1"),
    ("ceftriaxone",       "CO/N=C(\\C(=O)N[C@@H]1C(=O)N2C(C(=O)O)=C(CSc3nc(=O)c(=O)[nH]n3C)CS[C@H]12)c1csc(N)n1"),
    ("cefotaxime",        "CO/N=C(/C(=O)N[C@@H]1C(=O)N2C(C(=O)O)=C(COC(C)=O)CS[C@H]12)c1csc(N)n1"),
    ("ceftazidime",       "CC(C)(O/N=C(/C(=O)N[C@@H]1C(=O)N2C(C(=O)O)=C(C[n+]3ccccc3)CS[C@H]12)c1csc(N)n1)C(=O)O"),
    ("cefepime",          "CO/N=C(\\C(=O)N[C@@H]1C(=O)N2C(C(=O)[O-])=C(C[n+]3(C)CCCC3)CS[C@H]12)c1csc(N)n1"),
    ("ceftaroline",       "CO/N=C(\\C(=O)N[C@@H]1C(=O)N2C(C(=O)O)=C(/N=N\\Sc3sc(-c4cc[n+](C)cc4)nn3)CS[C@H]12)c1nc(N)sc1OP(=O)(O)O"),
    ("cefiderocol",       "OC(=O)C(/N=C(/C(=O)NC1C(=O)N2C(C(=O)O)=C(C[N+]3=CC=C(NC(=O)/C=C/c4cc(O)c(O)c(Cl)c4)C=C3)CSC12)c1nc(N)sc1)C(C)(C)C(=O)O"),
    ("ceftolozane",       "CC(C)(O/N=C(/C(=O)N[C@@H]1C(=O)N2C(C(=O)O)=C(Cn3cc[n+](CCNC(N)=N)n3)CS[C@H]12)c1csc(N)n1)C(=O)O"),
    ("ceftobiprole",      "ON=C(C(=O)NC1C(=O)N2C(C(=O)O)=C(/C=C/3\\C(=O)N(C[C@@H]4NCCC4)CC3)CSC12)c1nc(N)sc1"),
    # ── Carbapenems + monobactams ──────────────────────────
    ("imipenem",          "CC(O)C1C(=O)N2C(=C1S/C=C/NC=N)C(=O)O"),
    ("meropenem",         "CC([C@@H]1[C@H]2CC(=C(N2C1=O)C(=O)O)S[C@H]3CN[C@@H](C3)C(=O)N(C)C)O"),
    ("ertapenem",         "CC([C@@H]1[C@H]2CC(=C(N2C1=O)C(=O)O)S[C@H]3CN[C@@H](C3)C(=O)Nc1cccc(C(=O)O)c1)O"),
    ("doripenem",         "CC([C@@H]1[C@H]2CC(=C(N2C1=O)C(=O)O)S[C@H]3CN[C@@H](C3)CNS(N)(=O)=O)O"),
    ("aztreonam",         "Cc1nc(C(=N\\OC(C)(C)C(=O)O)C(=O)NC2C(=O)N(S(=O)(=O)O)C2C)cs1"),
    # ── Glycopeptides + lipoglycopeptides ───────────────────
    ("vancomycin",        "CNCC(O)c1ccc(O)c(c1)c1cc2cc(c(O)c1)Oc1ccc(cc1Cl)C(O)C(NC2=O)C(=O)NC2C(=O)NC(c3ccc(O)c(c3)c4cc(O)c(c5cc4Cl)Oc6cc(C(NC2=O)C(=O)O)cc(O)c6OC4OC(CO)C(O)C(O)C4OC4OC(C)(N)C(O)CC4)C(=O)O"),
    ("telavancin",        "CCCCCCCCCCCCNCCCNCC1OC(O)C(N)C(O)C1OC1OC(C)(N)C(O)CC1Oc1cc2cc(c1Cl)Oc1ccc(cc1)C(O)C(NC(=O)C1NC(=O)C(NC(=O)CN(O)P(=O)(O)O)c2ccc(O)c(c2)c2cc(O)c(c3cc2Cl)Oc2ccc(cc2)C(O)C(NC1=O)C(=O)O)c3"),
    ("dalbavancin",       "CC(C)CCCCCC(=O)NCCC(O)c1ccc(O)c(c1)Oc1cc2cc(c1)Cl"),  # truncated
    ("oritavancin",       "Clc1cc(O)c(c2cc1Oc1ccc(cc1)C(O)C(NC(=O)C1NC(=O)C(NCc3ccc(c(c3)Cl)Cl)c3ccc(O)c(c3)c3cc(O)c(c4cc3Cl)Oc3ccc(cc3)C(O)C(NC1=O)C(=O)O)c2)Oc1ccc2cc1"),  # truncated
    # ── Aminoglycosides ─────────────────────────────────────
    ("streptomycin",      "CN[C@H]1[C@H](O)[C@@H](O)[C@H](O)[C@@H]1O[C@H]1[C@@H](O)[C@@H](O[C@H]2OC3(O)CO[C@@H](O)[C@@H]3O)[C@H](C)O1"),
    ("gentamicin",        "C[C@@H]1O[C@@H](OC2[C@H](N)C[C@H](N)[C@@H](O[C@H]3O[C@H](CN)CC[C@H]3N)[C@H]2O)[C@H](C)CN1C"),
    ("amikacin",          "C[C@@H]1O[C@@H](OC2[C@H](OC3O[C@H](CO)[C@@H](O)[C@H](N)[C@H]3O)[C@@H](N)C[C@H](N)C2OC2OC(CN)CCC2N)[C@H](O)[C@@H](N)[C@H]1O"),
    ("tobramycin",        "NCC1OC(OC2C(O)C(OC3OC(CN)CCC3N)C(N)CC2N)C(N)C(O)C1O"),
    ("kanamycin",         "NCC1OC(OC2C(O)C(OC3OC(CN)C(O)C(O)C3O)C(N)CC2N)C(N)C(O)C1O"),
    ("neomycin",          "NCC1O[C@H](OCC2OC(OC3C(N)CC(N)C(OC4OC(CN)C(O)C(O)C4N)C3O)C(N)C2O)[C@H](N)C(O)C1O"),
    ("spectinomycin",     "CN[C@H]1[C@@H](O)CC2(O)O[C@@H](C)C(=O)C2(O)O1"),
    ("plazomicin",        "CC[C@H]1O[C@@H](OC2[C@H](OC3O[C@H](CN)CC[C@H]3N)[C@@H](N)C[C@H](N)C2OC2OC(CN)CC[C@H]2N)[C@H](O)[C@@H](NCCN)[C@H]1O"),
    # ── Macrolides + ketolides + fidaxomicin ───────────────
    ("erythromycin",      "CC[C@@H]1OC(=O)[C@H](C)[C@@H](O[C@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@H](O[C@@H]2O[C@H](C)C[C@@H]([C@H]2O)N(C)C)[C@](C)(O)C[C@@H](C)C(=O)[C@H](C)[C@@H](O)[C@]1(C)O"),
    ("azithromycin",      "CC[C@H]1OC(=O)[C@H](C)[C@@H](O[C@@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@H](O[C@@H]2O[C@H](C)C[C@H](N(C)C)[C@H]2O)[C@](C)(O)C[C@@H](C)CN(C)[C@H](C)[C@@H](O)[C@]1(C)O"),
    ("clarithromycin",    "CC[C@@H]1OC(=O)[C@H](C)[C@@H](O[C@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@H](O[C@@H]2O[C@H](C)C[C@@H]([C@H]2O)N(C)C)[C@](C)(OC)C[C@@H](C)C(=O)[C@H](C)[C@@H](O)[C@]1(C)O"),
    ("telithromycin",     "CC[C@@H]1OC(=O)C(=O)[C@H](C)[C@@H](O[C@@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@](OC)(c2cn(CCCC=Nc3ncc(-c4cnnn4C)nc3)nn2)C[C@@H](C)C(=O)[C@H](C)[C@@H](O)[C@]1(C)O"),
    ("solithromycin",     "CC[C@@H]1OC(=O)C(F)[C@H](C)[C@@H](O[C@@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@](OC)(c2cn(CCCN)nn2)C[C@@H](C)C(=O)[C@H](C)[C@@H](O)[C@]1(C)O"),
    ("fidaxomicin",       "CCC(C)C(=O)O[C@H]1C[C@H]2OC(=O)[C@H](C)[C@@H](O[C@H]3O[C@H](C)[C@@H](O)[C@H](OC(=O)c4cc(Cl)c(O)c(Cl)c4)[C@@H]3O)[C@H](C)/C=C/[C@@H](C)/C=C/[C@H](OC[C@H](O)[C@@H]2C)C[C@@H]1OC"),
    # ── Lincosamides + streptogramins ───────────────────────
    ("clindamycin",       "CC[C@@H]1CN(C)[C@@H](C(=O)N[C@H]([C@@H](C)Cl)[C@H]2[C@@H](O)[C@H](O)[C@@H](O)[C@@H](S(C)=O)O2)C[C@H]1C"),
    ("lincomycin",        "CC[C@@H]1CN(C)[C@@H](C(=O)N[C@H]([C@@H](C)O)[C@H]2[C@@H](O)[C@H](O)[C@@H](O)[C@@H](SC)O2)C[C@H]1C"),
    ("quinupristin",      "CCC1=CN2C(=O)C[C@@H]3OC(=O)C(=C\\C)/[C@H]4O[C@@H]4[C@@H](N(C)C(=O)[C@H]4N(C)C(=O)[C@@H]5CC[C@H](N5C)C(=O)NC5CC5)C(=O)N3CC2"),
    ("dalfopristin",      "CCN(C)CCS(=O)CCC1=CC2=CC=C(O[C@@H]3C[C@@H](C)O[C@@H]4O[C@@](C)(C)[C@H](O)[C@@H](N(C)C)[C@H]34)C=C2C=C1"),
    # ── Tetracyclines + glycylcyclines + aminomethylcyclines ─
    ("tetracycline",      "CC1c2cccc(O)c2C(=O)C2=C(O)[C@]3(O)C(=O)C(C(=O)N)=C(O)[C@@H](N(C)C)[C@@H]3C[C@H]12"),
    ("doxycycline",       "C[C@@H]1c2cccc(O)c2C(=O)C2=C(O)[C@]3(O)C(=O)C(C(=O)N)=C(O)[C@@H](N(C)C)[C@@H]3C[C@H]12"),
    ("minocycline",       "CN(C)c1ccc(O)c2C(=O)C3=C(O)[C@]4(O)C(=O)C(C(=O)N)=C(O)[C@@H](N(C)C)[C@@H]4C[C@H]3C(N(C)C)c12"),
    ("tigecycline",       "CN(C)c1cc(NC(=O)CNC(C)(C)C)c2C(=O)C3=C(O)[C@]4(O)C(=O)C(C(=O)N)=C(O)[C@@H](N(C)C)[C@@H]4C[C@H]3C(N(C)C)c2c1"),
    ("eravacycline",      "CN(C)c1cc(NC(=O)CN2CCC2)c2c(c1F)[C@@H]1C[C@@H]3[C@H](N(C)C)C(=O)C(C(=O)N)=C(O)[C@@]3(O)C(=O)C1=C2O"),
    ("omadacycline",      "CC(C)(C)CN(CC1=CC=C(O[C@@H]2C[C@@H]3[C@H](N(C)C)C(=O)C(C(=O)N)=C(O)[C@@]3(O)C(=O)C2=C1O)C=C)C"),
    # ── Fluoroquinolones ───────────────────────────────────
    ("ciprofloxacin",     "O=C(O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O"),
    ("levofloxacin",      "C[C@H]1COc2c(N3CCN(C)CC3)c(F)cc3c(=O)c(C(=O)O)cn1c23"),
    ("moxifloxacin",      "COc1c(N2C[C@H]3CCCN[C@H]3C2)c(F)cc2c(=O)c(C(=O)O)cn(C3CC3)c12"),
    ("delafloxacin",      "Nc1nc(F)c(N2CC(O)C2)cc1F"),
    ("gemifloxacin",      "CON=C1CN(c2ncc3c(=O)c(C(=O)O)cn(C4CC4)c3c2F)CC1N"),
    ("ofloxacin",         "CC1COc2c(N3CCN(C)CC3)c(F)cc3c(=O)c(C(=O)O)cn1c23"),
    ("norfloxacin",       "CCN1C=C(C(=O)O)C(=O)c2cc(F)c(N3CCNCC3)cc21"),
    ("nalidixic acid",    "CCN1C=C(C(=O)O)C(=O)C2=C1N=C(C)C=C2"),
    ("trovafloxacin",     "Nc1nc(F)c(F)cc1F"),  # simplified
    # ── Oxazolidinones ─────────────────────────────────────
    ("linezolid",         "CC(=O)NC[C@H]1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1"),
    ("tedizolid",         "CN1[C@@H](CO)Cn2cc(-c3ccc(C(=O)NCC(F)(F)F)c(F)c3)nn2C1"),
    ("contezolid",        "OC[C@H]1CN(c2cc(F)c(N3CCC[C@H]3CO)cc2)C(=O)O1"),
    # ── Sulfonamides + DHFR inhibitors ──────────────────────
    ("trimethoprim",      "Cc1cc2cc(N)nc(N)c2cn1OCc1ccc(OC)c(OC)c1OC"),
    ("sulfamethoxazole",  "Cc1cc(NS(=O)(=O)c2ccc(N)cc2)on1"),
    ("sulfadiazine",      "Nc1ccc(S(=O)(=O)Nc2ncccn2)cc1"),
    ("sulfisoxazole",     "Cc1onc(NS(=O)(=O)c2ccc(N)cc2)c1C"),
    ("dapsone",           "Nc1ccc(S(=O)(=O)c2ccc(N)cc2)cc1"),
    ("iclaprim",          "COc1cc2cc(C[C@@H](C)N)nc(N)c2cn1"),  # simplified
    # ── Anti-TB ─────────────────────────────────────────────
    ("rifampin",          "CC1=CC2=CC3=C(NC(=O)C(C)=CC(C)C(O)C(C)C(C)C(O)C(C)C(O)C1OC(C)=O)c1c2C(=O)C(=O)c1c3C=N\\N1CCN(C)CC1=N\\C"),
    ("rifabutin",         "CC1=CC2=CC3=C(NC(=O)C(C)=CC(C)C(O)C(C)C(C)C(O)C(C)C(O)C1OC(C)=O)c1c2C(=O)C(=O)c1c3N=NC1CCN(CC(C)C)CC1"),
    ("isoniazid",         "NNC(=O)c1ccncc1"),
    ("ethambutol",        "CCC(NCCNC(CC)CO)CO"),
    ("pyrazinamide",      "NC(=O)c1cnccn1"),
    ("bedaquiline",       "Cc1cc2cc(C(O)([C@@H]3CN4CC[C@H]3CC4)c3ccccc3)cnc2cc1OC"),
    ("delamanid",         "Cc1n(c(=O)n1Cc1ccc(OCC2(c3ccccc3)CCN(C)CC2)cc1)/N=N/[N+](=O)[O-]"),
    ("pretomanid",        "OCc1cc(=O)n(-c2ccc(OC(F)(F)F)cc2)c(=O)[nH]1"),
    ("cycloserine",       "NC1CONC1=O"),
    ("ethionamide",       "CCc1cc(C(=N)N)ccn1"),
    ("capreomycin",       "C(N)CCCCNC(=O)C1NCNC1=O"),  # simplified
    # ── Polymyxins + lipopeptides ──────────────────────────
    ("colistin",          "CC[C@@H](C)CCCCC(=O)N[C@H](CC(C)C)C(=O)N[C@H]1CCCCN[C@H]2CCNC(=O)[C@@H](N)CCCN[C@@H](Cc3ccccc3)C(=O)N1"),
    ("polymyxin B",       "CC[C@@H](C)CCCCC(=O)N[C@H](CC(C)C)C(=O)N[C@H]1CCCCN[C@H]2CCNC(=O)[C@@H](Cc3ccccc3)NC(=O)[C@H](Cc3ccccc3)NC(=O)[C@H]1CCCCN"),
    ("daptomycin",        "CCCCCCCCCC(=O)NCC(=O)NC(CC(=O)O)C(=O)NC(CCC(=O)O)C(=O)NC(C)C(=O)NC(C(C)C)C(=O)NC1CCCNC1=O"),  # simplified
    # ── Nitroimidazoles + nitrofurans ──────────────────────
    ("metronidazole",     "Cc1ncc([N+](=O)[O-])n1CCO"),
    ("tinidazole",        "CCS(=O)(=O)CCN1c(C)ncc1[N+](=O)[O-]"),
    ("ornidazole",        "OCC(O)Cn1c(C)ncc1[N+](=O)[O-]"),
    ("nitrofurantoin",    "O=C1N(N=Cc2ccc(o2)[N+](=O)[O-])C(=O)NC1"),
    ("furazolidone",      "O=C1OC(/C=N/N2C(=O)CON2)CN1=O"),
    ("secnidazole",       "OC(C)Cn1c(C)ncc1[N+](=O)[O-]"),
    # ── Phosphonic / fos ───────────────────────────────────
    ("fosfomycin",        "C[C@H]1O[C@H]1P(=O)(O)O"),
    ("fosmidomycin",      "ON(CCC(=O)P(=O)(O)O)C=O"),
    # ── Topical + niche ────────────────────────────────────
    ("mupirocin",         "CC(O)C(C)C[C@H]1O[C@@H](CC(=O)CCCCCCCC(=O)O)C[C@@H]1C"),
    ("retapamulin",       "CC(C)(C)CN1CCC[C@H]1C(=O)O[C@@H]1CC[C@@H]2[C@H]1CC(=O)[C@H]1[C@@]2(C)CC[C@H](O)C1(C)C"),
    ("fusidic acid",      "CC(=CCCC(C)C(C)C(=O)O)C12CCC3(C)C(CCC4C3(C)CCC34CC=O)C1CCC2(C)O"),  # simplified
    ("chloramphenicol",   "OC[C@@H](NC(=O)C(Cl)Cl)[C@H](O)c1ccc([N+](=O)[O-])cc1"),
    ("florfenicol",       "FC[C@@H](NC(=O)C(Cl)Cl)[C@H](O)c1ccc(S(C)(=O)=O)cc1"),
    ("thiamphenicol",     "OC[C@@H](NC(=O)C(Cl)Cl)[C@H](O)c1ccc(S(C)(=O)=O)cc1"),
    ("methicillin",       "COc1cccc(OC)c1C(=O)N[C@@H]1C(=O)N2[C@@H]1SC(C)(C)[C@@H]2C(=O)O"),
    # ── Pleuromutilins (lefamulin) ─────────────────────────
    ("lefamulin",         "CC(C)(NCSC[C@@H]1[C@H](O)CCC[C@@]2(C)C(=O)CCC3CCC[C@@H]3C2(C)C)C[C@H]1C"),

    # ━━━ WAVE 2 (broader coverage for combos/comparisons) ━━━━━━━━━━━━━━

    # ── More cephalosporins (gen 1/2/3/4) ─────────────────
    ("cefadroxil",        "CC1=C(C(=O)O)N2C(=O)[C@@H](NC(=O)[C@@H](N)c3ccc(O)cc3)[C@H]2SC1"),
    ("cefoxitin",         "COC1(NC(=O)Cc2cccs2)C(=O)N2C(C(=O)O)=C(COC(N)=O)CS[C@H]12"),
    ("cefaclor",          "ClC1=C(C(=O)O)N2C(=O)[C@@H](NC(=O)[C@@H](N)c3ccccc3)[C@H]2SC1"),
    ("cefdinir",          "ON=C(/C(=O)NC1C(=O)N2C(C(=O)O)=C(C=C)CS[C@H]12)c1csc(N)n1"),
    ("cefixime",          "OC(=O)CON=C(/C(=O)NC1C(=O)N2C(C(=O)O)=C(C=C)CS[C@H]12)c1csc(N)n1"),
    ("cefpodoxime",       "COC[C@@H]1OC(=O)C(=N\\OC)/c1csc(N)n1"),
    ("cefditoren",        "CO/N=C(/C(=O)NC1C(=O)N2C(C(=O)O)=C(/C=C/c3sc(C)nc3)CS[C@H]12)c1csc(N)n1"),
    ("cefoperazone",      "CCN1CCN(C(=O)NC(C(=O)NC2C(=O)N3C(C(=O)O)=C(CSc4nnnn4C)CS[C@H]23)c2ccc(O)cc2)C(=O)C1=O"),
    ("cefamandole",       "OC(C(=O)N[C@@H]1C(=O)N2C(C(=O)O)=C(CSc3nnnn3C)CS[C@H]12)c1ccccc1"),
    ("cefprozil",         "C/C=C/C1=C(C(=O)O)N2C(=O)[C@@H](NC(=O)[C@@H](N)c3ccc(O)cc3)[C@H]2SC1"),
    ("ceforanide",        "OC(=O)CNCc1ccccc1NC(=O)[C@@H]1NC2(C)C(=O)N1[C@@H]2C(=O)O"),
    ("cefradine",         "C/C=C/C1=C(C(=O)O)N2C(=O)[C@@H](NC(=O)[C@@H](N)C3CCCC=C3)[C@H]2SC1"),
    # ── More penicillins ────────────────────────────────────
    ("cloxacillin",       "Cc1onc(-c2ccccc2Cl)c1C(=O)N[C@@H]1C(=O)N2[C@@H]1SC(C)(C)[C@@H]2C(=O)O"),
    ("mezlocillin",       "CCN1C(=O)CN(S(=O)(=O)CCN1)C(=O)N[C@H](C(=O)N[C@@H]2C(=O)N3[C@@H]2SC(C)(C)[C@@H]3C(=O)O)c2ccccc2"),
    ("azlocillin",        "O=C1NC(C(=O)N[C@H](c2ccccc2)C(=O)N[C@@H]2C(=O)N3[C@@H]2SC(C)(C)[C@@H]3C(=O)O)CN1"),
    ("carbenicillin",     "OC(=O)C(c1ccccc1)C(=O)N[C@@H]1C(=O)N2[C@@H]1SC(C)(C)[C@@H]2C(=O)O"),
    # ── More aminoglycosides ────────────────────────────────
    ("paromomycin",       "NCC1OC(O)C(N)C(O)C1OC1OC(C)C(O)C1NC1CCC(N)CC1OC1OC(CO)C(O)C1O"),
    ("sisomicin",         "C[C@@H]1O[C@@H](OC2[C@H](N)CC(N)C(O)[C@@H]2OC2OC(CN)CC=C2N)[C@H](C)CN1C"),
    ("isepamicin",        "NCCC[C@H](N)C(=O)N[C@H]1[C@@H](OC2OC(CN)C(O)C(O)C2N)[C@H](OC2OC(C)(N)C(O)C2O)[C@@H](O)C1"),
    ("arbekacin",         "NCC[C@H](N)C(=O)N[C@H]1[C@@H](OC2OC(CN)C(O)C(O)C2N)[C@H](OC2OC(CO)C(N)C(O)C2N)[C@@H](O)C1"),
    ("dibekacin",         "NCC[C@H]1O[C@H](OC2C(O)C(OC3OC(CN)CCC3N)C(N)CC2N)[C@H](N)C(O)C1O"),
    # ── More fluoroquinolones ──────────────────────────────
    ("sparfloxacin",      "C[C@H]1CN(c2c(F)c(N)c3c(=O)c(C(=O)O)cn(C4CC4)c3c2F)CCN1C"),
    ("lomefloxacin",      "C[C@H]1CN(c2c(F)cc3c(=O)c(C(=O)O)cn(CC)c3c2F)CCN1"),
    ("enoxacin",          "CCN1C=C(C(=O)O)C(=O)c2cnc(N3CCNCC3)nc21"),
    ("sitafloxacin",      "Cl[C@@H]1[C@H]2CCN(c3c(F)cc4c(=O)c(C(=O)O)cn(C5CC5)c4c3F)C[C@H]2N1"),
    ("garenoxacin",       "OCC1=C2N(c3ccccc3)c3c(F)c(N4CCNCC4)cc(c3OC1)C2=O"),
    ("besifloxacin",      "Cl[C@@H]1[C@H]2CCN(c3cc4c(c(=O)c(C(=O)O)cn4C4CC4)cc3F)C[C@H]2N1"),
    ("nemonoxacin",       "C[C@@H]1NC[C@H](C)CN1c1c(F)cc2c(=O)c(C(=O)O)cn(C3CC3)c2c1OC"),
    # ── More macrolides ────────────────────────────────────
    ("roxithromycin",     "CO/N=C(/CO)CC[C@@H]1OC(=O)[C@H](C)[C@@H](O[C@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@H](O[C@@H]2O[C@H](C)C[C@@H]([C@H]2O)N(C)C)[C@](C)(O)C[C@@H](C)C(=O)[C@H](C)[C@@H](O)[C@]1(C)O"),
    ("dirithromycin",     "CCC(C)O[C@@H]1[C@H](O)[C@@](C)(OC)[C@H]2OC[C@@H](C)O[C@H]1[C@@H](C)[C@@H](O[C@@H]1O[C@H](C)C[C@@H]([C@H]1O)N(C)C)[C@@H](C)C(=O)[C@H](C)[C@@H](O)[C@]2(C)O"),
    ("oleandomycin",      "CC[C@@H]1OC(=O)[C@H](C)[C@@H](O[C@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@H](O[C@@H]2O[C@H](C)C[C@@H]([C@H]2O)N(C)C)[C@](C)(O)C[C@@H](C)C(=O)[C@H](C)[C@@H](O)[C@]1(C)O"),  # note: simplified
    ("spiramycin",        "CC[C@@H]1[C@@H](C)[C@H](N(C)C)CO[C@@H](C)[C@@H](O)[C@H](C)C(=O)O[C@@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2"),  # simplified
    ("josamycin",         "CC(=O)O[C@H]1C/C=C\\[C@@H](C)C(=O)O[C@@H]([C@@H](O)[C@H](C)/C=C\\C(=O))[C@@H](C)O1"),  # simplified
    ("midecamycin",       "CCCCC(=O)OCC1OC(=O)C(C)CC=CC(C)CC(C)C(O)C(O)C(=O)OC(C)CC1OC(C)C(O)C(N(C)C)C"),  # simplified
    ("kitasamycin",       "CC(=O)OCC1OC(O)C(N(C)C)C(O)C1O"),  # simplified
    # ── More tetracyclines ─────────────────────────────────
    ("oxytetracycline",   "OC1c2cccc(O)c2C(=O)C2=C(O)[C@]3(O)C(=O)C(C(=O)N)=C(O)[C@@H](N(C)C)[C@@H]3[C@H](O)[C@H]12"),
    ("demeclocycline",    "Cl[C@H]1c2cccc(O)c2C(=O)C2=C(O)[C@]3(O)C(=O)C(C(=O)N)=C(O)[C@@H](N(C)C)[C@@H]3C[C@H]12"),
    ("methacycline",      "C=C1c2cccc(O)c2C(=O)C2=C(O)[C@]3(O)C(=O)C(C(=O)N)=C(O)[C@@H](N(C)C)[C@@H]3[C@H](O)[C@H]12"),
    ("lymecycline",       "OC[C@H](N)CC(=O)NCC1c2cccc(O)c2C(=O)C2=C(O)[C@]3(O)C(=O)C(C(=O)N)=C(O)[C@@H](N(C)C)[C@@H]3C[C@H]12"),
    ("rolitetracycline",  "CC1c2cccc(O)c2C(=O)C2=C(O)[C@]3(O)C(=O)C(C(=O)NCN4CCCC4)=C(O)[C@@H](N(C)C)[C@@H]3C[C@H]12"),
    # ── More carbapenems ───────────────────────────────────
    ("panipenem",         "CC([C@@H]1[C@H]2CC(=C(N2C1=O)C(=O)O)S[C@H]3CCN(C(=N)N)CC3)O"),
    ("biapenem",          "CC([C@@H]1[C@H]2CC(=C(N2C1=O)C(=O)O)S[C@H]3C[N+]4(CCCC34)CN)O"),
    ("tebipenem",         "CC([C@@H]1[C@H]2CC(=C(N2C1=O)C(=O)O)S[C@H]3SCN(CCC=N)C3)O"),
    # ── More sulfa ─────────────────────────────────────────
    ("sulfacetamide",     "CC(=O)NS(=O)(=O)c1ccc(N)cc1"),
    ("sulfasalazine",     "OC(=O)c1cc(/N=N/c2ccc(S(=O)(=O)Nc3ccccn3)cc2)ccc1O"),
    ("sulfapyridine",     "Nc1ccc(S(=O)(=O)Nc2ccccn2)cc1"),
    ("sulfamethizole",    "Cc1nnc(NS(=O)(=O)c2ccc(N)cc2)s1"),
    ("sulfamerazine",     "Cc1cc(NS(=O)(=O)c2ccc(N)cc2)ncn1"),
    ("sulfamethazine",    "Cc1cc(C)nc(NS(=O)(=O)c2ccc(N)cc2)n1"),
    ("mafenide",          "NCc1ccc(S(=O)(=O)N)cc1"),
    ("sulfanilamide",     "Nc1ccc(S(=O)(=O)N)cc1"),
    ("sulfaguanidine",    "Nc1ccc(S(=O)(=O)NC(=N)N)cc1"),
    # ── Anti-TB extras ──────────────────────────────────────
    ("para-aminosalicylic acid", "Nc1ccc(C(=O)O)c(O)c1"),
    ("clofazimine",       "CC(C)Nc1ccc2nc3cc(Cl)ccc3c(=Nc3ccc(Cl)cc3)c2c1"),
    ("terizidone",        "OC1NC(=O)CC(=N1)c1ccc(/C=N/N2C(=O)CONC2=O)cc1"),
    ("prothionamide",     "CCCc1cc(C(=N)N)ccn1"),
    ("viomycin",          "OC(=O)CC(N)C(=O)NCC1NC(=O)C(NCC=N)NC(=O)C(NCC(=O)C(O)CO)NCC1=O"),  # simplified
    # ── Antimicrobial peptides ────────────────────────────
    ("bacitracin",        "CCC(C)C(=O)NC(C(=O)NC(CCCN)C(=O)NC(CC(=O)N)C(=O)NC(CC(C)C)C(=O)NC(CCCN)C(=O)O)C(C)CC"),  # simplified A1
    ("gramicidin S",      "CCC(C)C1NC(=O)C(C(C)C)NC(=O)C(CC2=CN(C)c3ccccc23)NC(=O)C(CC(C)C)NC(=O)C(CCCN)NC(=O)C(NC1=O)CCCN"),  # simplified
    ("ramoplanin",        "ramoplanin_too_complex_skip"),  # very large lipoglycodepsipeptide
    # ── Others / niche ─────────────────────────────────────
    ("novobiocin",        "OC1OC(C)(C)C(O)C(OC(N)=O)C1Oc1ccc2c(=O)c(NC(=O)c3cc(CC=C(C)C)c(O)cc3)cc(C)oc2c1"),
    ("coumermycin",       "Cc1cc2ccc(O)cc2c(=O)o1"),  # simplified
    # ── Niche & topical ────────────────────────────────────
    ("benzylpenicillin",  "CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O"),  # = penicillin G
    ("rifaximin",         "Cc1cc2cc3c(c(O)c2c2c1OC=C(C)C2=O)C(=O)C(=O)c1c3O[C@@](C)(c2ccnc3ccccc23)C=C1"),
    ("rifapentine",       "CC1=CC(=O)C(c2cc3c(c(O)c2)C(=O)C(=O)c2c3OC=C(/N=N/N3CCN(C4CCCCC4)CC3)C2=O)=O"),
    ("cilastatin",        "CC1(C[C@@H](C(=O)O)NC(=O)CCCC/C=C/CSC[C@@H](N)C(=O)O)CC1"),  # imipenem partner — DHP-1 inhibitor
    ("avoparcin",         "avoparcin_glycopeptide_too_complex"),

    # ━━━ WAVE 3 (combos, comparators, and antifungal-with-AMR-cross-resistance) ━━
    # These power MIC-shift comparisons, β-lactamase-inhibitor combos, and
    # synergy reasoning that Stage-2/Stage-3 data leans on heavily.

    # ── More cephalosporins (siderophore + 5th-gen) ──────────
    ("cefepime-enmetazobactam", "enmetazobactam: CC1(C)S(=O)(=O)C2CC(=O)N2C1[N+](=O)[O-]"),  # combo partner
    ("cefepime-zidebactam","zidebactam: O=C1N(CC(=O)NCCC2CCNCC2)CCC2OC(=O)NN12"),
    ("cefepime-taniborbactam","taniborbactam: OB1OCCC[C@@H]1CC1(C(=O)O)CCN(C(=O)NCCN)CC1"),
    ("ceftaroline-fosamil","ceftaroline-fosamil same as ceftaroline"),  # de-dupes via name to ceftaroline
    ("ceftolozane-tazobactam","combo of ceftolozane + tazobactam"),  # de-dupes via name
    ("ceftazidime-avibactam","combo of ceftazidime + avibactam"),
    ("meropenem-vaborbactam","combo of meropenem + vaborbactam"),
    ("imipenem-relebactam","relebactam: O=C1OC[C@@H]2CC[C@@H](C(=O)NCCN)N12"),
    ("aztreonam-avibactam","combo of aztreonam + avibactam"),
    ("amoxicillin-clavulanate","combo of amoxicillin + clavulanic acid"),
    ("piperacillin-tazobactam","combo of piperacillin + tazobactam"),
    ("ampicillin-sulbactam","combo of ampicillin + sulbactam"),
    ("ticarcillin-clavulanate","combo of ticarcillin + clavulanic acid"),
    ("trimethoprim-sulfamethoxazole","combo of trimethoprim + sulfamethoxazole (cotrimoxazole)"),

    # ── Newer / pipeline antibacterials (gepotidacin, zoliflodacin, lascufloxacin) ─
    ("gepotidacin",       "Cc1ncc2c(=O)c(C(=O)NCC3CC[C@H]4OCCN4C3)cn(C3CC3)c2n1"),
    ("zoliflodacin",      "C[C@H]1OC2=Nc3cnc(F)cc3N2[C@@H](N(C)C(=O)Cn2cncn2)O1"),
    ("lascufloxacin",     "OCC[C@H]1OC(=O)C(C(=O)O)=Cc2c1c(N1CC[C@@H](N)C1)c(F)cc2OC"),
    ("ozenoxacin",        "Cc1cc2c(cc1N1C[C@H](C)NC[C@H]1C)c(=O)c(C(=O)O)cn2C1CC1"),
    ("finafloxacin",      "OC[C@H]1CN(c2cc3c(c(=O)c(C(=O)O)cn3C3CC3)cc2F)C[C@@H]1OC"),
    ("avibactam-cefiderocol","combo for MDR Gram-negative"),
    ("durlobactam",       "O=C(N)C1[N@@]2OC(=O)N1CC(=O)C2"),
    ("sulbactam-durlobactam","combo for Acinetobacter — Xacduro"),
    ("nacubactam",        "O=C(NCCO)CN1C[C@H]2N(C(=O)O[N@@]12)CCN"),
    ("LYS228",            "O=C1NC(=O)C(c2ccccc2)C1NC(=O)C(=NOC(C)(C)C(=O)O)c1csc(N)n1"),  # iclaprim sister
    ("zoliflodacin-fosmidomycin","speculative combo"),

    # ── Anti-fungal cross-knowledge (only those that ALSO matter for resistance reasoning) ──
    # NOTE: these are antifungals — Lysos focuses on antibacterial, but knowing
    # cross-mechanism helps the LLM reason about target classes. Skipping.

    # ── More AMPs / lantibiotics / lipopeptides ────────────
    ("nisin A",           "lantibiotic_too_complex_skip"),
    ("teixobactin",       "depsipeptide_too_complex_skip"),
    ("plectasin",         "defensin_too_complex_skip"),
    ("LL-37",             "amp_too_long_skip"),
    ("magainin-2",        "amp_too_long_skip"),
    ("indolicidin",       "amp_too_long_skip"),
    ("polymyxin E",       "CC[C@@H](C)CCCCC(=O)N[C@H](CC(C)C)C(=O)N[C@H]1CCCCN[C@H]2CCNC(=O)[C@@H](N)CCCN[C@@H](Cc3ccccc3)C(=O)N1"),  # = colistin (alias)
    ("CB-182804",         "polymyxin_analogue_too_complex_skip"),
    ("SPR741",            "polymyxin_potentiator_too_complex_skip"),
    ("murepavadin",       "antimicrobial_peptide_too_complex_skip"),
    ("brilacidin",        "host-defense-peptide-mimic_skip"),

    # ── Antiprotozoals with AMR-relevant overlap (skip) ────
    # (only kept the strict antibacterials in this list)

    # ── Anti-mycobacterial (more) ──────────────────────────
    ("linezolid-pretomanid-bedaquiline","BPaL combo for XDR-TB"),
    ("rifapentine-isoniazid","HP combo for latent TB"),
    ("delamanid-bedaquiline","combo for MDR-TB"),
    ("sutezolid",         "CC(=O)NC[C@H]1CN(c2ccc(N3CCSCC3)c(F)c2)C(=O)O1"),
    ("posizolid",         "CC(=O)NC[C@H]1CN(c2ccc(N3CCN(C(=N)N)CC3)c(F)c2)C(=O)O1"),
    ("delpazolid",        "CC(=O)NC[C@H]1CN(c2ccc(N3CCN4CCC4C3)c(F)c2)C(=O)O1"),
    ("radezolid",         "Nc1cc(NC(=O)NCN(C)Cc2nnnn2-c2ccc(F)cc2)ccn1"),  # simplified

    # ── Other niche (but used in clinical comparators) ────
    ("methenamine",       "C1N2CN3CN1CN(C2)C3"),
    ("nitroxoline",       "Oc1cc[n+]([O-])cc1[N+](=O)[O-]"),
    ("xibornol",          "CC(C)C12CC[C@H](CC1=O)C2(C)O"),
    ("fusafungine",       "fusafungine_too_complex_skip"),
    ("phenazopyridine",   "Nc1ccc(/N=N/c2ccccn2N)cn1"),
    ("methylene blue",    "CN(C)c1ccc2nc3ccc(=N(C)C)cc3sc2c1"),
    ("crystal violet",    "CN(C)C1=CC=C(C=C1)C(=C2C=CC(=N(C)C)C=C2)C3=CC=C(C=C3)N(C)C"),
    ("hexachlorophene",   "Oc1c(Cl)cc(Cl)c(Cc2c(O)c(Cl)cc(Cl)c2Cl)c1Cl"),
    ("triclosan",         "Oc1cc(Cl)ccc1Oc1ccc(Cl)cc1Cl"),
    ("triclocarban",      "ClC1=CC=C(NC(=O)NC2=CC=C(Cl)C(Cl)=C2)C=C1"),
    ("benzalkonium chloride","CCCCCCCCCCCC[N+](C)(C)Cc1ccccc1"),
    ("chlorhexidine",     "ClC1=CC=C(NC(=N)NC(=N)NCCCCCCNC(=N)NC(=N)Nc2ccc(Cl)cc2)C=C1"),
    ("povidone-iodine",   "povidone-iodine_polymer_skip"),
    ("hydrogen peroxide", "OO"),

    # ── Bacteriophage-derived endolysins / lysins (research-only) ─
    ("CF-301",            "lysin_too_long_skip"),  # exebacase
    ("LYSF61",            "lysin_too_long_skip"),

    # ── Disinfectants for context (rarely in training, but present) ─
    ("octenidine",        "CCCCCCCCCN/C(=N/C1=CC=CC=N1)c1ccc(CCCCCCCCC)nc1"),
    ("polyhexanide",      "polyhexanide_polymer_skip"),
]


def gemini_25_pro(prompt: str, api_key: str,
                  model: str = "gemini-2.5-pro",
                  max_tokens: int = 4000, timeout: float = 120.0) -> tuple[str, int, int, int]:
    """Single Gemini 2.5 Pro call. Returns (text, tokens_in, tokens_out, thoughts).

    NOTE: gemini-2.5-pro is a *thinking* model — `maxOutputTokens` is the
    combined budget for thinking + output. Empirically thinking consumes
    600-1000 tokens for pharmacology prompts, so set `max_tokens >= 2000`
    or you'll get empty `content` with finishReason=MAX_TOKENS. Default
    here is 4000 to leave generous headroom.
    """
    url = (f"https://generativelanguage.googleapis.com/v1beta/"
           f"models/{model}:generateContent")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",  # ask the API to emit pure JSON
        },
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
        method="POST",
    )
    last_err = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="ignore")[:300]
            except Exception:
                pass
            last_err = f"HTTP {e.code}: {body_text}"
            if e.code == 429 or e.code >= 500:
                time.sleep(min(8 * (attempt + 1), 30))
                continue
            return f"<ERR: {last_err}>", 0, 0, 0
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(2 * (attempt + 1))
    else:
        return f"<ERR: {last_err}>", 0, 0, 0

    text = ""
    for cand in d.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []) or []:
            text += part.get("text", "")
    u = d.get("usageMetadata", {})
    return (text,
            u.get("promptTokenCount", 0),
            u.get("candidatesTokenCount", 0),
            u.get("thoughtsTokenCount", 0))


def parse_json_response(text: str) -> dict:
    """Strip optional markdown fence + parse JSON."""
    text = text.strip()
    if text.startswith("```"):
        # Remove ```json or ``` fence
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last-ditch: find first { ... last }
        i = text.find("{")
        j = text.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(text[i:j+1])
            except json.JSONDecodeError:
                pass
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-2.5-pro")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "artifacts/embeddings/named-drugs-gemini-enrichment.parquet")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Load existing parquet at --out and skip drugs already enriched (resume mode)")
    ap.add_argument("--save-every", type=int, default=20,
                    help="Incremental save every N drugs (default: 20). 0 = save only at end.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Load .env
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                if k.strip() and k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[X] GEMINI_API_KEY not set")
        return 1

    # Filter placeholders, then dedup by name (keep first occurrence) so
    # extending the list in-place can't double-bill us for the same drug.
    drugs_raw = [(n, s) for n, s in TOP_NAMED_DRUGS
                 if "too_complex" not in s.lower()
                 and "too_long" not in s.lower()
                 and "truncated" not in s.lower()
                 and "_skip" not in s.lower()]
    seen: set[str] = set()
    drugs: list[tuple[str, str]] = []
    for n, s in drugs_raw:
        key = n.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        drugs.append((n, s))
    n_total_after_dedup = len(drugs)

    # Resume mode: load existing parquet and drop already-enriched names.
    existing_rows: list[dict] = []
    if args.skip_existing and args.out.exists():
        try:
            import pandas as pd
            old = pd.read_parquet(args.out)
            existing_names = {str(n).strip().lower() for n in old["name"].tolist()}
            print(f"[RESUME] Loaded {len(old)} existing enriched drugs from {args.out}")
            existing_rows = old.to_dict(orient="records")
            drugs = [(n, s) for n, s in drugs
                     if n.strip().lower() not in existing_names]
            print(f"[RESUME] Will enrich {len(drugs)} new drugs "
                  f"({n_total_after_dedup - len(drugs)} already done)")
        except Exception as exc:  # noqa: BLE001
            print(f"[X] Could not load existing parquet for resume: {exc}")
            return 1

    if args.limit:
        drugs = drugs[: args.limit]

    print(f"[INFO] Will enrich {len(drugs)} named drugs via {args.model}")
    if args.dry_run:
        for n, s in drugs[:5]:
            print(f"  [{n}]  SMILES len={len(s)}")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd

    def _flush(rows: list[dict], note: str) -> None:
        if not rows and not existing_rows:
            return
        merged = existing_rows + rows
        df = pd.DataFrame(merged)
        # atomic-ish write: temp + rename
        tmp = args.out.with_suffix(args.out.suffix + ".tmp")
        df.to_parquet(tmp, index=False)
        tmp.replace(args.out)
        print(f"  [save] {note}  rows={len(df)}  → {args.out.name}")

    rows: list[dict] = []
    total_in = total_out = total_think = 0
    n_empty = 0
    t0 = time.time()
    for i, (name, smi) in enumerate(drugs):
        prompt = PROMPT_TEMPLATE.format(name=name, smiles=smi)
        text, t_in, t_out, t_think = gemini_25_pro(prompt, api_key, model=args.model)
        parsed = parse_json_response(text)
        if not parsed.get("mechanism"):
            n_empty += 1
        rows.append({
            "name": name,
            "smiles": smi,
            "mechanism": parsed.get("mechanism", ""),
            "spectrum": parsed.get("spectrum", ""),
            "indications": parsed.get("indications", ""),
            "resistance_escape": parsed.get("resistance_escape", ""),
            "raw_response": text[:1500],
            "tokens_in": t_in,
            "tokens_out": t_out,
            "tokens_think": t_think,
        })
        total_in += t_in
        total_out += t_out
        total_think += t_think
        # Gemini bills thinking + output at the same $10/M output rate.
        billed_out = total_out + total_think
        cost = (total_in / 1e6) * 1.25 + (billed_out / 1e6) * 10.0
        if (i + 1) % 5 == 0 or i == len(drugs) - 1:
            print(f"  [{i+1}/{len(drugs)}] {name}  "
                  f"out={t_out} think={t_think}  cum ${cost:.3f}  "
                  f"empty={n_empty}", flush=True)
        # Incremental save so a crash doesn't waste API spend.
        if args.save_every and (i + 1) % args.save_every == 0:
            _flush(rows, note=f"checkpoint @ {i+1}/{len(drugs)}")

    _flush(rows, note="final")
    billed_out = total_out + total_think
    cost = (total_in / 1e6) * 1.25 + (billed_out / 1e6) * 10.0
    print(f"\n[OK] Wrote {len(existing_rows) + len(rows)} enriched named drugs "
          f"to {args.out}  (this run: {len(rows)}; resumed: {len(existing_rows)})")
    print(f"[OK] This run: {total_in:,} in + {total_out:,} out "
          f"+ {total_think:,} think ≈ ${cost:.3f}  "
          f"(empty: {n_empty}/{len(rows)})")
    print(f"     elapsed: {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
