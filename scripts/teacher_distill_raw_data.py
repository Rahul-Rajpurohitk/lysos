"""Raw-data + core-functionality + audited-numbers teacher distillation.

The model needs to KNOW the actual data sources, the actual numbers we have,
and the core chemistry/biology fundamentals — not just abstract concepts.

Categories (each 500 traces):
  A. source_chembl              ChEMBL: schema, coverage, biases, our subset
  B. source_drugbank             DrugBank Open: schema, what we use
  C. source_npatlas              NPAtlas: natural products, producer organism
  D. source_dbaasp_dramp         AMP databases: peptide one-letter sequences
  E. source_drugcentral          DrugCentral: approved drugs + INN/CAS
  F. source_card_megares         CARD + MEGARES: resistance gene catalogs
  G. source_pdb                  RCSB PDB: structural biology
  H. source_zinc_pubchem         ZINC + PubChem: virtual libraries
  I. source_tdc                  Therapeutics Data Commons
  J. source_coadd                CO-ADD: open antimicrobial screens
  K. core_sar_concepts            SAR fundamentals
  L. core_mic_methodology         How MIC is measured (broth, agar, EUCAST/CLSI)
  M. core_resistance_biology      Gene families, plasmids, transposons
  N. core_pkpd                    PK/PD math + targets
  O. core_admet                   Lipinski, Veber, hERG, CYP
  P. core_3d_structure            Pose, RMSD, induced fit, allostery
  Q. core_synthesis               Retrosynthesis, SA, route quality
  R. core_regulatory              FDA, QIDP, breakpoints, EUCAST/CLSI
  S. audited_numbers              Real counts from our dataset
  T. data_provenance              Where each row came from + verification

Run:
  /tmp/lysos_venv/bin/python scripts/teacher_distill_raw_data.py --n_per_category 400

Output:
  data/synthetic/agentic_teacher_distill_raw_data.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic" / "agentic_teacher_distill_raw_data.jsonl"

PATHOGENS = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE", "Abaum", "Paer", "VRE", "NGono"]

SYS = (
    "You are a Lysos data + chemistry domain explainer. Your job is to teach "
    "a developer or sub-agent the raw data sources, the core chemistry / "
    "biology / pharmacology concepts, and the actual numbers in our dataset. "
    "Use specific counts, specific gene names, specific PDB ids, specific "
    "concentration ranges. Concrete > abstract."
)


# ============================================================================
# A. ChEMBL
# ============================================================================
def trace_source_chembl(rng: random.Random) -> dict:
    user = "What is ChEMBL? What's the schema? How does Lysos use it?"
    asst = (
        "[ChEMBL Source]:\n\n"
        "ChEMBL is the EMBL-EBI chemical bioactivity database. Free, manually curated, "
        "covers ~2.4M compounds with ~20M measured bioactivities. The standard reference "
        "for medicinal chemistry SAR data.\n\n"
        "Key tables for Lysos:\n"
        "  activities             — measured bioactivity values\n"
        "    fields: standard_type, standard_value, standard_units, target_chembl_id,\n"
        "             assay_chembl_id, molecule_chembl_id\n"
        "    standard_types we use: MIC, MIC50, MIC90, IC50, EC50, Ki, Kd, Potency\n"
        "  molecule_dictionary    — compound metadata (SMILES, InChI, ROMol)\n"
        "  target_dictionary      — biological targets (organism, target_type)\n"
        "  assays                 — assay metadata (description, organism, type)\n\n"
        "How Lysos pulls ChEMBL:\n"
        "  loader: src/data/chembl.py\n"
        "  filter: 8 priority pathogens (MRSA, Mtb, EColi-CRE, KpneuCRE, Abaum, "
        "Paer, VRE, NGono)\n"
        "  std_types: 8 (MIC, MIC50, MIC90, IC50, EC50, Ki, Kd, Potency)\n"
        "  unit normalization: log10(MIC_nM) or log10(MIC_uM)\n"
        "  output: ~21,283 records on disk (heavy run, after std_types widening)\n\n"
        "Per-pathogen ChEMBL distribution (from our cleanup):\n"
        "  Mtb:        4,236   EColi-CRE:  3,955   MRSA:       3,091\n"
        "  Paer:       2,807   KpneuCRE:   2,559   VRE:        2,426\n"
        "  Abaum:      1,618   NGono:        591\n\n"
        "Biases / limitations:\n"
        "  - Submission bias: more data on commonly-studied targets (PBP > MexAB)\n"
        "  - Pathogen bias: Mtb dominant due to TB-Alliance + Foundation grants\n"
        "  - Time bias: pre-2010 measurements use older standardization protocols\n"
        "  - Stereochemistry: ~20% of compounds have undefined stereo — handled in cleanup\n"
        "  - Tautomer state: arbitrary at submission time — canonicalized in cleanup\n\n"
        "Cleanup transformations applied (per scripts/clean_chemistry_corpus.py):\n"
        "  1. Detect peptide-as-SMILES (regex match against AA one-letter code)\n"
        "  2. Convert recovered peptides to SMILES via Chem.MolFromSequence\n"
        "  3. RDKit parse + sanitize\n"
        "  4. MolStandardize tautomer canonicalize\n"
        "  5. Stereo state classification (achiral / defined / partial / undefined / peptide / racemic)\n"
        "  6. Re-canonicalize via Chem.MolToSmiles(canonical=True, isomericSmiles=True)\n"
        "  7. Compute InChI key for cross-source dedup\n\n"
        "Result: 13,809 cleaned ChEMBL rows in known-antibiotics-canonical.parquet."
    )
    return {"task": "teacher_raw_chembl",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# B. DrugBank Open
# ============================================================================
def trace_source_drugbank(rng: random.Random) -> dict:
    user = "What is DrugBank Open? What does Lysos pull from it?"
    asst = (
        "[DrugBank Open Source]:\n\n"
        "DrugBank Open is the open-access subset of the DrugBank pharmaceutical "
        "database. ~14K approved + investigational + withdrawn drug entries with "
        "drug names, structures, indications, mechanisms, pharmacology, and "
        "interactions. Distributed as a single ZIP.\n\n"
        "Key fields for Lysos:\n"
        "  drugbank_id        — primary identifier (e.g., DB00759 = vancomycin)\n"
        "  name               — INN preferred name\n"
        "  cas_number         — CAS Registry Number (e.g., 1404-90-6)\n"
        "  unii               — FDA UNII\n"
        "  synonyms           — alternative names + brand names\n"
        "  groups             — approved / investigational / withdrawn / nutraceutical\n"
        "  smiles             — canonical SMILES\n"
        "  inchi              — full InChI\n"
        "  inchi_key          — InChI key for dedup\n"
        "  mechanism_of_action — narrative MoA\n"
        "  indication         — approved indications\n"
        "  pharmacology       — Vd, Cl, t1/2, F, ppb (when available)\n"
        "  interactions       — drug-drug interactions\n\n"
        "How Lysos pulls DrugBank Open:\n"
        "  loader: src/data/drugbank.py\n"
        "  ZIP contains: drugbank.xml (full DB) + drugbank vocabulary CSV\n"
        "  parsing: lxml.etree streaming for memory efficiency\n"
        "  filter: drugs with smiles + groups overlap with {approved, investigational}\n"
        "  output: ~14,630 records on disk\n\n"
        "Use cases for Lysos:\n"
        "  1. Drug-name-to-SMILES lookup (name_to_smiles task in pro-vN)\n"
        "  2. INN / CAS / UNII cross-reference\n"
        "  3. PK panel data extraction (build_pk_panel.py uses 75 antibacterial entries)\n"
        "  4. First-line therapy identification per pathogen\n"
        "  5. Drug history (year approved, discoverer)\n\n"
        "Biases / limitations:\n"
        "  - Only-approved-or-investigational; preclinical compounds absent\n"
        "  - PK panel data is sparse for older drugs\n"
        "  - Some withdrawn drugs missing complete data\n"
        "  - Nutraceuticals filtered out (not antibacterial-relevant)"
    )
    return {"task": "teacher_raw_drugbank",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# C. NPAtlas
# ============================================================================
def trace_source_npatlas(rng: random.Random) -> dict:
    user = "What is NPAtlas? Why does Lysos use it for antimicrobials?"
    asst = (
        "[NPAtlas Source]:\n\n"
        "NPAtlas is a curated catalog of microbial natural products — covers ~36,000 "
        "natural products from bacterial + fungal sources with producer organism, "
        "biosynthesis class, structure (SMILES), and bioactivity annotations. "
        "Critical for antimicrobial design because ~70% of clinically used "
        "antibiotics are derived from natural products.\n\n"
        "Key fields for Lysos:\n"
        "  npaid              — primary identifier (e.g., NPA001234)\n"
        "  name               — compound name (often the natural product name)\n"
        "  smiles             — canonical SMILES\n"
        "  inchi_key          — InChI key for dedup\n"
        "  producer_organism  — genus + species (e.g., Streptomyces coelicolor)\n"
        "  biosynthesis_class — NRPS / PKS / hybrid / terpene / etc.\n"
        "  cluster_type       — gene cluster type\n"
        "  origin_type        — bacterial / fungal\n\n"
        "How Lysos pulls NPAtlas:\n"
        "  loader: src/data/npatlas.py\n"
        "  endpoint: https://www.npatlas.org/api/v1/compounds (paginated)\n"
        "  output: 36,434 records on disk (full dump)\n"
        "  cleaned: 13,218 records in known-antibiotics-canonical.parquet (after dedup)\n\n"
        "Use cases for Lysos:\n"
        "  1. natural_product_origin task: 'What organism produces this NP?'\n"
        "  2. natural_product_origin_smiles: 'Given organism, what SMILES?'\n"
        "  3. SAR anchor: NP scaffolds inspire synthetic analogs\n"
        "  4. Novelty reference: candidates compared against known NPs\n\n"
        "Producer organism distribution (top genera):\n"
        "  Streptomyces       — the dominant antibiotic producer (~40% of NPs)\n"
        "  Aspergillus        — fungal source (statins, cephalosporins origin)\n"
        "  Penicillium        — fungal source (the original penicillin)\n"
        "  Bacillus           — peptide antibiotics (bacitracin, surfactins)\n"
        "  Pseudomonas        — siderophores, aerugineins\n"
        "  Micromonospora     — aminoglycosides (gentamicin)\n\n"
        "Biases / limitations:\n"
        "  - Marine NPs under-represented vs soil NPs\n"
        "  - Activity annotations sparse (most entries have structure-only)\n"
        "  - Stereo definition variable (depends on original reporting)"
    )
    return {"task": "teacher_raw_npatlas",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# D. DBAASP + DRAMP (AMP databases)
# ============================================================================
def trace_source_amp_databases(rng: random.Random) -> dict:
    user = "What's the difference between DBAASP and DRAMP? How does Lysos handle peptide one-letter sequences?"
    asst = (
        "[DBAASP + DRAMP Sources]:\n\n"
        "Two parallel databases of antimicrobial peptides (AMPs). Both store "
        "peptide sequences as ONE-LETTER amino-acid codes (e.g., 'KIKWILKYWKWS'), "
        "NOT as SMILES. Lysos has a special pipeline to handle this.\n\n"
        "DBAASP — Database of Antimicrobial Activity and Structure of Peptides:\n"
        "  ~6,256 peptide entries (sequence + activity + structure)\n"
        "  fields: sequence, MIC values per pathogen, hemolysis (HC50), structure_id\n"
        "  loader: src/data/dbaasp.py\n"
        "  use: hemolysis training labels, AMP activity references\n\n"
        "DRAMP — Data Repository of Antimicrobial Peptides:\n"
        "  ~8,532 AMP entries (broader coverage, less detailed activity)\n"
        "  fields: sequence, source organism, target pathogens, family\n"
        "  loader: src/data/dramp.py\n"
        "  use: AMP corpus for broad coverage + producer-organism reasoning\n\n"
        "CRITICAL ISSUE: peptide one-letter sequences in the smiles column.\n"
        "  Pre-cleanup audit found ~9,000 rows where smiles='QSERFEQQMQGQDFSHDERFLSQAA' "
        "(a peptide sequence) instead of a real SMILES like '[N+]C(C)C(=O)N...'\n"
        "  RDKit returns None on these. Model would learn 'single-uppercase-letter "
        "strings → MIC' if not cleaned.\n\n"
        "Cleanup pipeline (in scripts/clean_chemistry_corpus.py):\n"
        "  1. Detect amino-acid one-letter sequence: regex ^[ACDEFGHIKLMNPQRSTVWY]+$\n"
        "     length 5-200 + ≥3 distinct residues\n"
        "  2. If detected: convert via Chem.MolFromSequence(seq, flavor=0)\n"
        "  3. Output: real SMILES with proper backbone\n"
        "  4. Tag: stereo_state='peptide', is_peptide=True, peptide_sequence=<original>\n"
        "  5. Route to peptide-actives-canonical.parquet (separate from small molecules)\n\n"
        "Result: 8,847 peptides recovered (99.6% conversion success).\n"
        "  158 unconvertible (likely too long, non-standard residues).\n"
        "  Now in peptide-actives-canonical.parquet alongside small-molecule corpus.\n\n"
        "Why split them?\n"
        "  Peptide pharmacology is fundamentally different from small molecules:\n"
        "  - Different ADMET behavior (membrane-active, charge-dependent)\n"
        "  - Different design space (sequence length, charge, amphipathicity)\n"
        "  - Different manufacturing (solid-phase peptide synthesis vs medchem)\n"
        "  Splitting allows separate task labels and reward components."
    )
    return {"task": "teacher_raw_dbaasp_dramp",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# E. DrugCentral
# ============================================================================
def trace_source_drugcentral(rng: random.Random) -> dict:
    user = "What is DrugCentral? How is it different from DrugBank?"
    asst = (
        "[DrugCentral Source]:\n\n"
        "DrugCentral is a free, open-access drug knowledge base from UNM. ~3,800 "
        "approved drug entries with INN, CAS, SMILES, ATC code, indications, and "
        "pharmacology. Curated by clinical pharmacologists.\n\n"
        "Key fields for Lysos:\n"
        "  cd_id              — DrugCentral ID\n"
        "  name               — INN\n"
        "  cas                — CAS Registry Number\n"
        "  smiles             — canonical SMILES\n"
        "  inchi              — full InChI\n"
        "  atc_code           — Anatomical Therapeutic Chemical classification\n"
        "  indications        — approved indications + ICD-10 codes\n"
        "  approval_year      — first FDA / EMA approval year\n"
        "  drug_class         — pharmacological class\n\n"
        "How Lysos pulls DrugCentral:\n"
        "  loader: src/data/drugcentral.py\n"
        "  endpoint: drugcentral.org PostgreSQL dump\n"
        "  output: 3,930 records on disk\n"
        "  cleaned: 3,716 in known-antibiotics-canonical.parquet\n\n"
        "vs DrugBank:\n"
        "  - DrugCentral is smaller but more curated for clinical accuracy\n"
        "  - DrugCentral has cleaner ATC + indication data\n"
        "  - DrugBank has richer mechanism narratives + interaction data\n"
        "  - We use both; DrugCentral cross-validates DrugBank entries\n\n"
        "Use cases for Lysos:\n"
        "  1. drug_structure: name → SMILES (high-confidence reference)\n"
        "  2. atc_code mapping: which drugs are J01 (antibacterials)\n"
        "  3. approval_year for time-aware splits\n"
        "  4. cross-validation of DrugBank entries"
    )
    return {"task": "teacher_raw_drugcentral",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# F. CARD (Comprehensive Antibiotic Resistance Database)
# ============================================================================
def trace_source_card(rng: random.Random) -> dict:
    user = "What is CARD? How does Lysos use resistance gene data?"
    asst = (
        "[CARD Source]:\n\n"
        "CARD is the Comprehensive Antibiotic Resistance Database — McMaster + EBI. "
        "Catalogs ~5,000 resistance genes, ~3,000 SNPs/mutations, with their target "
        "antibiotics and mechanism categories. The standard reference for AMR genomics.\n\n"
        "Key tables for Lysos:\n"
        "  ARO              — Antibiotic Resistance Ontology (term-based hierarchy)\n"
        "  AMR_genes        — gene families (e.g., bla family for β-lactamases)\n"
        "  variants         — SNPs that confer resistance (e.g., gyrA-S91F)\n"
        "  drug_targets     — which drug class each gene affects\n"
        "  organisms        — host pathogen for each gene\n\n"
        "How Lysos pulls CARD:\n"
        "  loader: src/data/card.py\n"
        "  endpoint: card.mcmaster.ca/download (JSON release)\n"
        "  filter: 8 priority pathogens\n"
        "  output: 3,543 records on disk (resistance gene catalog per pathogen)\n\n"
        "Use cases for Lysos:\n"
        "  1. resistance_gene_explain task: 'What is mecA?'\n"
        "  2. predict_resistance_escape backend: which mutations exist for this drug class\n"
        "  3. resistome briefing: get_pathogen_resistome tool returns CARD-derived data\n"
        "  4. Reward training: resistance_robustness reward uses CARD escape mechanisms\n\n"
        "Per-pathogen resistance gene examples (from CARD):\n"
        "  MRSA:    mecA (PBP2a), blaZ (penicillinase), vanA (acquired)\n"
        "  Mtb:     rpoB (rifampin), katG (INH activator), inhA (INH target), gyrA (FQ)\n"
        "  EColi-CRE: blaKPC, blaNDM, blaOXA-48, blaCTX-M (ESBL)\n"
        "  KpneuCRE: blaKPC-3 (D179Y emerging), blaOXA-48 group, blaNDM\n"
        "  Abaum:   blaOXA-23, blaOXA-24, blaOXA-58, OmpA (porin)\n"
        "  Paer:    AmpC (chromosomal), MexAB-OprM, blaVIM, blaIMP, blaNDM\n"
        "  VRE:     vanA, vanB, vanC, 23S G2576T (linezolid-R)\n"
        "  NGono:   penA mosaic XXXIV/XXXV, gyrA-S91F, mtrR (efflux)\n\n"
        "Related: MEGARES (Colorado State) — temporal data for resistance emergence."
    )
    return {"task": "teacher_raw_card",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# G. PDB
# ============================================================================
def trace_source_pdb(rng: random.Random) -> dict:
    user = "How does Lysos use the PDB? What structures do we have for each pathogen?"
    asst = (
        "[RCSB PDB Source]:\n\n"
        "The Protein Data Bank — ~200K experimentally-determined macromolecular "
        "structures. For Lysos: the source of structural targets, ligand-bound "
        "complexes, and the foundation for propose_pocket_aware + dock_against_target + "
        "predict_complex_structure tools.\n\n"
        "How Lysos pulls PDB:\n"
        "  loader: src/data/pdb.py\n"
        "  endpoint: rcsb.org GraphQL + REST APIs\n"
        "  filter: 8 priority pathogens + clinically-relevant target proteins\n"
        "  output: 3,136 structures on disk (mirror)\n\n"
        "Per-pathogen structural target catalog:\n"
        "  MRSA / PBP2a:\n"
        "    1VQQ — apo PBP2a (constricted active site)\n"
        "    3ZG0 — PBP2a + ceftaroline (open conformation)\n"
        "    5M18 — PBP2a + ceftobiprole\n"
        "  Mtb:\n"
        "    2NSD — InhA + INH-NAD adduct\n"
        "    4TZK — InhA + triclosan-class diphenyl ether\n"
        "    1SJ2 — KatG (INH activator)\n"
        "    5UAQ — RpoB (rifampin binding pocket, RRDR)\n"
        "  EColi-CRE / KPC-2:\n"
        "    6Q9B — KPC-2 (1.6 Å) — covalent avibactam\n"
        "    5VFA — KPC-3 (D179Y selection target)\n"
        "    3SPU — NDM-1 (Zn2+ MBL)\n"
        "    3HBR — OXA-48\n"
        "  Abaum:\n"
        "    4JF6 — OXA-23\n"
        "  Paer:\n"
        "    3OG7 — PBP3 (ceftolozane target)\n"
        "    5O8R — MexAB-OprM efflux complex\n"
        "  VRE:\n"
        "    1IOG — VanA D-Ala-D-Lac ligase\n"
        "  NGono:\n"
        "    6P58 — PBP2 (penA mosaic XXXIV)\n"
        "    5N6S — GyrB (zoliflodacin target)\n\n"
        "Use cases for Lysos:\n"
        "  1. find_target_structure tool returns PDB id per pathogen\n"
        "  2. propose_pocket_aware uses PDB ligand-binding pocket geometry\n"
        "  3. dock_against_target / predict_complex_structure use PDB structure\n"
        "  4. Boltz-2 sweep: cache pose-confidence per (smiles, pdb) pair\n"
        "  5. render_3d_scene visualizes ligand-target complex"
    )
    return {"task": "teacher_raw_pdb",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# H. ZINC + PubChem
# ============================================================================
def trace_source_zinc_pubchem(rng: random.Random) -> dict:
    user = "What's ZINC? PubChem? How does Lysos use them?"
    asst = (
        "[ZINC + PubChem Sources]:\n\n"
        "Two virtual library sources for property-matched decoys + chemical-space "
        "exploration.\n\n"
        "ZINC (UCSF / IRWIN-LAB):\n"
        "  ~22 billion virtual compounds, organized by:\n"
        "    drug-like / lead-like / fragment-like subsets\n"
        "    in-stock vs make-on-demand\n"
        "    purchasability ranks\n"
        "  loader: src/data/zinc.py\n"
        "  Lysos subset: 100 records on disk (FDA + in-trials), "
        "but DUD-E decoys generated from a synthetic 100K pool when ZINC raw not available\n\n"
        "PubChem (NCBI):\n"
        "  ~110M compounds with bioassay data linkages\n"
        "  loader: src/data/pubchem.py\n"
        "  output: 1,268 records (specific antibacterial AIDs)\n"
        "  47 fresh AIDs replaced retired ones in our 2026-05-01 refresh\n\n"
        "Use cases for Lysos:\n"
        "  1. DUD-E decoys: scripts/build_decoys.py samples 5-50 property-matched "
        "decoys per active. Cleans the chemistry classifier of 'looks-like-active' "
        "shortcuts.\n"
        "  2. Negative class for property-prediction training\n"
        "  3. Novelty reference: candidates compared against ZINC virtual space\n"
        "  4. Patent landscape (PubChem PatentView linkages)\n\n"
        "DUD-E methodology (used in our build_decoys.py):\n"
        "  For each active in known-antibiotics-canonical, sample N decoys matched on:\n"
        "    MW ± 25 Da, logP ± 1.0, HBA ± 2, HBD ± 1,\n"
        "    rotatable bonds ± 2, ring count ± 1, charge ± 1\n"
        "  Result: 13,990 active-decoy pairs, 4,519 training rows in pro-vN.\n"
        "  Without DUD-E decoys, the model can shortcut on 'looks-like-active' surface "
        "features and miss real pharmacophore-driven activity.\n\n"
        "Bias: ZINC is heavy on drug-like + lead-like — under-represents AMP, "
        "macrocycle, and metallo-organic chemistries. PubChem has broader coverage "
        "but less curated."
    )
    return {"task": "teacher_raw_zinc_pubchem",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# I. TDC
# ============================================================================
def trace_source_tdc(rng: random.Random) -> dict:
    user = "What is the Therapeutics Data Commons? What benchmarks does Lysos use?"
    asst = (
        "[TDC Source]:\n\n"
        "Therapeutics Data Commons (Harvard) — open-access benchmark for ML in drug "
        "discovery. ~70 task-specific benchmark datasets across ADMET, synthesis, "
        "tox, HTS. The standard reference for benchmarking molecular property "
        "prediction.\n\n"
        "How Lysos pulls TDC:\n"
        "  builder: scripts/prepare_tdc_data.py (uses PyTDC)\n"
        "  output: 151,530 instruction-tuned examples in tdc-stage1\n"
        "    106,070 train + 15,153 valid + 30,307 test\n\n"
        "TDC benchmarks Lysos uses (28 tasks):\n"
        "  ADMET (absorption-distribution-metabolism-excretion-toxicity):\n"
        "    - bbb_martins      — Blood-brain barrier penetration\n"
        "    - bioavailability_ma — oral bioavailability\n"
        "    - hia_hou          — human intestinal absorption\n"
        "    - pampa_ncats      — passive permeability\n"
        "    - pgp_broccatelli  — P-gp substrate\n"
        "    - lipophilicity    — logD\n"
        "    - solubility       — aqueous solubility\n"
        "    - ppbr_az          — plasma protein binding ratio\n"
        "    - half_life_obach  — t1/2\n"
        "    - clearance_microsome_az / hepatocyte_az — Cl\n"
        "  CYP isoforms:\n"
        "    - cyp1a2_veith / cyp2c9_veith / cyp2c19_veith / cyp2d6_veith / cyp3a4_veith\n"
        "    - cyp2c9_substrate / cyp2d6_substrate / cyp3a4_substrate\n"
        "  Toxicity:\n"
        "    - ames             — bacterial mutagenicity\n"
        "    - dili             — drug-induced liver injury\n"
        "    - herg_karim       — hERG blockade\n"
        "    - skin_reaction\n"
        "    - carcinogens_lagunin\n"
        "  HTS / Activity:\n"
        "    - hiv_replicate    — antiviral screen\n"
        "    - sars_cov2_3clpro — COVID protease screen\n\n"
        "Use cases for Lysos:\n"
        "  1. Stage 1 SFT (TxGemma-4 base): instruction-tune on TDC tasks before AMR specialization\n"
        "  2. ADMET reward components: TDC-derived predictors\n"
        "  3. Cross-validation: TDC test split as held-out eval baseline\n"
        "  4. Task naming convention: pro-vN inherits TDC-style task labels"
    )
    return {"task": "teacher_raw_tdc",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# J. CO-ADD
# ============================================================================
def trace_source_coadd(rng: random.Random) -> dict:
    user = "What is CO-ADD? Why is it valuable for AMR?"
    asst = (
        "[CO-ADD Source]:\n\n"
        "Community for Open Antimicrobial Drug Discovery (UQ + Wellcome Trust). "
        "Open-data antimicrobial screening — anyone can submit compounds for free "
        "MIC testing against priority pathogens. Resulting data is open-access. "
        "~300K+ compounds tested.\n\n"
        "Key data:\n"
        "  primary screen           — single-concentration (32 µg/mL) growth inhibition\n"
        "  dose-response confirmation — full MIC curve for actives\n"
        "  pathogen panel           — E. coli + S. aureus + K. pneumoniae + P. aeruginosa + A. baumannii\n"
        "  compound metadata        — submitter origin (academic / pharma / open consortium)\n\n"
        "How Lysos pulls CO-ADD:\n"
        "  builder: scripts/build_coadd_examples.py\n"
        "  source: CO-ADD database CSV exports + Wellcome NTD set\n"
        "  output: ~48K coadd_inhibition_screen rows + ~24K coadd_mic_prediction rows in pro-vN\n"
        "  cleanup: dedup at SMILES + remove single-concentration screens with no follow-up\n\n"
        "CO-ADD task types in pro-vN:\n"
        "  coadd_screen           — primary single-concentration outcome\n"
        "  coadd_mic_prediction   — dose-response MIC value\n"
        "  coadd_selectivity_profile — multi-pathogen panel for one compound\n\n"
        "Why CO-ADD is valuable:\n"
        "  - Antimicrobial-specific (vs general HTS in PubChem)\n"
        "  - Physical screen results (vs predicted activity)\n"
        "  - Open-access (no paywall) — democratizes AMR drug discovery\n"
        "  - Recent data (active program, ongoing submissions)\n\n"
        "Bias: skewed toward submitter pipelines (mostly academic compounds + "
        "natural products); industrial proprietary chemistry under-represented."
    )
    return {"task": "teacher_raw_coadd",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# K. Core SAR concepts
# ============================================================================
def trace_core_sar(rng: random.Random) -> dict:
    concepts = [
        ("pharmacophore", "the spatial arrangement of features (H-bond donor, acceptor, hydrophobic group, aromatic) that engage the target. Two molecules with the same pharmacophore can have very different scaffolds. The pharmacophore is what activity REQUIRES; the scaffold is what activity is decorated on."),
        ("bioisostere", "a chemical group that can substitute for another while preserving similar activity. Classic examples: COOH ↔ tetrazole, phenyl ↔ thiophene, OH ↔ NH2 ↔ F, methyl ↔ trifluoromethyl. Bioisosteric replacement is the most common operation in scaffold_hop."),
        ("scaffold", "the core ring + connector framework of a molecule, abstracting away the substituents. Scaffold-distinct molecules can have similar activity if they share a pharmacophore. Scaffold hopping = swapping the core while preserving the pharmacophore."),
        ("activity cliff", "a pair of structurally similar molecules (Tanimoto ≥ 0.85) with very different activities (ΔlogMIC ≥ 1.5 or 30+ fold). Cliffs reveal CRITICAL structural features that drive activity. Training data with explicit cliffs (~227 pairs in pro-v6+) sharpens the model's structure-activity reasoning."),
        ("Tanimoto similarity", "overlap fraction of bit-set fingerprints. Range [0, 1]. Tanimoto ≥ 0.6 → close analogs; ≥ 0.85 → near-identical. Used for novelty filtering (Tanimoto < 0.4 vs known corpus). Computed on Morgan ECFP4 fingerprints."),
        ("Morgan fingerprint", "a circular fingerprint that hashes atom-environment neighborhoods up to radius r. ECFP4 = radius 2 (4-atom diameter). Standard parameters: 2048 bits, radius 2. The default for Tanimoto similarity in cheminformatics."),
        ("Lipinski Rule of 5", "drug-likeness heuristic: MW ≤ 500, logP ≤ 5, HBD ≤ 5, HBA ≤ 10. Predicts oral bioavailability. Antibacterials often violate (vancomycin MW 1450) when IV-only."),
        ("Veber rules", "Veber's drug-likeness extension: rotatable_bonds ≤ 10, TPSA ≤ 140 Å². Predicts oral bioavailability. Often used alongside Lipinski."),
        ("scaffold hopping", "the design strategy of replacing the core scaffold while preserving the pharmacophore. Used to escape patent landscape, evade resistance, or improve drug-likeness. Operationally: 'pyridine→pyrimidine', 'phenyl→thiazole', 'ester→amide'."),
        ("matched molecular pair (MMP)", "a pair of molecules differing by exactly one structural feature (e.g., -H to -CH3 at one position). MMPs reveal the contribution of that single feature to activity. mmpdb is the standard tool for mining MMPs."),
        ("Free-Wilson analysis", "decomposing activity into additive contributions of each substituent at each position. Useful for late-stage optimization within a scaffold series."),
        ("retrosynthetic analysis", "working backwards from the target SMILES to identify available starting materials and the reaction sequence. AizynthFinder + Synthia + IBM RoboRXN are standard tools. Output: reaction tree with cost + step count."),
    ]
    concept, explanation = rng.choice(concepts)
    user = f"Explain the SAR concept: {concept}."
    asst = f"[Core SAR — {concept}]:\n\n{concept.title()} is {explanation}\n\nIn the Lysos design pipeline, {concept} appears in:\n"
    if concept in ["pharmacophore", "scaffold", "scaffold hopping"]:
        asst += "  - propose_pocket_aware (initial proposal generation)\n  - scaffold_hop (iteration)\n  - Critic novelty review\n"
    elif concept in ["bioisostere", "matched molecular pair (MMP)", "activity cliff"]:
        asst += "  - scaffold_hop generates bioisosteric alternatives\n  - mine_activity_cliffs.py extracts MMP cliffs for training\n  - Critic uses cliffs for SAR reasoning\n"
    elif concept in ["Tanimoto similarity", "Morgan fingerprint"]:
        asst += "  - find_similar_drugs uses Morgan ECFP4 + Tanimoto\n  - novelty reward component (cliff at 0.4 vs known corpus)\n  - compare_molecules tool\n"
    elif concept in ["Lipinski Rule of 5", "Veber rules"]:
        asst += "  - predict_admet returns Lipinski violations + Veber pass\n  - structural_alerts reward component\n  - Critic drug-likeness dimension\n"
    elif concept in ["retrosynthetic analysis", "Free-Wilson analysis"]:
        asst += "  - predict_synthesis_route + AizynthFinder backend\n  - estimate_synth_cost\n  - manufacturing reasoning sub-agent\n"
    asst += "\nDECISION: this concept is a first-class citizen in Lysos design reasoning."
    return {"task": "teacher_core_sar",
            "concept": concept,
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# L. Core MIC methodology
# ============================================================================
def trace_core_mic(rng: random.Random) -> dict:
    user = "How is MIC measured? What's the difference between EUCAST and CLSI breakpoints?"
    asst = (
        "[Core MIC Methodology]:\n\n"
        "MIC = Minimum Inhibitory Concentration — the lowest antibiotic concentration "
        "that PREVENTS visible bacterial growth. Reported in µg/mL or mg/L (equivalent).\n\n"
        "STANDARD METHODS:\n"
        "  Broth microdilution (gold standard):\n"
        "    - 96-well plate with 2-fold serial dilutions (typical 0.06-128 µg/mL)\n"
        "    - Mueller-Hinton broth (or specialized media for fastidious organisms)\n"
        "    - Standardized inoculum: 5×10⁵ CFU/mL\n"
        "    - Incubation: 16-20 h at 35°C (24 h for slow growers like Mtb)\n"
        "    - Read: lowest concentration with no visible growth\n"
        "  Agar dilution:\n"
        "    - Compound incorporated in agar at varying concentrations\n"
        "    - Used for fastidious organisms; lower throughput\n"
        "  Etest (gradient diffusion):\n"
        "    - Strip with antibiotic gradient placed on agar\n"
        "    - Read MIC where growth ellipse intersects strip\n"
        "    - Practical for clinical labs; less precise than microdilution\n\n"
        "MIC HARMONIZATION ISSUES:\n"
        "  Different std_types in ChEMBL: MIC, MIC50, MIC90, IC50, EC50 — NOT interchangeable.\n"
        "  - MIC          = single isolate inhibition\n"
        "  - MIC50 / MIC90 = isolate-population statistics (50th / 90th percentile)\n"
        "  - IC50         = enzyme inhibition concentration (different scale)\n"
        "  Lysos handling: log-transform to log10(MIC_µM); harmonize units.\n\n"
        "BREAKPOINTS — what counts as susceptible vs resistant:\n"
        "  EUCAST (European):\n"
        "    Sets clinical breakpoints based on PK/PD + epidemiological cutoff\n"
        "    Susceptible (S) / Susceptible-Increased Exposure (I) / Resistant (R)\n"
        "    Updated annually; available at eucast.org\n"
        "  CLSI (US):\n"
        "    Sets breakpoints via the Clinical and Laboratory Standards Institute\n"
        "    Susceptible / Intermediate / Resistant\n"
        "    Often differ slightly from EUCAST (e.g., S. aureus + meropenem)\n"
        "  ECOFF (Epidemiological cutoff):\n"
        "    Statistical separation between wild-type and non-wild-type populations\n"
        "    Lower than clinical breakpoint typically\n\n"
        "EXAMPLE BREAKPOINTS (vancomycin vs S. aureus):\n"
        "  EUCAST: S ≤ 2 µg/mL, I = 2-4, R > 4\n"
        "  CLSI:   S ≤ 2, I = 4-8, R ≥ 16\n\n"
        "ACTIVITY CATEGORIES IN LYSOS:\n"
        "  Active:      MIC ≤ 1 µg/mL (hit-quality, advance)\n"
        "  Borderline:  MIC 1-4 µg/mL (acceptable for combos or high-doses)\n"
        "  Inactive:    MIC > 4 µg/mL (kill or major redesign)\n\n"
        "DECISION: standardize all MIC values to log10(MIC_µM) before training; track standard_type for unit conversion."
    )
    return {"task": "teacher_core_mic_methodology",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# M. Core resistance biology
# ============================================================================
def trace_core_resistance(rng: random.Random) -> dict:
    mechanisms = [
        ("efflux pumps", "membrane proteins that actively export antibiotics out of the bacterial cell. Examples: AcrAB-TolC (E. coli), MexAB-OprM (P. aeruginosa), NorA (S. aureus). Up-regulation confers multi-drug resistance. Lysos design strategy: avoid known efflux substrates; use efflux-pump inhibitors (EPIs) in combo."),
        ("β-lactamases", "enzymes that hydrolyze the β-lactam ring of penicillins/cephalosporins/carbapenems. Class A (KPC, CTX-M, TEM, SHV — Ser-70 catalytic), Class B (MBLs: NDM, VIM, IMP — Zn²⁺ catalytic), Class C (AmpC — chromosomal), Class D (OXA — Ser-79 + carbamylated Lys-82). Inhibitors: clavulanate, sulbactam, tazobactam (older) → avibactam, vaborbactam, durlobactam (newer DBO/boronate)."),
        ("target site modification", "mutation of the antibiotic binding site so the drug no longer binds tightly. Examples: gyrA-S91F (FQ resistance), 23S G2576T (linezolid resistance), penA mosaic XXXIV (3GC resistance in NGono), rpoB-S531L (rifampin resistance). Lysos design strategy: design analogs that contact residues OUTSIDE the canonical resistance target — e.g., extend the allosteric tail."),
        ("target replacement", "the bacterium acquires an alternative target enzyme that the drug doesn't bind. Examples: mecA encodes PBP2a (low-affinity β-lactam target), vanA acquires D-Ala:D-Lac ligase (vancomycin can't bind). Lysos design: target the alternative protein directly (e.g., ceftaroline binds PBP2a allosterically)."),
        ("porin loss", "down-regulation of outer membrane porins reduces drug entry. Common in K. pneumoniae (ompK35/36 loss) + A. baumannii (carO loss). Often combined with carbapenemases for high-level resistance. Lysos design: siderophore-conjugate drugs that enter via TonB-dependent receptors bypass porins."),
        ("enzymatic inactivation", "covalent modification of the antibiotic. Examples: aminoglycoside phosphotransferases / acetyltransferases / nucleotidyltransferases; chloramphenicol acetyltransferase; macrolide methylases (Erm). Lysos: design enzyme-stable variants or use combo with enzyme inhibitors."),
        ("biofilm tolerance", "physiological state — not a genetic mutation. Bacteria in biofilm matrix have reduced metabolism + reduced drug penetration. Common in Pseudomonas (CF lung), MRSA (catheter), VRE (endocarditis). Strategy: combo with biofilm-disrupting agents (DNase, alginate lyase)."),
        ("persisters", "phenotypic non-replicating subpopulation that tolerates antibiotic exposure. Key in Mtb (granuloma), S. aureus (chronic infection). Strategy: bedaquiline-class agents that target ATP synthase (kills persisters)."),
        ("plasmid transfer", "horizontal gene transfer of resistance via conjugative plasmids. KPC and NDM are plasmid-borne — spread rapidly between species. Strategy: monitor plasmid epidemiology; design drugs whose target is chromosome-encoded only."),
        ("transposon-mediated mobilization", "IS elements + transposons mobilize resistance genes between chromosomes and plasmids. Tn4401 carries blaKPC. ISCR1 mobilizes class 1 integrons. Implications: resistance can spread without active transfer."),
    ]
    label, explanation = rng.choice(mechanisms)
    user = f"Explain the resistance mechanism: {label}."
    asst = (
        f"[Core Resistance Biology — {label.title()}]:\n\n"
        f"{label.title()}: {explanation}\n\n"
        f"In Lysos design pipeline, {label} affects:\n"
        f"  - predict_resistance_escape backend (model is trained on CARD-derived mechanism categories)\n"
        f"  - resistance_robustness reward component (Stage 3 GRPO penalizes candidates susceptible to known mechanisms)\n"
        f"  - Designer's per-pathogen briefing (get_pathogen_resistome includes the dominant mechanism)\n"
        f"  - Critic's escape-mutation review dimension\n\n"
        f"DECISION: every Designer iteration starts with the resistome briefing; the dominant mechanism shapes the design."
    )
    return {"task": "teacher_core_resistance_biology",
            "mechanism": label,
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# N. Core PK/PD
# ============================================================================
def trace_core_pkpd(rng: random.Random) -> dict:
    user = "Explain PK/PD in antimicrobial design. What targets matter?"
    asst = (
        "[Core PK/PD]:\n\n"
        "Pharmacokinetics (PK) = what the body does to the drug. "
        "Pharmacodynamics (PD) = what the drug does to the bacterium.\n\n"
        "KEY PK PARAMETERS:\n"
        "  Vd (volume of distribution, L/kg)        — apparent volume the drug occupies\n"
        "  Cl (clearance, mL/min/kg)                — rate of drug elimination\n"
        "  t1/2 (half-life, h)                       — time for plasma concentration to halve\n"
        "  F (bioavailability, 0-1)                  — fraction reaching systemic circulation\n"
        "  ppb (plasma protein binding, 0-1)         — fraction bound to plasma proteins\n"
        "  Cmax                                     — peak plasma concentration\n"
        "  AUC (area under curve, mg·h/L)            — total exposure\n\n"
        "STEADY-STATE FORMULA:\n"
        "  Css(avg) = (Dose × F) / (Cl × τ)\n"
        "    where τ = dosing interval\n"
        "  Free Css = Css × (1 - ppb)\n\n"
        "PD TARGETS BY ANTIBIOTIC CLASS:\n"
        "  Concentration-dependent (kill rate scales with peak):\n"
        "    aminoglycosides           — Cmax/MIC ≥ 8-10\n"
        "    fluoroquinolones          — AUC/MIC ≥ 100-125 (gram-negatives)\n"
        "    daptomycin                — AUC/MIC ≥ 800-1000\n"
        "  Time-dependent (kill rate plateaus, depends on duration above MIC):\n"
        "    β-lactams                 — fT > MIC ≥ 50-70%\n"
        "    macrolides                — fT > MIC ≥ 40-60%\n"
        "    linezolid                 — AUC/MIC ≥ 80-120\n"
        "  Concentration- + time-dependent (mixed):\n"
        "    vancomycin                — AUC/MIC ≥ 400 (target trough 15-20 µg/mL)\n"
        "    glycopeptides             — AUC/MIC ≥ 400\n\n"
        "DOSE-INTERVAL DECISIONS:\n"
        "  - Long t1/2 (>12h) → once daily acceptable\n"
        "  - Short t1/2 (<3h) → q6-q8h dosing\n"
        "  - Concentration-dependent → high-dose, longer interval (extended-interval aminoglycoside)\n"
        "  - Time-dependent → continuous infusion or frequent dosing (extended-infusion β-lactam)\n\n"
        "RENAL DOSING (Dettli method):\n"
        "  Cl_adj = Cl_normal × (1 - F_renal × (1 - CrCl/100))\n"
        "  F_renal = fraction of clearance via kidneys (per drug)\n"
        "  Adjusted dose = (Cl_adj / Cl_normal) × normal dose\n\n"
        "EXAMPLE — vancomycin in CrCl 30:\n"
        "  Vancomycin F_renal = 0.85\n"
        "  Adjustment factor = 1 - 0.85 × (1 - 30/100) = 1 - 0.85 × 0.7 = 0.405\n"
        "  Adjusted dose = 0.405 × normal = 40.5% of normal dose\n\n"
        "TISSUE PENETRATION CONSIDERATIONS:\n"
        "  CSF (CNS infections):  Vd > 0.5 L/kg, lipophilic preferred\n"
        "  Lung (pneumonia):      ELF concentration > MIC ≥ 50%\n"
        "  Bone (osteomyelitis):  high Vd, sustained exposure\n"
        "  Biofilm:               poorly defined — combos preferred\n\n"
        "DECISION: PK/PD targets dictate dosing strategy; mismatched dosing is a top cause of treatment failure even when the drug is theoretically active in vitro."
    )
    return {"task": "teacher_core_pkpd",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# O. Core ADMET
# ============================================================================
def trace_core_admet(rng: random.Random) -> dict:
    user = "What is ADMET? What's the 5-stoplight panel?"
    asst = (
        "[Core ADMET]:\n\n"
        "ADMET = Absorption, Distribution, Metabolism, Excretion, Toxicity. "
        "The set of pharmacokinetic + toxicological properties that determine "
        "whether a candidate can be a drug, beyond its in vitro activity.\n\n"
        "5-STOPLIGHT ADMET PANEL (Lysos uses this in predict_admet):\n"
        "  1. MW ≤ 500 Da              — Lipinski; oral absorption\n"
        "  2. logP ≤ 5                 — lipophilicity; membrane permeability\n"
        "  3. HBD ≤ 5                  — H-bond donors; solubility + permeability\n"
        "  4. HBA ≤ 10                 — H-bond acceptors\n"
        "  5. TPSA ≤ 140 Å²            — Veber; oral bioavailability + CNS penetration\n"
        "  Pass criterion: 4 of 5\n\n"
        "VEBER RULES (extension of Lipinski):\n"
        "  rotatable_bonds ≤ 10        — flexibility; oral bioavailability\n"
        "  TPSA ≤ 140 Å²               — surface polarity\n\n"
        "EGAN BOUNDARIES:\n"
        "  logP ≤ 5.88 + TPSA ≤ 131.6 — alternative drug-likeness gate\n\n"
        "CNS PENETRATION (BBB):\n"
        "  logP ≥ 1.5 + TPSA ≤ 90 + MW ≤ 450 → likely BBB-penetrant\n"
        "  Most antibacterials are NOT CNS-penetrant (poor CNS infection coverage).\n"
        "  Exceptions: chloramphenicol, fluoroquinolones, some carbapenems.\n\n"
        "TOXICITY STOPLIGHTS (Lysos predicts via TDC-trained models):\n"
        "  Ames (mutagenicity)         — bacterial TA98/TA100 reversion\n"
        "  hERG (cardiotoxicity)       — IKr K+ channel blockade → QT prolongation\n"
        "  DILI (hepatotox)            — drug-induced liver injury risk\n"
        "  Skin reaction (allergy)     — anaphylaxis / SJS risk\n"
        "  Carcinogenicity             — long-term oncogenic risk\n\n"
        "CYP ISOFORMS (drug-drug interactions):\n"
        "  CYP3A4 (most metabolized)   — most common DDI source\n"
        "  CYP2D6                      — debrisoquine-class metabolism\n"
        "  CYP2C9                      — warfarin metabolism (TMP-SMX inhibits)\n"
        "  CYP2C19                     — proton pump inhibitor metabolism\n"
        "  CYP1A2                      — caffeine metabolism (cipro inhibits)\n"
        "  Lysos predicts: substrate / inhibitor / inducer per isoform\n\n"
        "PHASE I METABOLISM:\n"
        "  Oxidation (CYP3A4 dominant), reduction, hydrolysis\n"
        "  Functional groups vulnerable: ester, amide, ether, alkyl, aromatic ring\n"
        "PHASE II METABOLISM:\n"
        "  Conjugation: glucuronidation (UGTs), sulfation (SULTs), GSH (GSTs)\n"
        "  Less commonly relevant to antibacterial design\n\n"
        "DECISION: ADMET is the gate AFTER activity. Many active candidates fail here; pre-emptive ADMET screening avoids late-stage failure."
    )
    return {"task": "teacher_core_admet",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# P. Core 3D structure
# ============================================================================
def trace_core_3d_structure(rng: random.Random) -> dict:
    user = "Explain 3D structural concepts: pose, RMSD, ipTM, induced fit, allostery."
    asst = (
        "[Core 3D Structure]:\n\n"
        "Lysos uses 3D structural reasoning when scoring binding affinity + designing "
        "pocket-aware analogs.\n\n"
        "POSE — the 3D coordinates of the ligand in the binding pocket. Generated by "
        "docking (Vina, GOLD, Glide) or co-folding (Boltz-2, AlphaFold-3, RoseTTAFold).\n\n"
        "RMSD (Root-Mean-Square Deviation):\n"
        "  Measures how close a predicted pose is to a reference (e.g., crystal structure).\n"
        "  Computed over ligand heavy atoms.\n"
        "  RMSD < 1.5 Å    → excellent pose\n"
        "  RMSD 1.5-2.5 Å  → reasonable\n"
        "  RMSD > 2.5 Å    → likely incorrect\n\n"
        "ipTM (interface predicted Template Modeling score):\n"
        "  Boltz-2 / AlphaFold-3 native confidence score for the protein-ligand interface.\n"
        "  Range [0, 1].\n"
        "  ipTM > 0.8  → high-confidence pose\n"
        "  ipTM 0.6-0.8 → medium-confidence; verify with docking\n"
        "  ipTM < 0.6  → low-confidence; pose unreliable\n\n"
        "pTM (predicted Template Modeling score):\n"
        "  Whole-complex confidence (not just the interface).\n"
        "  Used as overall structural confidence.\n\n"
        "BINDING ENERGY:\n"
        "  ΔG (kcal/mol) — Gibbs free energy of binding (negative = favorable)\n"
        "    ΔG < -10 kcal/mol  → tight binder (pKd > 7)\n"
        "    ΔG -7 to -10        → moderate binder\n"
        "    ΔG > -7             → weak binder\n"
        "  pKd = -ΔG / 1.36     → log10 of dissociation constant\n"
        "  pKd > 7 ≡ Kd < 100 nM (clinically actionable)\n\n"
        "INDUCED FIT:\n"
        "  The receptor changes conformation upon ligand binding. Examples:\n"
        "  - PBP2a: ceftaroline binds the allosteric site, OPENS the active site\n"
        "  - HIV protease: ligand binding closes the flaps over the active site\n"
        "  - GPCRs: agonist binding stabilizes the active conformation\n"
        "  Implication: rigid docking can miss induced-fit binders; co-folding (Boltz-2) handles this.\n\n"
        "ALLOSTERY:\n"
        "  Binding at one site affects activity at a distant site.\n"
        "  Lysos PBP2a allosteric site is ~60 Å from the catalytic Ser-403.\n"
        "  Allosteric binders can:\n"
        "    - INHIBIT the catalytic site (e.g., MEK inhibitors)\n"
        "    - ENHANCE binding of an orthosteric ligand (e.g., ceftaroline opening PBP2a)\n"
        "  Lysos design strategy for MRSA: extend the allosteric tail of 5GC scaffolds.\n\n"
        "PHARMACOPHORE-MAP:\n"
        "  3D arrangement of feature points (HBD, HBA, hydrophobic, aromatic) that "
        "engage the target. Multiple molecules can share a pharmacophore-map.\n\n"
        "DECISION: 3D pose + binding-energy reasoning are first-class signals; cheap "
        "tools handle activity gating, expensive tools (Boltz-2) handle pose verification."
    )
    return {"task": "teacher_core_3d_structure",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# Q. Core synthesis
# ============================================================================
def trace_core_synthesis(rng: random.Random) -> dict:
    user = "How does Lysos evaluate synthesis feasibility? What's SA score?"
    asst = (
        "[Core Synthesis]:\n\n"
        "Designing 'unmakable' molecules is a common AI-design failure. Lysos uses "
        "retrosynthesis tools to keep candidates synthesizable.\n\n"
        "SA SCORE (Synthetic Accessibility):\n"
        "  Range: 1 (trivial) to 10 (very hard).\n"
        "  Computed from fragment frequencies in a known-synthesis corpus + complexity penalties.\n"
        "  SA ≤ 4   → easy, few-step synthesis\n"
        "  SA 4-6   → moderate, medchem feasible\n"
        "  SA 6-8   → hard, expert chemist required\n"
        "  SA > 8   → likely unmakable\n"
        "  Implementation: rdkit.Chem.SAscorer (Ertl + Schuffenhauer 2009)\n\n"
        "RETROSYNTHESIS TOOLS:\n"
        "  AizynthFinder (AstraZeneca, open-source)\n"
        "    - MCTS-based retrosynthesis planning\n"
        "    - Trained on USPTO patent reactions corpus (~3M reactions)\n"
        "    - Returns a tree of disconnections + estimated cost\n"
        "  Synthia (formerly Chematica, MilliporeSigma)\n"
        "    - Commercial; rule-based\n"
        "  IBM RoboRXN\n"
        "    - Transformer-based reaction prediction\n"
        "  Lysos uses AizynthFinder via predict_synthesis_route tool.\n\n"
        "ROUTE QUALITY METRICS:\n"
        "  estimated_steps         — step count (≤6 ideal, ≤8 acceptable)\n"
        "  estimated_cost_usd_per_g — at lab scale (5-10g)\n"
        "  confidence_route_found  — AizynthFinder probability the route is valid\n"
        "  starting_material_cost   — bottleneck if expensive\n\n"
        "STEP-COUNT THRESHOLDS:\n"
        "  ≤ 4 steps   → ideal; convergent synthesis preferred\n"
        "  5-6 steps   → acceptable; medchem standard\n"
        "  7-8 steps   → borderline; flag for chemistry team review\n"
        "  > 8 steps   → poor; suggest scaffold-hop to shorter route\n\n"
        "COST DRIVERS:\n"
        "  1. Chiral resolution (chromatography is the #1 cost driver at GMP scale)\n"
        "  2. Expensive starting materials (>$200/g raw → bottleneck)\n"
        "  3. Macrocyclization (low-yield + high-dilution requirements)\n"
        "  4. Late-stage chiral centers (forces convergent synthesis)\n"
        "  5. Difficult separations (chromatography vs crystallization)\n\n"
        "GMP COST MULTIPLIER (vs lab scale):\n"
        "  Typical: 5-10× lab cost at GMP scale (10 kg)\n"
        "  Process optimization can reduce 2-4×\n"
        "  Antibacterial market price: $800-3000/g hospital IV; generic $1-50/g\n\n"
        "DECISION: predict_synthesis_route runs after Critic clearance; SA + cost gate the candidate's wet-lab priority."
    )
    return {"task": "teacher_core_synthesis",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# R. Core regulatory
# ============================================================================
def trace_core_regulatory(rng: random.Random) -> dict:
    user = "Explain the regulatory landscape for new antibiotics: FDA pathways, QIDP, breakpoints."
    asst = (
        "[Core Regulatory]:\n\n"
        "Antibacterial regulation has special pathways given the public health "
        "urgency of AMR.\n\n"
        "FDA PATHWAYS:\n"
        "  Standard NDA (505(b)(1))                   — full clinical program, 7-12 yr\n"
        "  Limited Population (LPAD) — 2017 GAIN Act  — smaller-population approval\n"
        "    Requirements: pathogen-specific subpopulation, unmet need\n"
        "  Breakthrough Therapy designation           — accelerated review\n"
        "  Fast Track designation                     — for serious unmet need\n"
        "  Priority Review                            — 6-month FDA action\n\n"
        "QIDP (Qualified Infectious Disease Product):\n"
        "  Enacted in 2012 (GAIN Act). Provides:\n"
        "    - 5 years extended exclusivity (added on top of standard 5y)\n"
        "    - Priority Review eligibility\n"
        "    - Fast Track eligibility\n"
        "    - For pathogens listed by FDA as qualifying (covers our 8 priority pathogens)\n"
        "  Examples of QIDP-approved drugs:\n"
        "    ceftolozane-tazobactam (2014)\n"
        "    ceftaz-avibactam (2015)\n"
        "    meropenem-vaborbactam (2017)\n"
        "    plazomicin (2018)\n"
        "    cefiderocol (2019)\n"
        "    sulbactam-durlobactam (2023)\n"
        "    aztreonam-avibactam (2024)\n\n"
        "PRV (Priority Review Voucher):\n"
        "  Tropical disease + pediatric rare disease vouchers — can sell on secondary "
        "market for $50-150M. NOT applicable to most antibacterials.\n\n"
        "BREAKPOINT SETTING (clinical interpretation of MIC):\n"
        "  EUCAST (Europe):\n"
        "    Annual updates at eucast.org\n"
        "    Categories: S / I (susceptible-increased exposure) / R\n"
        "    Set based on PK/PD + ECOFF + clinical outcome data\n"
        "  CLSI (US):\n"
        "    Clinical and Laboratory Standards Institute\n"
        "    M100 document updated annually\n"
        "    Categories: S / I (intermediate) / R\n"
        "  Differences:\n"
        "    EUCAST tends to be more conservative (tighter S threshold)\n"
        "    CLSI sometimes higher S (e.g., vancomycin S. aureus historical issue)\n\n"
        "POST-MARKETING SURVEILLANCE:\n"
        "  Required by FDA for new antibacterials: track resistance emergence + clinical outcomes\n"
        "  CDC ARLN (Antibiotic Resistance Laboratory Network) handles US surveillance\n"
        "  WHO GLASS handles global surveillance\n\n"
        "DECISION: design candidates targeting QIDP-eligible pathogens (we cover 8); plan for LPAD pathway given small target populations + high unmet need."
    )
    return {"task": "teacher_core_regulatory",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# S. Audited numbers
# ============================================================================
def trace_audited_numbers(rng: random.Random) -> dict:
    queries = [
        ("How many rows are in pro-v7?",
         "Pro-v7 has 319,229 train + 19,546 valid + 50 test = 338,825 total rows.\n"
         "  - 308,282 train rows from cleaned pro-v5 (after deep audit cleanup)\n"
         "  - 4,768 chem teacher-distill rows (Designer↔Critic loops)\n"
         "  - 6,179 systems-level teacher-distill rows (13 categories)\n"
         "(Architecture distillation will be added in pro-v8.)"),
        ("How many cleaned chemistry rows do we have?",
         "39,590 cleaned rows total in known-antibiotics-canonical.parquet:\n"
         "  - 30,743 small molecules\n"
         "  - 8,847 peptides (recovered via Chem.MolFromSequence from one-letter sequences)\n"
         "  - 158 dropped (unconvertible / invalid SMILES)\n"
         "Source breakdown of cleaned chemistry:\n"
         "  ChEMBL:      13,809\n"
         "  NPAtlas:     13,218\n"
         "  DrugCentral:  3,716\n"
         "  + 8,847 peptide actives (DRAMP/DBAASP recovered)"),
        ("What's the stereo-state distribution in our chemistry corpus?",
         "Stereo state distribution (from cleanup of known-antibiotics-canonical):\n"
         "  achiral:    11,076 (no chiral centers)\n"
         "  peptide:     8,847 (separated to peptide-actives)\n"
         "  partial:     6,650 (some stereo defined, some not)\n"
         "  defined:     6,514 (all chiral centers defined)\n"
         "  undefined:   6,503 (chiral centers exist but not assigned)\n"
         "Pre-cleanup, ~20% of corpus had silent undefined stereo — now flagged."),
        ("How many tasks are in pro-v7?",
         "Pro-v7 has 119 task buckets in train. Top 10 by row count:\n"
         "  name_to_smiles               114,906\n"
         "  coadd_screen                  38,895\n"
         "  natural_product_origin        27,655\n"
         "  name_to_inchi                 15,100\n"
         "  name_to_synonyms              13,021\n"
         "  name_to_cas                   11,655\n"
         "  cas_to_name                   10,524\n"
         "  admet_panel                    8,931\n"
         "  smiles_generation_pathogen     6,071\n"
         "  tox_panel                      5,062"),
        ("How many teacher-distillation traces total?",
         "Total: 21,500 teacher-distillation traces across 3 layers\n"
         "  Chem (5,000):    Designer↔Critic loops, 14 (pathogen, target) combos\n"
         "  Systems (6,500): 13 categories — Strategist campaign, tool orchestration, "
         "multi-pathogen spectrum, failure-mode debug, constraint compliance, wet-lab "
         "handoff, resistance forecasting, combo therapy, clinical positioning, "
         "manufacturing, literature grounding, confidence calibration, workbench state\n"
         "  Architecture (10,000): 20 categories — agent roles (Designer/Critic/"
         "Strategist/Editor), handoff protocol, tool registry, decision tree, ledger, "
         "state machine, stage gates, intervention, error escalation, branch/merge, "
         "pipeline map, subagent dispatcher, confidence convention, error codes, "
         "system self-description, API contracts, sprint planning"),
        ("How many ChEMBL records do we have, broken down by pathogen?",
         "ChEMBL records by pathogen (after std_types widening to 8):\n"
         "  Mtb:        4,236   (TB-Alliance + Foundation funding skews)\n"
         "  EColi-CRE:  3,955\n"
         "  MRSA:       3,091\n"
         "  Paer:       2,807\n"
         "  KpneuCRE:   2,559\n"
         "  VRE:        2,426\n"
         "  Abaum:      1,618\n"
         "  NGono:        591   (smallest — under-represented in clinical literature)\n"
         "Total: 21,283 ChEMBL records"),
        ("How many tools does Lysos have?",
         "25 tools across 6 categories:\n"
         "  amr (5):        predict_mic_pathogen, get_pathogen_resistome, "
         "check_resistance_genes, predict_resistance_escape, find_active_against_mdr\n"
         "  scoring (6):    predict_admet, predict_hemolysis, predict_synthesis_route, "
         "estimate_synth_cost, score_molecule, find_similar_drugs\n"
         "  structural (3): dock_against_target, predict_binding_affinity, "
         "predict_complex_structure\n"
         "  generative (4): propose_pocket_aware, scaffold_hop, transform_structure, "
         "optimize_iteratively\n"
         "  knowledge (5):  compare_molecules, explain_mechanism, find_target_structure, "
         "get_drug_history, search_literature\n"
         "  sandbox (2):    execute_python, render_3d_scene"),
        ("How many reward components in Stage 3 GRPO?",
         "12 reward components, weights sum to 1.0:\n"
         "  validity              0.05  (RDKit parse + sanitize)\n"
         "  structural_alerts     0.05  (PAINS + Brenk + Lipinski + Veber)\n"
         "  predicted_mic         0.20  (XGBoost MIC predictor)\n"
         "  drug_likeness_qed     0.10\n"
         "  synthesizability      0.10  (SA score)\n"
         "  hemolysis_safety      0.10\n"
         "  novelty               0.08  (Tanimoto vs known corpus)\n"
         "  embedding_novelty     0.07  (EmbeddingGemma cosine)\n"
         "  boltz2_pose_conf      0.10  (3D pose ipTM cache)\n"
         "  spectrum_breadth      0.05  (active vs ≥3 priority pathogens)\n"
         "  resistance_robustness 0.05  (heuristic mech-evasion)\n"
         "  pareto_entry          0.05  (frontier-exploration bonus)"),
        ("How many priority pathogens does Lysos cover?",
         "8 WHO-priority pathogens:\n"
         "  CRITICAL tier: Mtb, EColi-CRE, KpneuCRE, Abaum\n"
         "  HIGH tier:     MRSA, Paer, VRE, NGono\n"
         "Each pathogen has: 1-3 mapped PDB targets, full resistome briefing, "
         "first-line therapy reference, scaffold class anchors."),
        ("What's the train/valid/test split convention?",
         "95/5 train/valid for synthetic data (random). Test split is RESERVED for "
         "held-out canary evaluation: 50 hand-curated rows (named-drug-test_split.jsonl) "
         "with split='test' baked in. The cleanup pipeline NEVER touches test rows. "
         "Cross-split leak audit: 0 leakage of test prompts into train/valid."),
    ]
    q, a = rng.choice(queries)
    user = q
    asst = f"[Audited Numbers]:\n\n{a}\n\nDECISION: these are the actual numbers in our dataset as of pro-v7."
    return {"task": "teacher_audited_numbers",
            "query": q,
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# T. Data provenance
# ============================================================================
def trace_data_provenance(rng: random.Random) -> dict:
    user = "How is each row in pro-v7 traceable back to its source?"
    asst = (
        "[Data Provenance]:\n\n"
        "Every row in pro-vN carries provenance metadata so we can trace failures "
        "back to source data + verify reproducibility.\n\n"
        "PER-ROW METADATA:\n"
        "  task:     the task type (e.g., 'mic_prediction', 'teacher_distill', "
        "'natural_product_origin', 'safety_refusal')\n"
        "  pathogen: optional pathogen field (None for generic chemistry tasks; "
        "primer applied at builder time)\n"
        "  split:    'train' | 'valid' | 'test'\n"
        "  messages: serialized JSON list of {role, content} chat turns\n\n"
        "SOURCE TRACEABILITY:\n"
        "  Task name encodes the pipeline that produced it:\n"
        "    name_to_smiles                — DrugBank + DrugCentral vocabulary\n"
        "    natural_product_origin        — NPAtlas\n"
        "    coadd_screen                  — CO-ADD primary screen + dose-response\n"
        "    mic_prediction                — ChEMBL MIC measurements\n"
        "    admet_panel / tox_panel       — TDC ADMET/Tox benchmarks\n"
        "    drug_likeness                 — TDC drug-likeness derivative\n"
        "    safety_refusal                — agentic synthesis (v6 audit fix)\n"
        "    tool_arg_validation           — agentic synthesis (v6 audit fix)\n"
        "    held_out_eval                 — manual curation (v6 audit fix)\n"
        "    teacher_distill / teacher_*   — manual teacher distillation (v6+ inline)\n"
        "    activity_cliff                — mmpdb-style mining\n"
        "    decoy_negative                — DUD-E generated\n"
        "    smiles_aug                    — randomization of base task\n"
        "    long_form_designer_loop       — synth_long_form_traces.py\n"
        "    pk_panel                      — DrugBank PK extraction\n"
        "    tool_call_with_result         — synth_tool_results.py\n\n"
        "DATASET MANIFEST:\n"
        "  data/processed/MANIFEST.json contains:\n"
        "    git_sha:           commit at build time\n"
        "    sdk_versions:      rdkit, datasets, transformers, torch, trl, peft, etc.\n"
        "    datasets:          per-dataset content hash (SHA-256, 16 chars)\n"
        "    reward_stack:      Stage 3 reward components + weights\n"
        "  Generated by scripts/build_dataset_manifest.py.\n"
        "  Embedded into model card on push for full provenance.\n\n"
        "VERSION TRAIL:\n"
        "  pro-v1   raw                   (leaky superset)\n"
        "  pro-v2   pro v1 + named-drug elite CoT\n"
        "  pro-v3   pro v2 + 32 agentic gaps + safety/refusal/tool-arg/held-out\n"
        "  pro-v4   pro v3 + tool-call-results + long-form-traces + pk-panel + decoys + activity-cliffs + smiles-aug + pathogen-primer + canonical-chemistry\n"
        "  pro-v5   pro v4 cleaned (5 audit issues fixed)\n"
        "  pro-v6   pro v5 + 3K chem teacher\n"
        "  pro-v7   pro v5 + 5K chem teacher + 6.5K systems teacher\n"
        "  pro-v8   pro v5 + 5K chem + 6.5K systems + 10K architecture + 8K raw-data/core\n\n"
        "REPRODUCIBILITY:\n"
        "  Given (git_sha, dataset_hash, reward_stack_version), the same input+training "
        "config will produce the same model output.\n"
        "  The manifest captures all three, so any reported metric is reproducible.\n\n"
        "DECISION: provenance is non-negotiable; every row is traceable back to its source pipeline + git commit."
    )
    return {"task": "teacher_data_provenance",
            "messages": [{"role": "system", "content": SYS},
                          {"role": "user", "content": user},
                          {"role": "assistant", "content": asst}]}


# ============================================================================
# Driver
# ============================================================================
GENERATORS = {
    "source_chembl":         trace_source_chembl,
    "source_drugbank":       trace_source_drugbank,
    "source_npatlas":        trace_source_npatlas,
    "source_dbaasp_dramp":   trace_source_amp_databases,
    "source_drugcentral":    trace_source_drugcentral,
    "source_card":           trace_source_card,
    "source_pdb":            trace_source_pdb,
    "source_zinc_pubchem":   trace_source_zinc_pubchem,
    "source_tdc":            trace_source_tdc,
    "source_coadd":          trace_source_coadd,
    "core_sar":              trace_core_sar,
    "core_mic_methodology":  trace_core_mic,
    "core_resistance":       trace_core_resistance,
    "core_pkpd":             trace_core_pkpd,
    "core_admet":            trace_core_admet,
    "core_3d_structure":     trace_core_3d_structure,
    "core_synthesis":        trace_core_synthesis,
    "core_regulatory":       trace_core_regulatory,
    "audited_numbers":       trace_audited_numbers,
    "data_provenance":       trace_data_provenance,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_per_category", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0xBADCAFE)
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

    print(f"\nGenerated {n_total:,} raw-data + core + audited-numbers traces")
    for k, v in counts.items():
        print(f"  {k:25s} {v}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
