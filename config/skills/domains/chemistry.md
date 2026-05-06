---
slug: domains/chemistry
loaded_when: "any of: SMILES, RDKit, scaffold, fragment, bioisostere, stereochemistry, chirality, ring, aromatic, halide, sulfonamide, beta-lactam, peptide, AMP, prodrug, P450, log P, TPSA, QED, SA score, ChEMBL, PDB"
---

# Domain: Drug-design chemistry

Loaded when chemistry-specific signals appear in input. Pairs with the
AMR domain when both apply.

## SMILES conventions

- Always **canonicalize** before scoring: `Chem.MolToSmiles(mol)`.
- Always **assign stereochemistry** when present: `Chem.AssignStereochemistry`.
- Stereochemistry hints in SMILES: `@`, `@@` (chiral), `/`, `\` (double-bond).
- `[C@@H]` = R-config when looking at first three substituents.
- Rings are SSSR by default; report **AromaticAtomCount** + **RingCount**.

## Scoring conventions

- **MIC** is reported as **log10(µg/mL)**. log10 < 0 = MIC < 1 µg/mL = active.
  - "Sub-µM" ≈ log10 ≤ 0 ≈ excellent.
  - log10 ≤ 0.7 ≈ active threshold for inclusion in spectrum count.
- **QED** ∈ [0, 1]. ≥ 0.55 = drug-like.
- **SAscore** ∈ [1, 10]. ≤ 4.0 = synthesizable in <10 steps.
- **logP** is calculated via Crippen MolLogP. logP > 5 violates Lipinski.
- **TPSA** > 140 Å² → poor membrane permeability.
- **Lipinski**: MW < 500, logP < 5, HBD ≤ 5, HBA ≤ 10, rotatable < 10.

## Bioisostere library (the canonical replacements)

### Hydrogen-bond donors / acceptors

- **-OH ↔ -F** (similar size, both can form weak HB; F more
  metabolically stable)
- **-OH ↔ tetrazole** (carboxylic-acid bioisostere: both deprotonated
  at physiological pH)
- **-NH-CO- ↔ -CH=CH-** (peptide-bond → trans-alkene; protease-stable)

### Aromatic ring swaps

- **phenyl ↔ pyridine** (lowers logP, adds HBA)
- **phenyl ↔ thiophene** (lowers logP slightly, similar shape)
- **phenyl ↔ thiazole** (HBA + lowers logP + swap of pi)
- **phenyl ↔ furan** (lower logP but metabolic risk)

### Halide swaps

- **Cl ↔ F** (smaller, lower logP, similar electronic effect)
- **Cl ↔ CF₃** (more lipophilic, more steric, locks rotamer)
- **Br ↔ I** (rarely useful — both leave; don't use I in candidates).

### Carbonyl / amide

- **amide ↔ sulfonamide** (different geometry, hydrolytic stability)
- **amide ↔ ester** (hydrolytic loss of stability — usually a downgrade)
- **amide ↔ N-methylated amide** (locks rotamer, sometimes lifts MIC)

## Reaction SMARTS (used by `transform_structure` tool)

Already implemented (see `workspace/tools/generative/transform_structure.py`):

| op | SMARTS | When to use |
|---|---|---|
| add_hydroxyl | `[c:1][H:2]>>[c:1][OH]` | Lower logP, add HBD |
| add_fluorine | `[c:1][H:2]>>[c:1]F` | Metabolic stability, mild lipophilicity |
| add_methyl | `[c:1][H:2]>>[c:1]C` | Steric block, lipophilicity++ |
| add_amine | `[c:1][H:2]>>[c:1]N` | HBD + HBA, basicity |
| swap_chloro_to_fluoro | `[Cl]>>[F]` | Smaller halogen |
| swap_fluoro_to_chloro | `[F]>>[Cl]` | Larger halogen |
| add_sulfonamide | `[NH2:1]>>[N:1]S(=O)(=O)C` | PABA-mimic warhead |
| add_carboxyl | `[c:1][H:2]>>[c:1]C(=O)O` | Lower logP, anionic |
| ring_close | `[c:1][CX4:2][CX4:3][c:4]>>[c:1]1[CX4:2][CX4:3][c:4]1` | Lock geometry, reduce rotors |
| remove_methyl | `[c:1]C>>[c:1][H]` | Open up steric room |

## Pharmacophores by drug class

Quick reference for `inferred_class` matching:

| Class | Required substructures | Common scaffolds |
|---|---|---|
| β-lactam (penicillins) | β-lactam ring fused to thiazolidine | penam |
| β-lactam (cephalosporins) | β-lactam fused to dihydrothiazine | cephem |
| β-lactam (carbapenems) | β-lactam fused to pyrroline | carbapen-2-em |
| β-lactam (monobactams) | β-lactam, no fusion | aztreonam-like |
| fluoroquinolone | quinolone core + C7 piperazine + C6-F | levofloxacin scaffold |
| oxazolidinone | 1,3-oxazolidin-2-one + C5-acetamide | linezolid scaffold |
| macrolide | 12-/14-/15-membered macrocycle | erythromycin scaffold |
| tetracycline | linearly fused 4-ring system (D-C-B-A) | tetracene scaffold |
| glycopeptide | crosslinked heptapeptide | vancomycin scaffold |
| aminoglycoside | aminocyclitol + glycosidic linkages | streptamine, 2-DOS |
| polymyxin | cyclic lipopeptide + Dab residues | polymyxin B/E |
| sulfonamide | -SO₂NH₂ on aniline | sulfamethoxazole |

## Common pitfalls (avoid)

- **Halide on sp3 nitrogen** → unstable; usually a SMILES error.
- **Open valence** in proposed product → RDKit will reject; sanitize before reporting.
- **Hyper-substituted aromatic** (e.g., 5+ substituents on benzene) →
  almost always an enumeration artifact; flag and drop.
- **PAINS hits** (rhodanines, alpha,beta-unsat carbonyls in non-cephalosporin
  context, catechols outside cefiderocol motif) → mark as alert.
