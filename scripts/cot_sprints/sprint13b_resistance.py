"""Sprint 13b — 12 resistance_mechanism_explanation examples.
Non-overlapping with Sprint 5. Targets: MBLs, OXA carbapenemases, plasmid quinolone-R,
target-modification AMR landscape."""
import json
from pathlib import Path

OUT = Path("data/synthetic/named_drug_examples.jsonl")

INSTR = ("Instructions: Provide a deep mechanistic explanation of the named resistance "
         "determinant. Cover (1) molecular structure / catalytic mechanism, (2) genetic "
         "context (chromosomal vs plasmid, mobile element, regulation), (3) substrate range "
         "(which drug classes it defeats and which it spares), (4) phylogeographic origin "
         "and dissemination story, and (5) design strategies that escape it (BLI, structural "
         "modification, alternate target, bypass).")

ITEMS = [
    ("VIM and IMP metallo-β-lactamases (Class B Zn²⁺-cofactored MBLs)",
     "VIM (Verona integron-encoded MBL) and IMP (active on imipenem) are Ambler Class B "
     "metalloenzymes that hydrolyze ALL β-lactams except monobactams (aztreonam) — including "
     "carbapenems. Catalytic mechanism: two Zn²⁺ ions in the active site, bridged by "
     "water/hydroxide that nucleophilically attacks the β-lactam carbonyl. No covalent "
     "acyl-enzyme intermediate (unlike serine β-lactamases) — Zn²⁺ polarizes the carbonyl, "
     "hydroxide attacks, open-ring product diffuses out. This means traditional serine-BLI "
     "(clavulanate, tazobactam, avibactam) have ZERO activity. Genetic context: VIM and IMP "
     "are class 1 integron-borne, plasmid-carried, often co-located with aminoglycoside-"
     "modifying enzymes (aac(6')-Ib, ant(2'')-Ia) and qnrS — multi-drug-resistance cassette. "
     "Geographic origin: VIM first in Italy 1997, IMP first in Japan 1991; both now global. "
     "Substrate: all penicillins, all cephalosporins, all carbapenems; SPARES aztreonam. "
     "Therapeutic implications: (a) aztreonam + ceftazidime-avibactam combo — avibactam "
     "blocks the AmpC/ESBL that would otherwise hydrolyze aztreonam, and aztreonam itself "
     "escapes the MBL; (b) cefiderocol — siderophore-cephalosporin Trojan horse via TonB-"
     "dependent uptake bypasses porin restriction; (c) MBL-specific inhibitors in development: "
     "taniborbactam (boronate Zn²⁺-binder), xeruborbactam, ANT2681 (thiol-zinc-chelator). "
     "Detection: combination disk test with EDTA (chelates Zn²⁺), or molecular PCR for "
     "blaVIM/blaIMP. Surveillance: VIM endemic in Greece, Italy, Japan, China; IMP particularly "
     "in Japan/Australia/Taiwan. NDM far more common globally."),
    ("OXA-23, OXA-24, OXA-58 carbapenem-hydrolyzing class D β-lactamases in Acinetobacter",
     "OXA-23, OXA-24/40, and OXA-58 are Ambler Class D serine carbapenemases — narrow-"
     "spectrum but devastating in A. baumannii context. Catalytic mechanism: Ser70-Lys73 "
     "general base, carbamylated lysine (CO₂-bound) acts as proton shuttle. Carbapenem "
     "hydrolysis is SLOW (kcat 0.1–10 /sec, vs KPC 100+) but sufficient because A. baumannii "
     "couples OXA expression with porin loss (OmpA, CarO downregulation) and AdeABC efflux "
     "upregulation — synergistic resistance. Genetic context: OXA-23 typically on AbaR "
     "resistance islands, plasmid-mobilizable with insertion sequences (ISAba1, ISAba125) "
     "acting as outward-facing promoters. ISAba1 upstream of blaOXA-23 increases expression "
     "100-fold and is the major cause of high-level CRAB. Phylogeography: OXA-23 global "
     "pandemic, OXA-24/40 Iberian/Latin American clones, OXA-58 Mediterranean/European. "
     "Substrate: all β-lactams to varying degrees; cephalosporins poorly hydrolyzed (broad-"
     "spectrum cephalosporin susceptibility may be retained — but only if ADC/AmpC is "
     "uninduced, rare in clinical isolates). Therapeutic counter: (1) sulbactam-durlobactam "
     "(durlobactam is the first DBO with reliable OXA-23/24/58 coverage), (2) cefiderocol, "
     "(3) high-dose ampicillin-sulbactam (sulbactam direct PBP1/3 hit), (4) minocycline / "
     "tigecycline. Eravacycline also covers most CRAB. IDSA 2024 update: sulbactam-"
     "durlobactam preferred."),
    ("qnr plasmid-mediated quinolone resistance proteins (qnrA/B/S/D/VC)",
     "qnr proteins are pentapeptide-repeat-containing plasmid-borne fluoroquinolone resistance "
     "factors that bind to DNA gyrase and topoisomerase IV, sterically blocking quinolone "
     "access without preventing enzyme function. Discovered 1998 (qnrA on Klebsiella plasmid). "
     "Mechanism is REVERSIBLE PROTECTION — they cannot raise MIC above breakpoint alone "
     "(typically 4–8× shift) but they (a) elevate baseline tolerance enough that selective "
     "pressure favors emergence of chromosomal gyrA/parC mutants, and (b) co-locate on plasmids "
     "with ESBLs (CTX-M-15) and aac(6')-Ib-cr — three-hit MDR cassette. Five families: qnrA "
     "(chromosomal in Shewanella, ancestor), qnrB (Citrobacter origin), qnrS, qnrD, qnrVC. "
     "Substrate: all FQs (cipro, levo, moxi, gemi). Detection: PCR — phenotypic screening "
     "misses them (raise MIC <breakpoint). Clinical impact: qnr+ Enterobacterales have higher "
     "rates of clinical FQ failure even at MIC ≤1, because in-vivo selection of chromosomal "
     "mutants is accelerated. Therapeutic counter: avoid FQ when qnr present (infrequently "
     "tested) or when ESBL co-detected (correlated). NBTI-class compounds (gepotidacin, "
     "zoliflodacin) may evade qnr because they target a distinct gyrase site (GyrA α-3-helix "
     "— different from the QRDR pocket protected by qnr); preliminary EAGLE-1 data support "
     "this. Stewardship: avoid FQ for ESBL infections (high qnr co-carriage)."),
    ("dfrA dihydrofolate reductase variants (TMP resistance)",
     "Trimethoprim binds bacterial DHFR with 60,000-fold selectivity over human DHFR. "
     "Resistance mechanism: dfrA gene cassettes (28+ variants: dfrA1, dfrA5, dfrA12, dfrA17, "
     "etc.) encode DHFR enzymes with active-site substitutions (Phe98Tyr, Ile100Leu, etc.) "
     "that reduce TMP binding ~10⁴-fold while preserving folate reduction. Genetic context: "
     "Class 1 integron-borne, plasmid-mediated, found in nearly all CTX-M-15 plasmids of "
     "ST131 E. coli — co-amplification phenomenon. Phylogeographic origin: dfrA1 from Tn7-like "
     "elements 1980s; dfrA17 explosion in mid-2000s with global ST131 spread. Substrate: "
     "trimethoprim and analogs (iclaprim, brodimoprim) at varying degrees — iclaprim was "
     "designed with extended ring system to defeat dfrA but trial failed for unrelated "
     "reasons. Therapeutic counter: (1) sulfonamide co-targeting via TMP-SMX restoration "
     "(sulI/sulII mediates SMX-R, but combined effect sometimes saved by remaining sulfa "
     "activity); (2) novel DHFR inhibitors with deeper binding pocket engagement (compounds "
     "like UCP1175); (3) avoid TMP-SMX if local resistance >20% in cystitis isolates "
     "(CDC threshold) — switch to nitrofurantoin or fosfomycin. Detection: dfrA+ → automated "
     "MIC platforms report TMP-SMX R, highly correlated."),
    ("blaZ Staphylococcus aureus β-lactamase (the original penicillin-resistance gene)",
     "blaZ is the chromosomal/plasmid-encoded class A serine β-lactamase that drove the "
     "1940s-1950s collapse of penicillin G in S. aureus — within 5 years of mass deployment, "
     "70% of hospital S. aureus produced blaZ. Catalytic mechanism: Ser70 nucleophilic attack "
     "on β-lactam carbonyl → covalent acyl-enzyme → hydrolysis. Substrate: penicillins "
     "(penicillin G, ampicillin, amoxicillin), poorly hydrolyzed cephalosporins. Inducible: "
     "blaR1 + blaI two-component system senses β-lactam, derepresses transcription. "
     "Phylogeography: ubiquitous in MSSA today (~90% of clinical S. aureus). Therapeutic "
     "response — historic: methicillin (1959) — bulky 2,6-dimethoxybenzyl side chain "
     "prevents hydrolysis but doesn't escape PBP2a (mecA emergence 1960s); nafcillin/oxacillin "
     "remain MSSA workhorse drugs because steric bulk excludes blaZ. Modern: amoxicillin-"
     "clavulanate (clav inhibits blaZ irreversibly), cefazolin (reasonable hydrolysis "
     "resistance + PBP binding). Cefazolin inoculum effect is THE concerning blaZ phenomenon: "
     "at high inoculum (10⁸ CFU/mL — endocarditis), blaZ hydrolyzes cefazolin enough that "
     "clinical failure occurs; nafcillin lacks this. So: cefazolin OK for MSSA bacteremia/"
     "skin, nafcillin preferred for endocarditis. Detection: cefoxitin disk + nitrocefin "
     "chromogenic assay. Co-resistance: blaZ alone does not predict mecA, but most MRSA "
     "still carry blaZ."),
    ("fosA and fosB glutathione S-transferases (fosfomycin inactivation)",
     "Fosfomycin is a small (138 Da) phosphonate that mimics PEP and irreversibly inhibits "
     "MurA. Resistance routes: (1) target mutation (uhpT/glpT transporter loss — drug entry "
     "block); (2) enzymatic inactivation by fosA (Mn²⁺-glutathione S-transferase, gram-negs) "
     "or fosB (Mg²⁺-cysteine-thiol transferase, gram-pos S. aureus, B. cereus). fosA opens "
     "the fosfomycin epoxide ring by GSH thiol attack — generates inactive GSH-fosfomycin "
     "adduct. Catalytic efficiency 10⁴ /sec at saturating GSH. Genetic context: fosA is "
     "intrinsic-chromosomal in many gram-negs (Klebsiella, Serratia, Pseudomonas, Enterobacter) "
     "— this is why oral fosfomycin works for E. coli cystitis but is unreliable for "
     "Klebsiella cystitis (intrinsic fosA). Plasmid variants fosA3, fosA5, fosA6 spread "
     "horizontally and are now in CTX-M-positive E. coli. Therapeutic counter: (1) avoid "
     "fosfomycin in Klebsiella, Serratia (intrinsic fosA); (2) avoid in S. aureus (intrinsic "
     "fosB); (3) IV fosfomycin combination with carbapenems for systemic infection in "
     "fosfomycin-susceptible strains; (4) MurA-bypass strategies under research. Detection: "
     "automated MIC platforms unreliable for fosfomycin — agar dilution is gold standard; "
     "phenotype + species ID predicts fosA presence. fosA is the reason CDC limits oral "
     "fosfomycin recommendation to E. coli cystitis only."),
    ("vanB and vanD vancomycin-resistance operons (D-Ala-D-Lac and D-Ala-D-Ser variants)",
     "vanA is the headline vanco-R operon (D-Ala-D-Lac substitution in lipid II cap, 1000-"
     "fold MIC shift). vanB = same D-Ala-D-Lac chemistry but typically inducible (slower "
     "phenotype, lower-level: MIC 4–32 vs vanA 64–1024) and on Tn1547 conjugative transposon "
     "— common in E. faecalis (less so E. faecium). VanB does NOT confer teicoplanin-R "
     "(vanA does) — teicoplanin retains activity in vanB-VRE. vanD = also D-Ala-D-Lac but "
     "constitutively expressed and chromosomally integrated (E. faecium subset, rare clinical "
     "isolates). vanC, vanE, vanG = D-Ala-D-Ser (lower-affinity substitution, MIC 8–32, "
     "intrinsic in E. gallinarum and E. casseliflavus — non-infectious). vanL, vanM, vanN = "
     "newer variants in clinical reports. Therapeutic implications: VRE infection — first "
     "identify vanA vs vanB (PCR or phenotype with teicoplanin susceptibility). vanB → "
     "teicoplanin OK + linezolid + daptomycin. vanA → linezolid (50S, no peptidoglycan target "
     "overlap), daptomycin (lipopeptide, membrane), tigecycline, oritavancin (lipoglycopeptide, "
     "partially overcomes vanA via secondary membrane interaction). Quinupristin-dalfopristin "
     "(Synercid) for E. faecium vanA but inactive against E. faecalis. Phylogeography: vanA "
     "in E. faecium global; vanB more US/Europe enterococcal. Avoparcin agricultural driver "
     "(banned 1997 EU) initiated the spread."),
    ("sulI integron-borne sulfonamide resistance (sulI, sulII, sulIII)",
     "Sulfonamides inhibit dihydropteroate synthase (DHPS, folP) by competing with PABA for "
     "the substrate site. Resistance: sulI, sulII, sulIII encode alternate DHPS enzymes with "
     "reduced sulfonamide affinity (200-fold) while retaining PABA binding. Genetic context: "
     "sulI is the QUINTESSENTIAL class 1 integron 3' conserved-segment marker — it is the "
     "cassette that defines the integron's identity, immediately downstream of qacEΔ1. ANY "
     "class 1 integron carries sulI by structural definition. sulII is on plasmids without "
     "integron, sulIII rare. Phylogeographic origin: 1960s sulfa introduction; sulI now in "
     "80%+ of clinical Enterobacterales, sulII similar. Substrate: all sulfa drugs "
     "(sulfamethoxazole, sulfadiazine, sulfisoxazole, sulfacetamide). Therapeutic implication: "
     "TMP-SMX double-attack on folate pathway (DHPS + DHFR) preserves clinical activity even "
     "when sulI present (TMP component alone has antibacterial effect); but high-level "
     "sulfonamide-R + dfrA = TMP-SMX failure. CDC threshold: avoid TMP-SMX for empiric UTI "
     "when local E. coli resistance >20%. Counter: sulfa-DHPS inhibitor with deeper-binding "
     "scaffold (under research, limited progress). Co-resistance: sulI is a marker of class 1 "
     "integron + therefore co-carriage of aacA, aadA, blaPSE, dfrA, blaCTX-M cassettes — "
     "finding sulI predicts MDR phenotype."),
    ("pmrA/pmrB and mgrB lipid-A modification (chromosomal polymyxin/colistin resistance)",
     "Colistin/polymyxin B bind lipid-A phosphates electrostatically (positive DAB residues "
     "to negative phosphates). Chromosomal resistance via PhoP/PhoQ → PmrA/PmrB two-component "
     "cascade activates pbgP/arnBCADTEF/ugd operons that synthesize and add 4-amino-arabinose "
     "(L-Ara4N) and phosphoethanolamine (pEtN) to lipid-A phosphates — neutralizing the "
     "negative charge and preventing polymyxin binding. MgrB is a small inner-membrane "
     "regulator that NEGATIVELY controls PhoQ; loss-of-function mutations in mgrB unleash "
     "PhoP/PhoQ → PmrA/PmrB → constitutive lipid-A modification → high-level colistin-R. "
     "mgrB inactivation (insertion-sequence-mediated, frameshifts, deletions) is the "
     "dominant route in K. pneumoniae colistin-R. Plasmid-mediated counterpart is mcr-1 "
     "through mcr-10 — phosphoethanolamine transferases that horizontally spread between "
     "species, first reported 2015 (Liu et al., Lancet Infect Dis, China). Phylogeography: "
     "chromosomal PmrA/PmrB widespread; mcr-1 global within 18 months of report (livestock-"
     "driven). Therapeutic counter: (1) avoid colistin monotherapy when PmrAB or mcr "
     "suspected; (2) novel polymyxin analogs (SPR206, NAB7061) with engineered lipid-A "
     "binding registers; (3) MurA + LpxC inhibitors target outer membrane synthesis from "
     "different angle. Detection: colistin BMD MIC, no reliable disk diffusion."),
    ("gyrA/parC QRDR mutations (chromosomal fluoroquinolone-resistance)",
     "Fluoroquinolones target DNA gyrase (gyrA + gyrB) and topoisomerase IV (parC + parE). "
     "GyrA α-helix and ParC analog form the quinolone-resistance-determining region (QRDR). "
     "Single-step mutations at GyrA Ser83 (→ Leu, Ile, Phe) and Asp87 (→ Asn, Tyr, Gly) raise "
     "MIC 8–16-fold. Second-step ParC Ser80 (→ Leu, Ile) or Glu84 push to high-level R. The "
     "quinolone binding pocket is at the DNA-cleavage site — mutations alter drug-binding "
     "contact while preserving catalytic function (selection-tolerated). Phylogeography: "
     "ubiquitous in MDR E. coli ST131 (gyrA S83L + D87N + parC S80I triad), Salmonella Typhi "
     "(S83F/Y), N. gonorrhoeae (S91F + D95N + S87R + S88P — ceftriaxone-only era), "
     "M. tuberculosis (rapid escape on FQ monotherapy 10⁻⁸). Substrate: all FQs, with "
     "gradient — moxifloxacin retains some activity at single S83L due to higher gyrase "
     "affinity, but loses to triple mutants. Therapeutic counter: (1) NBTI gepotidacin/"
     "zoliflodacin — bind a distinct gyrase pocket (GyrA α-3-helix), active vs S83L/D87N; "
     "(2) avoid FQ for ESBL-positive (qnr correlation, see qnr entry); (3) AGS-2024 update "
     "lowers FQ in cystitis tier when local R >10%. Detection: gyrA/parC PCR for "
     "Salmonella/Mtb is standard."),
    ("23S rRNA central-loop mutations (linezolid + tedizolid + chloramphenicol R)",
     "Linezolid (oxazolidinone) binds the 23S rRNA central loop in domain V at the A-site, "
     "blocking the 70S initiation complex from binding the first aminoacyl-tRNA. Resistance: "
     "G2576U is the dominant clinical mutation (single nucleotide change), conferring "
     "4–32-fold MIC shift. Because bacterial ribosome operons are present in 4–7 copies, "
     "heterozygous mutants emerge first (1–2 copies G2576U), then under linezolid selection "
     "convert all copies via gene conversion → high-level R. cfr ribosomal RNA "
     "methyltransferase (chloramphenicol-florfenicol resistance) methylates A2503 (also "
     "PTC region) — confers PhLOPSA cross-resistance (Phenicols, Lincosamides, Oxazolidinones, "
     "Pleuromutilins, Streptogramin A). Genetic context: cfr is plasmid-borne, ag-livestock-"
     "driven; G2576U is chromosomal de novo. Substrate: linezolid, tedizolid, chloramphenicol, "
     "clindamycin, retapamulin/lefamulin (cfr only), streptogramin A (cfr only). Tedizolid "
     "retains some activity vs G2576U single-copy mutants because of higher binding affinity. "
     "Therapeutic counter: (1) oxazolidinone analogs with extended ring engagement — "
     "radezolid, contezolid; (2) lefamulin (pleuromutilin, distinct PTC binding mode, "
     "partially uncorrelated with G2576U); (3) limit linezolid duration <14d to minimize "
     "selection. Detection: 23S PCR for G2576U, cfr PCR, MIC. cfr in livestock makes "
     "ag-driven horizontal spread the major surveillance concern. optrA + poxtA are newer "
     "ABCF ribosomal-protection equivalents — emerging in VRE."),
    ("KatG INH-resistance landscape — beyond Ser315Thr",
     "Isoniazid (INH) is a prodrug activated by mycobacterial catalase-peroxidase KatG to "
     "INH-NAD adduct — the active inhibitor of InhA (enoyl-ACP reductase, mycolic acid "
     "synthesis). Resistance routes: (1) katG mutations — Ser315Thr is the dominant clinical "
     "variant (>70% of INH-R Mtb), retaining catalase activity (preserves H₂O₂ defense, "
     "fitness preserved) while losing INH activation 200-fold. Other katG variants: "
     "Ser315Asn, Trp321Stop, total deletion (high-level R, often co-clusters with MDR). "
     "(2) inhA promoter (–15C→T, –17G→T) up-regulation — overexpresses target, titrating "
     "drug — confers low-level INH-R but cross-resistance with ethionamide (also targets "
     "InhA). (3) ndh (NADH dehydrogenase) mutations — alter NADH/NAD ratio, indirectly "
     "perturb INH-NAD adduct. (4) ahpC promoter mutations — co-occur with katG loss, "
     "compensate H₂O₂ defense. Phylogeography: katG-S315T globally dominant. Substrate "
     "specificity: INH only — no cross-resistance with rifampin, pyrazinamide, ethambutol, "
     "fluoroquinolones; partial cross with ethionamide (inhA pathway). Therapeutic counter: "
     "(1) WHO 2024 — high-dose INH (15 mg/kg) for inhA-promoter low-level R only; "
     "(2) preserve INH in MDR-TB regimens when only katG-WT/inhA-mutant; (3) direct InhA "
     "inhibitors that bypass KatG activation (in clinical research — pretomanid acts via "
     "different mechanism but escape route). Detection: GeneXpert MTB/RIF for rpoB only; "
     "GenoType MTBDRplus catches katG and inhA. Hain InnoLiPA covers same loci."),
]

count = 0
with OUT.open("a") as f:
    for combo, response in ITEMS:
        ex = {
            "task": "resistance_mechanism_explanation",
            "split": "train",
            "prompt": f"{INSTR}\n\nResistance determinant: {combo}",
            "response": response,
            "messages": [
                {"role": "user", "content": f"{INSTR}\n\nResistance determinant: {combo}"},
                {"role": "assistant", "content": response},
            ],
        }
        f.write(json.dumps(ex) + "\n")
        count += 1

total = sum(1 for _ in OUT.open())
chars = sum(len(line) for line in OUT.open())
print(f"Wrote {count} resistance_mechanism_explanation examples (Sprint 13b)")
print(f"  total in named_drug_examples.jsonl: {total}")
print(f"  total chars: {chars:,}")
print(f"  approx tokens: {chars // 4:,}")
