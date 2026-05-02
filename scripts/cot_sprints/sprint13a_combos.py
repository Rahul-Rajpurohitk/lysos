"""Sprint 13a — 12 drug_combination_synergy examples.
Non-overlapping with Sprint 4. Targets: novel combos, salvage regimens, biofilm, TB."""
import json
from pathlib import Path

OUT = Path("data/synthetic/named_drug_examples.jsonl")

INSTR = ("Instructions: Explain the mechanistic rationale for the named drug combination. "
         "Cover (1) the clinical indication and bacterial target, (2) why monotherapy fails, "
         "(3) the molecular interaction between the two agents (PK potentiation, "
         "permeabilization, sequential pathway block, target diversification, persister kill), "
         "(4) the resistance-suppression argument, and (5) clinical-trial evidence or "
         "guideline-level adoption. Be specific about doses, ratios, and approval status.")

ITEMS = [
    ("RIFAMPIN + VANCOMYCIN for prosthetic valve / hardware-related staphylococcal infection",
     "Rifampin (RNA-pol β subunit, rpoB) plus vancomycin (D-Ala-D-Ala lipid II cap) is the "
     "guideline-recommended adjunct for staphylococcal PVE, prosthetic-joint, and CNS "
     "ventriculitis — settings where biofilm-encased organisms in stationary phase defeat "
     "monotherapy. Vancomycin alone has poor activity against the small-colony variants and "
     "metabolically dormant cells embedded in glycocalyx; rifampin penetrates biofilm matrix "
     "and kills these persisters by halting transcription independent of cell-wall synthesis "
     "rate. Mechanism of synergy: vancomycin disrupts the outermost actively dividing layer; "
     "rifampin diffuses deeper and kills stationary cells. Time-kill shows ≥2-log additional "
     "reduction at 24h vs vancomycin alone for biofilm-grown S. aureus. Critical caveat: "
     "rifampin monotherapy selects single-step rpoB mutants at 10⁻⁷–10⁻⁸; the partner drug "
     "MUST be co-bactericidal — never add rifampin to a non-functional backbone. IDSA 2015 "
     "PVE update + 2013 PJI guidelines recommend rifampin 300–450 mg PO BID for 4–6 weeks "
     "(joint) or full duration (PVE), only after debridement / load reduction. Drug-interaction "
     "burden is severe: rifampin is a CYP3A4 inducer that drops warfarin / tacrolimus / DOAC "
     "levels — clinical pharmacy must adjust before initiation. STAPH-OR (2020) showed survival "
     "benefit in S. aureus bacteremia with hardware. Stewardship: do not use rifampin for "
     "S. aureus bacteremia WITHOUT hardware — adjunctive value is biofilm-specific."),
    ("CEFTAZIDIME-AVIBACTAM for KPC-producing Enterobacterales (CRE) bacteremia",
     "Ceftazidime — a 3G anti-Pseudomonal cephalosporin with C7-aminothiazolyl-oxime — is "
     "obliterated by KPC carbapenemase (Class A serine β-lactamase). Avibactam is a non-β-lactam "
     "diazabicyclooctane (DBO) inhibitor that forms a reversible carbamoyl bond with active-"
     "site Ser70, then re-cyclizes intact and recycles to inhibit additional enzymes — unlike "
     "clavulanate/tazobactam which are suicide inhibitors. Avibactam covers Class A (KPC, "
     "CTX-M, SHV, TEM-ESBLs), Class C (AmpC), and Class D OXA-48 — three of four Ambler classes. "
     "Pairing logic: ceftazidime is a fully active β-lactam vs Pseudomonal-type PBPs; "
     "avibactam restores hydrolysis profile against CRE. Approved 2015, 2.5 g IV q8h (extended "
     "infusion preferred). Trial evidence: RECAPTURE (cUTI), REPRISE (CRE), CRACKLE-2 + PROVE "
     "registries — 30-day mortality 8–13% vs colistin 30–40%. Critical gap: NO activity against "
     "metallo-β-lactamases (NDM, VIM, IMP) — Zn-cofactored MBLs require taniborbactam / "
     "xeruborbactam in development. Resistance has emerged: KPC-31/KPC-33 Ω-loop variants "
     "(D179Y, V240G) eliminate avibactam binding while paradoxically restoring meropenem "
     "susceptibility — the field's first documented avibactam-seesaw. For NDM coexistence, "
     "the salvage combo is ceftazidime-avibactam + aztreonam (aztreonam escapes MBLs; "
     "avibactam covers the co-produced ESBLs). Stewardship: reserve for confirmed CRE."),
    ("ERAVACYCLINE + PIPERACILLIN-TAZOBACTAM for cIAI involving CRE plus possible Pseudomonas",
     "Eravacycline is a fully synthetic fluorocycline (C7-fluoro, C9-pyrrolidinoacetamido) "
     "whose ribosomal A-site binding defeats Tet(M) ribosomal protection and Tet(A/B) efflux — "
     "the two dominant tetracycline-resistance routes. It covers CRE (KPC + NDM), "
     "Acinetobacter, gram-positives, and anaerobes (B. fragilis MIC ≤0.5). Piperacillin-"
     "tazobactam (3.375 g q8h) brings two things eravacycline cannot: (a) reliable Pseudomonas "
     "activity (eravacycline P. aeruginosa MIC₉₀ ≥16 — clinically resistant) and (b) further "
     "Enterobacterales coverage when extended-spectrum strains are present without "
     "carbapenemase. The pairing is intra-abdominal sepsis empiric coverage when CRE is "
     "suspected (recent travel, prior carbapenem exposure, hospital outbreak) and Pseudomonas "
     "cannot be excluded. IGNITE-1/IGNITE-4 trials confirmed eravacycline non-inferior to "
     "ertapenem/meropenem for cIAI. Caveat: tigecycline-class hypotension warning; "
     "eravacycline avoids the tigecycline FDA mortality black-box by achieving higher Cmax/MIC. "
     "Resistance signal: tet(X3/X4/X5) — flavin-dependent monooxygenases that hydroxylate "
     "C11a — are spreading on plasmids and inactivate the entire tetracycline class including "
     "eravacycline; this is a 2019+ emergent threat tracked by CDC/AR Lab Network."),
    ("TIGECYCLINE + COLISTIN for CRAB pneumonia",
     "Acinetobacter baumannii is WHO Priority 1 Critical, intrinsically permeability-restricted, "
     "and CRAB strains carry OXA-23/24/58 carbapenemases plus AdeABC efflux. Colistin "
     "(polymyxin E) binds LPS lipid-A phosphates and disrupts the outer membrane — "
     "permeabilization permits tigecycline (a glycylcycline that already evades Tet(M)/Tet(A) "
     "but suffers from outer-membrane porin restriction) to reach 30S ribosome at higher "
     "intracellular concentration. Synergy is consistent in time-kill: 2-log additional kill "
     "at 24h. Clinical reality is mixed: AIDA trial showed colistin + meropenem NOT superior "
     "to colistin alone for CRAB; INCREMENT-CR registry suggests benefit only in severe "
     "pneumonia where tigecycline lung penetration is otherwise insufficient. IDSA 2022 "
     "CRAB guidance now recommends sulbactam-durlobactam preferred (where available) and "
     "high-dose ampicillin-sulbactam ± minocycline OR cefiderocol as alternatives — "
     "tigecycline + colistin has dropped to third-line. Caveats: tigecycline FDA mortality "
     "black box (loaded 200 mg, then 100 q12h to bypass), colistin nephrotoxicity 30–40%, "
     "no PK rationale for once-daily polymyxin; standard is loading + q12h."),
    ("FOSFOMYCIN IV + MEROPENEM for ESBL/AmpC pyelonephritis with bacteremia",
     "Fosfomycin (MurA — UDP-GlcNAc enolpyruvyl transferase — irreversible suicide inhibitor) "
     "shares no scaffold with β-lactams and bypasses every β-lactamase. Meropenem (PBP-2/3 "
     "carbapenem) covers Pseudomonas and most ESBLs but loses to KPC. Combination rationale "
     "for complicated pyelonephritis with bacteremia: (1) fosfomycin-MurA inhibition weakens "
     "nascent peptidoglycan precursors before transpeptidation, so meropenem-induced PBP-3 "
     "inhibition triggers earlier autolysis (sequential cell-wall block at consecutive "
     "biosynthetic steps); (2) fosfomycin's 70% urinary excretion drives high renal/medullary "
     "tissue concentrations; (3) for KPC-producers, fosfomycin's MurA target is unaffected by "
     "carbapenemases. ZEUS (2019) showed fosfomycin IV non-inferior to pip-tazo for cUTI. "
     "Synergy: in vitro time-kill with KPC-Kp showed 4-log greater kill at 8h vs either alone. "
     "Caveat: fosfomycin IV monotherapy selects rapid murA mutants and uhpT/glpT transporter "
     "loss — NEVER monotherapy for systemic infection. Sodium load 14 mEq/g — watch HF. "
     "Fosfomycin oral (3g sachet) is for uncomplicated cystitis only; NO role in pyelo or "
     "bacteremia (subtherapeutic in tissue)."),
    ("LL-37 antimicrobial peptide + COLISTIN for CF biofilm Pseudomonas",
     "LL-37 is the human cathelicidin (37-aa, amphipathic α-helix) that permeabilizes outer "
     "membrane via electrostatic carpet binding to LPS phosphates — same mechanism class as "
     "colistin but distinct primary structure. The combo achieves: (a) two parallel outer-"
     "membrane attacks at different binding registers, reducing single-step pmrAB/mcr "
     "resistance escape; (b) LL-37 penetrates exopolysaccharide alginate matrix where colistin "
     "is sequestered; (c) sub-MIC LL-37 disperses biofilm by modulating rhlR quorum-sensing. "
     "Pre-clinical evidence: artificial sputum medium plus CF isolate biofilms show 3-log "
     "additional kill at 1× MIC. Translational: LL-37 itself is too short-half-life for "
     "systemic use, but engineered analogs (P-113, OP-145, IDR-1018) are in phase 1–2 for "
     "nebulized CF use. Same biophysical logic drives interest in SPR741/SPR206 (polymyxin-"
     "derived permeabilizers) paired with rifampin/azithromycin — engineered away from "
     "fatty-acyl tail to reduce nephrotoxicity while retaining outer-membrane attack."),
    ("DALBAVANCIN + CEFTAROLINE for refractory MRSA bacteremia with hardware",
     "Dalbavancin is a lipoglycopeptide (vancomycin-derived, with C16-acyl tail and biphenyl-"
     "aryl modifications) with 14-day terminal half-life — single 1500 mg IV dose achieves "
     "MIC-exceeding levels for 3+ weeks. Ceftaroline is a 5G cephalosporin whose acyl-"
     "aminothiadiazole side chain reaches the allosteric site of PBP2a (the MRSA-specific "
     "PBP), opening the active site for transpeptidation inhibition. Seesaw effect: MRSA "
     "isolates with reduced vancomycin susceptibility (hVISA, VISA) frequently show INCREASED "
     "ceftaroline susceptibility because mecA upregulation and pbp4 modulation alter "
     "PBP2a/PBP4 balance. Dalbavancin + ceftaroline = cell-wall attack at two geometrically "
     "distinct steps (lipid II cap vs PBP2a transpeptidation). Real-world salvage cohorts "
     "(Casapao 2018, Shaw 2021) show 70–80% clinical success in vancomycin-failure persistent "
     "MRSA bacteremia, including endocarditis. Long t½ allows weekly outpatient OPAT — major "
     "cost / hospitalization reduction. Caveat: no large RCT; salvage indication; risk of "
     "ceftaroline-induced neutropenia at doses >600 mg q8h."),
    ("BPaMZ regimen (BEDAQUILINE + PRETOMANID + MOXIFLOXACIN + PYRAZINAMIDE) for drug-sensitive TB",
     "Replaces 6-month RIPE with a 4-month all-oral regimen. Each drug hits a different "
     "bacterial state and target. Bedaquiline = F1F0 ATP synthase, kills replicating + dormant "
     "Mtb. Pretomanid = nitroimidazole prodrug activated by F420-dependent Ddn nitroreductase, "
     "releases NO under hypoxia (caseum) and inhibits mycolic-acid synthesis under aerobic "
     "conditions — dual-state killer. Moxifloxacin = DNA gyrase, replicating-cell killer with "
     "good caseum penetration. Pyrazinamide = pyrazinoic acid (POA) accumulation in acidic "
     "phagosome, pH-dependent killer of slow-growers. Four orthogonal mechanisms block "
     "resistance escape (single-step probability 10⁻⁹⁻¹²) and shorten treatment because all "
     "metabolic states are killed simultaneously. SimpliciTB (2024 NEJM) showed BPaMZ "
     "non-inferior at 4 months vs HRZE 6 months for relapse-free cure. Toxicity: QT "
     "prolongation (bedaquiline + moxi additive — baseline ECG required), pretomanid "
     "hepatotoxicity, pyrazinamide hyperuricemia. BPaL (without moxi/pyrazinamide, with "
     "linezolid) is approved for XDR-TB; BPaMZ is the drug-sensitive analog now under WHO "
     "consideration."),
    ("ORITAVANCIN + CEFTRIAXONE for outpatient ABSSSI with MRSA + Streptococcal coverage",
     "Oritavancin is a lipoglycopeptide (chlorobiphenyl tail) with 1200 mg single-dose for "
     "ABSSSI and t½ ~245 hours. Activity: MRSA, VRE (vanA partial — secondary membrane "
     "interaction overcomes vanA at higher MICs), vancomycin-intermediate. ABSSSI presentation "
     "often has mixed pathogens — adding ceftriaxone (1g IM) covers S. pyogenes (oritavancin "
     "is fine but ceftriaxone gives 24h IM depot for outpatient compliance) and ensures "
     "β-hemolytic streptococcal coverage if polymicrobial component present. Single-dose "
     "oritavancin + IM ceftriaxone is a hospital-discharge bridge — treats ABSSSI without "
     "PICC line or daily IV. SOLO trials proved oritavancin monotherapy non-inferior to "
     "vancomycin 7–10 days; real-world diabetic-foot and IVDU populations benefit from the "
     "streptococcal kicker. Critical drug interaction: oritavancin artifactually prolongs "
     "aPTT (binds heparin/phospholipid in collection tube) for 48h, and PT/INR for 24h — "
     "monitor warfarin patients accordingly. Lab notification SOP needed."),
    ("SULBACTAM-DURLOBACTAM for CRAB",
     "Sulbactam is a β-lactamase inhibitor with INTRINSIC anti-Acinetobacter activity — it "
     "binds A. baumannii PBP3 and PBP1, an unusual property among BLIs. CRAB strains, however, "
     "produce OXA-23/24/58 carbapenemases that hydrolyze sulbactam itself plus the AmpC and "
     "ADC enzymes. Durlobactam is a DBO (avibactam-class) with broad β-lactamase coverage "
     "including the OXA carbapenemases. The combo: sulbactam (1g) + durlobactam (1g) + "
     "imipenem-cilastatin (1g, as backbone — durlobactam doesn't fully restore sulbactam "
     "against all CRAB resistance routes; imipenem retains some activity once OXA enzymes "
     "are blocked). ATTACK (2023) trial: non-inferior to colistin for CRAB pneumonia / "
     "bacteremia, with 30-day mortality 19% vs 32% (significant reduction). FDA-approved "
     "2023 — first new CRAB-targeted therapy in a decade. Mechanistic rationale: OXA-23 "
     "(majority of global CRAB) is durlobactam-inhibited; sulbactam (PBP-binder) does the "
     "killing; imipenem (less OXA-hydrolyzed than meropenem in this context) provides "
     "additional PBP coverage. This regimen now displaces colistin/tigecycline for CRAB."),
    ("OMADACYCLINE + LINEZOLID for severe CABP with necrotizing MRSA pneumonia",
     "Omadacycline is an aminomethylcycline (C9-aminomethyl modification) that defeats Tet(M) "
     "and Tet(A/B) like other modernized tetracyclines, with oral + IV bioavailability and "
     "lung tissue concentration suitable for pneumonia. CABP empirical concerns: pneumococcus "
     "(now ~30% macrolide-resistant in US, ~5–10% tet-R), Mycoplasma/Chlamydia (atypical), "
     "S. aureus (post-influenza, IVDU). Omadacycline alone covers all of these. Why add "
     "linezolid? In severe / ICU CABP with confirmed MRSA pneumonia (necrotizing, post-flu), "
     "the toxin-suppression effect of linezolid (50S ribosome — halts translation of PVL, "
     "alpha-hemolysin, TSST-1) is clinically important. Protein synthesis inhibition has an "
     "anti-toxin effect that vancomycin lacks (vanco is a wall-active killer that triggers "
     "release of preformed toxins via lysis). Pairing leverages omadacycline for bacterial "
     "reduction + linezolid for toxin-modulation. CDC/IDSA CABP guidelines do not formally "
     "endorse this duo; it is a tertiary-care approach for necrotizing MRSA pneumonia. "
     "Alternative single-agent: ceftaroline (anti-MRSA + anti-pneumococcal + atypical via "
     "macrolide adjunct). Toxicity: linezolid >14d → thrombocytopenia + lactic acidosis + "
     "MAOI interaction; omadacycline has tigecycline-class GI tolerability."),
    ("PLAZOMICIN + MEROPENEM for CRE + Pseudomonas mixed BSI in transplant recipient",
     "Plazomicin is a next-generation aminoglycoside (sisomicin scaffold modified at C1 with "
     "4-amino-2(S)-hydroxybutyryl group + C6'-hydroxyethyl) that defeats all clinically "
     "relevant aminoglycoside-modifying enzymes (AAC(6'), APH(2''), ANT(2'')) EXCEPT 16S rRNA "
     "methyltransferases (armA, rmtA-H). Meropenem covers Pseudomonas and non-CRE "
     "Enterobacterales. Synergy: plazomicin disrupts protein synthesis at 30S A-site (initial "
     "cidality wave); meropenem hits PBP-3 in dividing cells, inducing autolysis. AG + β-lactam "
     "synergy is a 50-year clinical principle (S. viridans endocarditis the classic) — "
     "shortens time-to-clearance. EPIC and CARE trials: plazomicin non-inferior to meropenem "
     "for cUTI, with mortality benefit in CRE BSI (24-day mortality 12% vs colistin 39%). "
     "For Pseudomonas mixed infection, meropenem is the backbone (plazomicin alone has "
     "variable Pseudomonas activity, MIC₉₀ 16). Caveat: plazomicin nephrotoxicity 11% (lower "
     "than tobramycin/amikacin); pre-treatment screening for armA/rmtB by PCR ideal in "
     "endemic regions (India, Pakistan) where 16S methyltransferases co-spread with NDM-1."),
]

count = 0
with OUT.open("a") as f:
    for i, (combo, response) in enumerate(ITEMS):
        ex = {
            "task": "drug_combination_synergy",
            "split": "train",
            "prompt": f"{INSTR}\n\nCombination: {combo}",
            "response": response,
            "messages": [
                {"role": "user", "content": f"{INSTR}\n\nCombination: {combo}"},
                {"role": "assistant", "content": response},
            ],
        }
        f.write(json.dumps(ex) + "\n")
        count += 1

total = sum(1 for _ in OUT.open())
chars = sum(len(line) for line in OUT.open())
print(f"Wrote {count} drug_combination_synergy examples (Sprint 13a)")
print(f"  total in named_drug_examples.jsonl: {total}")
print(f"  total chars: {chars:,}")
print(f"  approx tokens: {chars // 4:,}")
