---
slug: domains/amr
loaded_when: "any of: AMR, MRSA, MRD, ESBL, KPC, NDM, VRE, MDR, antibiotic, antibacterial, vancomycin, beta-lactamase, gyrA, methicillin, linezolid, polymyxin, carbapenem, fluoroquinolone, oxazolidinone, ribosome, peptidoglycan"
---

# Domain: Antimicrobial Resistance (AMR)

The domain Lysos is purpose-built for. Loaded when the user's input
mentions any AMR keyword.

## The 8 priority pathogens (WHO + CDC overlap)

| Code | Pathogen | Critical resistance | Typical first-line |
|---|---|---|---|
| MRSA | *Staphylococcus aureus* (MRSA) | mecA → PBP2a | vancomycin, ceftaroline, linezolid, daptomycin |
| Mtb | *Mycobacterium tuberculosis* (MDR/XDR) | katG, rpoB, gyrA mutations | RIF/INH/EMB/PZA → bedaquiline + pretomanid + linezolid (BPaL) |
| EColi-CRE | *Escherichia coli* (carbapenem-resistant) | KPC, NDM, OXA-48 carbapenemases | ceftazidime/avibactam, meropenem/vaborbactam, cefiderocol |
| KpneuCRE | *Klebsiella pneumoniae* (carbapenem-resistant) | KPC, NDM, OXA + porin loss (OmpK) | ceftazidime/avibactam, meropenem/vaborbactam |
| Abaum | *Acinetobacter baumannii* (MDR/XDR) | OXA carbapenemases, PBP3 mutations, AdeABC efflux | sulbactam/durlobactam, cefiderocol, polymyxin B |
| Paer | *Pseudomonas aeruginosa* (MDR) | OprD loss, AmpC, MexAB efflux, gyrA | ceftolozane/tazobactam, ceftazidime/avibactam, cefiderocol |
| VRE | vanA/B *Enterococcus faecium* | D-Ala-D-Lac substitution | linezolid, daptomycin, oritavancin, tigecycline |
| NGono | *N. gonorrhoeae* (XDR) | gyrA, parC, penA mosaic | ceftriaxone (last-line); zoliflodacin (pipeline) |

## Key resistance enzymes (named, by class)

**β-lactamases**: TEM, SHV, CTX-M (ESBLs); KPC, NDM, VIM, IMP (CR);
OXA-23, OXA-48 (carbapenem in *Acinetobacter*/*Klebsiella*); AmpC.

**Aminoglycoside-modifying enzymes**: aac(6')-Ib, aph(3')-IIa, ant(2'')-Ia.

**Methylases (rRNA)**: erm A2058 (macrolides MLSb), cfr A2503
(linezolid + chloramphenicol + others), 16S rRNA armA/rmtB
(aminoglycoside high-level R).

**Efflux pumps**: AcrAB-TolC (E. coli), MexAB-OprM (Pseudomonas),
NorA (S. aureus), Tet(A-K) (tetracycline).

**Target modifications**: gyrA S83L / parC S80I (FQs); rpoB (rifampin);
katG / inhA (isoniazid); pbp2a (mecA); D-Ala-D-Lac (vanA/B).

## Standard target enzymes (SBM ground truth)

When the user names a pathogen, default targets:

- MRSA → **PBP2a** (PDB: 1VQQ, 4DKI, 5JZM)
- Mtb → **InhA** (1ZID), **DprE1** (4FDO), **MmpL3** (6AJG)
- E. coli / Klebsiella → **PBP3 / FtsI** (4BJP), **AcrB** (1IWG)
- Pseudomonas → **PBP3** (3PBR), **DNA gyrase** (4CKL)
- Acinetobacter → **PBP1a / PBP3** (4OON), **LpsA**
- VRE → **D-Ala-D-Ala ligase** (1IOV), **MurF** (2AM1)
- N. gonorrhoeae → **PBP2 (penA)** (3EQU), **MtrCDE efflux**

## Default scoring weights for AMR

The 12-component reward stack (with rationale per axis):

| Component | Weight | Why for AMR |
|---|---|---|
| validity | 0.05 | Hard floor — RDKit must parse |
| structural_alerts | 0.05 | PAINS/Brenk/Lipinski — drug-likeness floor |
| **predicted_mic** | **0.20** | The key axis; we want low MIC |
| drug_likeness_qed | 0.10 | QED ≥ 0.55 typical for marketed antibiotics |
| synthesizability | 0.10 | SAscore < 4.0 makes it scalable |
| hemolysis_safety | 0.10 | RBC lysis is the #1 AMP failure mode |
| novelty | 0.08 | Tanimoto novel vs 30K known |
| embedding_novelty | 0.07 | Semantic novelty (Gemini Embedding 2) |
| **boltz2_pose_conf** | **0.10** | Real binding signal (ipTM/pTM) |
| spectrum_breadth | 0.05 | Active across ≥3 priority pathogens |
| resistance_robustness | 0.05 | Evades ≥2 known mechanisms |
| pareto_entry | 0.05 | Bonus for novel Pareto front entries |

## Editing heuristics for AMR

- **MRSA β-lactams**: ceftaroline-style C3 substituent for PBP2a allosteric.
- **CRE β-lactams**: avibactam-pair (siderophore catechol C3 = cefiderocol).
- **Mtb**: small, lipophilic (cell-wall penetration); avoid charged groups.
- **Pseudomonas**: charged C3 (cefepime-style) for OprD-bypass entry.
- **AMPs**: cationic + amphipathic for membrane disruption; lower
  hemolysis = D-amino acids, cyclization, head-group masking.
