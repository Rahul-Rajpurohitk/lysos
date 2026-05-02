"""Sprint 13c — 12 pathogen_specific_dive examples."""
import json
from pathlib import Path

OUT = Path("data/synthetic/named_drug_examples.jsonl")

INSTR = ("Instructions: Provide a deep clinical-microbiology profile of the named pathogen. "
         "Cover (1) Gram status / cell envelope, (2) ecological niche / transmission, "
         "(3) intrinsic resistome and dominant acquired mechanisms, (4) standard-of-care "
         "regimen with drug rationale, and (5) drug-discovery gaps. Cite WHO/CDC tier.")

ITEMS = [
    ("Vancomycin-resistant Enterococcus (VRE) — beyond vanA",
     "Gram-positive cocci, intrinsically tolerant: low PBP affinity for cephalosporins "
     "(intrinsic R), low aminoglycoside uptake (low-level R), lipid II precursors that allow "
     "vancomycin escape via vanA/B/D. E. faecalis retains ampicillin-S (PBP4 binding); "
     "E. faecium is the epidemic VRE — ampicillin-R + vanco-R + high-level AG-R nosocomial. "
     "Niche: GI commensal; UTI, BSI, endocarditis (right-sided IVDU), abdominal. WHO Priority "
     "2 High. Treatment: E. faecalis = ampicillin + ceftriaxone (PBP4/5 sequential, NEJM 2013 "
     "Fernández-Hidalgo) for endocarditis. E. faecium VRE = linezolid (50S, oral), daptomycin "
     "high-dose 8–10 mg/kg ± ampicillin, tigecycline (bacteriostatic), oritavancin "
     "(lipoglycopeptide overcomes vanA partially), Synercid (E. faecium only). Newer: "
     "omadacycline, eravacycline. Linezolid-R via 23S G2576U + plasmid optrA/poxtA emerging. "
     "Stewardship: don't treat asymptomatic GI carriage. Discovery gaps: oral VRE-active "
     "agent (linezolid OK but BMS warning), faster cidality vs biofilm endocarditis."),
    ("Mycobacterium abscessus — rapid-growing NTM nightmare",
     "Subsp. abscessus, massiliense, bolletii. Rapidly-growing, intrinsically MDR NTM. Niche: "
     "water (tap, biofilms), hospital plumbing (post-surgical: cardiac, breast, lipo, eye), "
     "chronic CF lung. Envelope: thick mycolic acid + porins restrictive. Intrinsic resistome: "
     "(a) erm(41) inducible 23S MTase (macrolide-R; only abscessus full erm; massiliense "
     "truncated/non-functional); (b) MAB_2875 β-lactamase; (c) AGE 16S MTase basal; "
     "(d) low-permeability outer mycomembrane. Treatment: 12+ months 3-drug. IV phase: "
     "amikacin + imipenem + tigecycline ± cefoxitin. Oral: azithromycin (only if erm-"
     "truncated) + clofazimine + linezolid + bedaquiline (off-label). Surgical resection "
     "often required. Cure 30–50%. CFTR-modulator era: M. abscessus prevalence in CF "
     "increasing. Discovery: bedaquiline, clofazimine, GSK '656, telacebec (cytochrome bc). "
     "Diagnosis: AFB + 16S/hsp65 sequencing, erm(41) PCR for macrolide-tx prediction. "
     "Archetype of why we need new mycobacterial drugs."),
    ("Burkholderia cepacia complex (Bcc) — CF lung enigma",
     "Complex of 20+ gram-negative species (B. cenocepacia, B. multivorans, B. dolosa). "
     "Environmental (soil, water, plant rhizosphere), devastating in CF lung. WHO Priority 1. "
     "Cell envelope: LPS with O-antigen variations, prominent biofilm, intrinsic high-level "
     "polymyxin-R via constitutive 4-amino-arabinose lipid-A modification. Intrinsic "
     "resistome: chromosomal AmpC (highly inducible), PenA β-lactamase, polymyxin intrinsic-"
     "R, AmrAB-OprA + BpeAB-OprB efflux, intrinsic carbapenem-R. Acquired: cepacia syndrome "
     "(necrotizing pneumonia + bacteremia, post-transplant contraindication; B. cenocepacia "
     "ET-12 lineage transmissible CF-to-CF). Treatment: TMP-SMX (preferred per CFF), "
     "ceftazidime ± avibactam, meropenem (variable), tigecycline / minocycline, "
     "chloramphenicol. Combinations standard. Salvage: cefiderocol, eravacycline, phage "
     "(case-report). Drug-discovery: Bcc historically excluded from screens; recent WHO "
     "priority push."),
    ("Stenotrophomonas maltophilia — post-broad-spectrum bug",
     "Aerobic gram-negative bacillus, environmental ubiquitous, classic post-broad-spectrum/"
     "post-carbapenem opportunist (ICU pneumonia, line BSI, neutropenic fever, CF lung). "
     "Envelope: standard gram-neg. Key feature: INTRINSIC RESISTANCE to all β-lactams via "
     "two chromosomal β-lactamases — L1 (Class B Zn-MBL, hydrolyzes carbapenems) + L2 "
     "(Class A serine, hydrolyzes ceftaz/ceftriaxone). NO β-lactam works clinically except "
     "aztreonam-avibactam in development. SmeABC + SmeDEF efflux contribute FQ + tet-R. "
     "Treatment: TMP-SMX is GOLD STANDARD (folate two-target). Levofloxacin OK milder. "
     "Tigecycline, eravacycline. Minocycline/doxycycline. Cefiderocol works (siderophore "
     "Trojan horse bypasses L1/L2). Severe: TMP-SMX + minocycline OR TMP-SMX + cefiderocol. "
     "Stewardship: preserve TMP-SMX. Resistance via sul1 + dfrA emerging (~10% some regions) "
     "→ collapse to minocycline + cefiderocol."),
    ("Achromobacter xylosoxidans — 'other' CF / immunocompromised opportunist",
     "Aerobic gram-negative bacillus. Niche: environmental, CF lung + hematologic-malignancy "
     "infection. Intrinsic high-level penicillin-R + cefepime-R via AmpC induction. "
     "Susceptibility highly variable: typically TMP-SMX, pip-tazo, imipenem/meropenem, "
     "ceftazidime, sometimes minocycline. Less reliable: levofloxacin, amikacin. Ceftaz-avi "
     "marginal. Cefiderocol reasonable in-vitro. Eravacycline marginal. Treatment: pip-tazo "
     "OR meropenem + minocycline; severe ICU pneumonia: meropenem + colistin (variable) or "
     "cefiderocol. Mortality bacteremia/pneumonia 25–40%. CF chronic colonization difficult "
     "to eradicate; nebulized colistin marginal. Discovery: largely overlooked — pharma "
     "stopped at top-6 ESKAPE."),
    ("Bacillus anthracis — bioterrorism + cutaneous + inhalational anthrax",
     "Aerobic gram-positive spore-forming bacillus. Capsule (poly-γ-D-glutamic acid, plasmid "
     "pXO2) + tripartite toxin (PA + LF + EF, plasmid pXO1). Spores from contaminated soil/"
     "products → cutaneous (95%), inhalational (post-spore aerosol), GI, injection. "
     "Inhalational post-spore exposure = bioterrorism scenario (2001 US attacks). Treatment: "
     "cipro + meropenem (or doxy) + linezolid (toxin-suppression) for inhalational/severe. "
     "Plus monoclonal antitoxin (raxibacumab, obiltoxaximab) targeting protective antigen. "
     "Cutaneous: cipro or doxy alone, 60d. Post-exposure prophylaxis: cipro/doxy + AVA "
     "vaccine, 60d. Concern: weaponized strain susceptibility unknown; engineered FQ-R or "
     "β-lactam-R spores theoretically possible. CDC/USAMRIID stockpiles: cipro, doxy, anti-PA "
     "mAbs, AVA. Spores survive decades; soil decontamination near-impossible. Discovery: "
     "linezolid + novel toxin-modulator."),
    ("Francisella tularensis — tularemia / 'rabbit fever' / Tier 1 select agent",
     "Small intracellular gram-negative coccobacillus, facultative intracellular pathogen. "
     "Niche: ticks (Dermacentor), rabbits, rodents; transmission via tick bite, animal "
     "handling, aerosol (laboratory + bioterrorism), water. Tier 1 select agent (CDC) due "
     "to low infectious dose (10–50 organisms aerosol) + lethality. Forms: ulceroglandular, "
     "oculoglandular, oropharyngeal, pneumonic (highest mortality). Cell envelope: LPS with "
     "atypical lipid A (low TLR4 stimulation — explains immune evasion). Intrinsic resistome: "
     "chromosomal β-lactamase → all penicillins/cephalosporins ineffective. Treatment: "
     "streptomycin or gentamicin IM/IV 10–14 days (gold standard); doxycycline or "
     "ciprofloxacin oral for milder. Post-exposure prophylaxis: doxycycline or ciprofloxacin "
     "14 days. Vaccine: live-attenuated (LVS, USAMRIID) — IND only. Concern: AG nephrotoxicity "
     "in elderly bioterrorism scenario; FQ resistance theoretical. Discovery: novel "
     "intracellular-penetrating drugs."),
    ("Yersinia pestis — plague / Tier 1 select agent",
     "Gram-negative coccobacillus, facultative intracellular. Niche: rodent flea (Xenopsylla "
     "cheopis) → mammal, sylvatic cycle. Forms: bubonic (flea bite, 70% historical mortality "
     "untreated), septicemic, pneumonic (highest concern — droplet transmission, near-100% "
     "fatal untreated). Tier 1 select agent. Cell envelope: type 3 secretion (Yop effectors), "
     "F1 capsular antigen, plasminogen activator. Intrinsic resistome: typically antibiotic-"
     "susceptible (β-lactamase rare); concern is engineered MDR strains. Treatment: "
     "streptomycin or gentamicin (gold), doxycycline, ciprofloxacin, levofloxacin. "
     "Pneumonic plague needs aggressive IV therapy + isolation. Post-exposure: "
     "ciprofloxacin or doxycycline 7 days. Vaccine: no licensed (formalin-killed F1 "
     "discontinued; F1/V subunit in development). Discovery: rapid-acting drug for "
     "post-exposure prophylaxis with shorter regimen."),
    ("Brucella spp. — undulant fever / occupational + zoonosis",
     "Small gram-negative coccobacillus, facultative intracellular. Species: B. melitensis "
     "(goats/sheep, most virulent), B. abortus (cattle), B. suis (swine), B. canis (dogs). "
     "Niche: animal reservoirs; transmission via raw dairy, infected aerosol (lab, abattoir), "
     "direct contact. Forms: acute (fever, sweats, arthralgia), chronic (osteoarticular, "
     "endocarditis, neuro-brucellosis). WHO Tier — not select but BSL-3, occupational "
     "concern. Cell envelope: LPS with atypical lipid A (low pyrogenicity). Intrinsic "
     "resistome: typically susceptible; cell wall + intracellular niche complicate clearance. "
     "Treatment: doxycycline + rifampin 6 weeks (mild); doxycycline + streptomycin or "
     "gentamicin × 2–3 weeks then doxy + rif × 6 weeks (severe). Endocarditis: TMP-SMX + "
     "rifampin + doxycycline 6+ months + valve surgery. Neuro-brucellosis: doxy + rif + "
     "ceftriaxone or TMP-SMX, 6+ months. Vaccine: animal only (RB51). Discovery: "
     "intracellular-penetrating drug shortening 6-week course."),
    ("Bartonella henselae and B. quintana — cat-scratch / trench fever / bacillary angiomatosis",
     "Small gram-negative bacilli, intracellular (RBC, endothelium). Niche: B. henselae — cat "
     "fleas, kittens, bite/scratch transmission; B. quintana — body lice (homeless, refugee). "
     "Forms: cat-scratch lymphadenopathy, trench fever, culture-negative endocarditis (key DDx "
     "for HACEK-negative endocarditis), bacillary angiomatosis (HIV/immunocompromised — "
     "vasoproliferative skin lesions), peliosis hepatis. Diagnosis: serology (IFA), PCR, "
     "Warthin-Starry stain. Cell envelope: standard gram-neg, no LPS endotoxin classic. "
     "Treatment: cat-scratch self-limited (azithromycin 5 days for severe lymphadenopathy); "
     "endocarditis = doxycycline + gentamicin × 2 weeks, then doxy + rifampin × 6 weeks "
     "(strong rifampin role for intracellular Bartonella); bacillary angiomatosis = "
     "erythromycin or doxycycline 3 months. Discovery: intracellular drug for shorter "
     "endocarditis course."),
    ("Listeria monocytogenes — pregnancy + neonatal + immunocompromised invasive infection",
     "Gram-positive rod, facultative intracellular, motile (tumbling at 20°C, not 37°C). "
     "Niche: soil/silage, contaminated food (deli meats, soft cheese, sprouts), invades GI "
     "epithelium, crosses placenta + BBB. Risk groups: pregnant (20× higher), neonates, "
     "elderly, immunocompromised (T-cell deficit). Forms: gastroenteritis, bacteremia, "
     "meningoencephalitis, neonatal sepsis (granulomatosis infantiseptica). Cell envelope: "
     "standard gram-positive. Intrinsic resistome: INTRINSICALLY R to cephalosporins (PBP3 "
     "low affinity — this is THE reason ampicillin is added to ceftriaxone empirically for "
     "meningitis in >50yo and immunocompromised). Treatment: ampicillin (high-dose, 2g IV q4h) "
     "+ gentamicin (synergy) for invasive disease; TMP-SMX backup for penicillin-allergic. "
     "Linezolid + meropenem alternatives. Pregnancy: ampicillin alone (avoid AG fetal "
     "ototoxicity). Discovery: faster intracellular drug shortening 21-day meningitis course."),
    ("Nocardia spp. — soil aerobic actinomycete, immunocompromised + post-transplant",
     "Aerobic gram-positive filamentous branching bacillus, partial-acid-fast (modified Kinyoun). "
     "Niche: soil ubiquitous; entry via inhalation (pulmonary nocardiosis) or skin trauma "
     "(cutaneous, mycetoma). Risk: T-cell immunocompromised — solid-organ transplant, HIV, "
     "chronic steroids, HSCT. Forms: pulmonary cavitary, disseminated (CNS abscesses 30–50% "
     "with brain involvement), cutaneous, mycetoma (chronic foot). Species: N. asteroides "
     "complex, N. brasiliensis (cutaneous), N. farcinica (drug-R). Cell envelope: mycolic acid "
     "thin, but partial-acid-fast distinct from Mycobacteria. Intrinsic resistome: variable by "
     "species; N. farcinica is intrinsically R to TMP-SMX + cephalosporin + AG → high mortality. "
     "Treatment: TMP-SMX (15 mg/kg/day TMP component) is gold; combination for severe disease — "
     "TMP-SMX + imipenem + amikacin × 6 weeks IV, then oral TMP-SMX × 6–12 months (CNS 12+). "
     "Linezolid covers all species (salvage). Surgical drainage for abscess. Discovery: "
     "shorter regimen with better CNS penetration; oral non-TMP-SMX salvage."),
]

count = 0
with OUT.open("a") as f:
    for name, response in ITEMS:
        ex = {
            "task": "pathogen_specific_dive",
            "split": "train",
            "prompt": f"{INSTR}\n\nPathogen: {name}",
            "response": response,
            "messages": [
                {"role": "user", "content": f"{INSTR}\n\nPathogen: {name}"},
                {"role": "assistant", "content": response},
            ],
        }
        f.write(json.dumps(ex) + "\n")
        count += 1

total = sum(1 for _ in OUT.open())
chars = sum(len(line) for line in OUT.open())
print(f"Wrote {count} pathogen_specific_dive examples (Sprint 13c)")
print(f"  total in named_drug_examples.jsonl: {total}")
print(f"  total chars: {chars:,}")
print(f"  approx tokens: {chars // 4:,}")
