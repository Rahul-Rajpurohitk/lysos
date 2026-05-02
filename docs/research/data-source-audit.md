# Lysos Data Source Audit + Research

**Date**: 2026-05-02
**Status**: Pre-kickoff (May 4) data ingestion review
**Current corpus**: 273,600+ examples on HF Hub (`rahul24raj/lysos-amr-stage2-pro`)

## Current Raw Data Inventory (~116K rows total)

| Source | Rows | Notes |
|--------|------|-------|
| ChEMBL antibiotics (canonical) | 21,283 | MIC/IC50 with standardized SMILES, primary chemistry |
| NPAtlas (canonical) | 36,434 | Natural products — biggest single source by rows |
| DrugBank with SMILES | 14,630 | 96.1% SMILES resolution rate |
| Wikipedia AMR | 13,800 | Mechanism + history + indication text |
| DRAMP AMPs (canonical) | 8,532 | Antimicrobial peptide database |
| DBAASP AMPs (canonical) | 6,256 | Antimicrobial peptide structures + activity |
| PubMed AMR v2 | 4,197 | Recent abstracts (extended sweep) |
| DrugCentral (canonical) | 3,930 | Drug-target interactions, indications |
| PDB AMR targets | 3,157 | Crystal structures of bacterial targets |
| PubMed AMR v1 | 2,346 | Initial abstracts pull |
| PubChem antibacterial | 1,268 | NCBI bioassay subset |
| OpenFDA labels | 78 | 44 with mechanism text |
| ChEMBL mechanisms | 59 | Bacterial-target-filtered MoA |
| **TOTAL** | **115,970 rows** | |

## High-Value MISSING Sources (priority-ranked)

### 1. CO-ADD (Community for Open Antimicrobial Drug Discovery) — TOP PRIORITY
- **URL**: https://db.co-add.org/downloads
- **Size**: ~2.1 MILLION data points (10-20× larger than ChEMBL antibiotics subset)
- **Format**: CSV + SDF, free download (registration required)
- **Coverage**: Free screening of submitted compounds against:
  - 5 priority pathogens (E. coli, K. pneumoniae, A. baumannii, P. aeruginosa, S. aureus)
  - + 2 fungi (C. albicans, C. neoformans)
- **Why ingest**: Dramatically expands chemistry diversity for SFT + provides massive scaffold-CV training material. Compounds DON'T overlap with ChEMBL much (CO-ADD takes academic research compounds, ChEMBL takes published patents).
- **Cost**: Free, but rate-limited downloads
- **Action**: Add `src/data/coadd.py` loader, ingest into Stage 2

### 2. TDC (Therapeutics Data Commons) — HIGH PRIORITY
- **URL**: https://tdcommons.ai
- **Datasets**: 66 AI-ready datasets across 22 tasks
- **AMR-relevant**:
  - SAH single-cell antibacterial
  - Resistance prediction tasks
  - ADMET datasets (we'd benefit from hERG, PAMPA, Caco-2 etc.)
  - Property prediction benchmarks
- **Format**: Python `pyTDC` package, one-line loaders
- **Why ingest**: Provides STANDARDIZED BENCHMARKS — useful for evaluating Lysos against published baselines. ALSO provides ADMET data that complements safety reward.
- **Action**: Add `src/data/tdc.py`, run benchmark eval on Stage 1/Stage 2 models

### 3. WHO 2024 Antimicrobial Lists — STEWARDSHIP DATA
- **URL**: https://cdn.who.int/media/docs/default-source/gcp/who-mia-list-2024-lv.pdf
- **Content**: WHO Medically Important Antimicrobials list (categorized by importance + usage class)
- **Why ingest**: Provides STEWARDSHIP CONTEXT — model can learn that CARBAPENEM-LAST-RESORT vs PENICILLIN-FIRST-LINE has different prescription consequences
- **Action**: PDF parse → JSONL with drug class + WHO category

### 4. CARB-X 2024 Pipeline Analysis — UNMET NEED CONTEXT
- **URL**: https://carb-x.org/wp-content/uploads/2024/10/PIIS266652472400260X.pdf
- **Content**: WHO 2023 antibacterial clinical pipeline analysis — what's in Phase I/II/III
- **Why ingest**: Tells the model what pathogens have UNMET clinical need (CRAB, NDM-positive Enterobacterales, etc.)
- **Action**: PDF parse → reasoning seeds for "where to focus generation"

### 5. Recent FDA Approvals (2023-2025) — NOT YET IN CORPUS
| Drug | Year | Indication | In our corpus? |
|------|------|-----------|----------------|
| Sulbactam-Durlobactam (Xacduro) | 2023 | CRAB pneumonia | NO — needs adding |
| Aztreonam-Avibactam (Emblaveo) | 2024 (EU) | NDM+ESBL Enterobacterales | NO |
| Gepotidacin (Blujepa) | 2025 | Uncomplicated gonorrhea + UTI | Mentioned in NBTI batch |
| Ceftobiprole (Zevtera) | 2024 (US) | Anti-MRSA cephalosporin | Mentioned in CoT |
| Tedizolid (Sivextro) | 2014 | MRSA SSTI (oxazolidinone) | Mentioned in linezolid CoT |
- **Action**: Add SMILES + mechanism to Stage 2 + dedicated CoT examples

### 6. EUCAST Clinical Breakpoints — INTERPRETATION DATA
- **URL**: https://www.eucast.org/clinical_breakpoints
- **Content**: Standardized MIC breakpoints for "Susceptible / Intermediate / Resistant" interpretation across all major antibiotics × pathogens
- **Why ingest**: Tells model how to convert raw MIC into clinical SUSCEPTIBLE/RESISTANT classification — critical for clinically-actionable generation
- **Action**: Scrape into JSONL (drug × pathogen → S/I/R breakpoints)

### 7. AMR-for-R Drug Database — STANDARDIZED CLASSIFICATION
- **URL**: http://amr-for-r.org/reference/antimicrobials.html
- **Content**: 625 drugs with ATC codes, ATC groups, defined daily doses
- **Why ingest**: Provides standardized drug class taxonomy that complements raw drug names
- **Action**: Cross-reference with our drug names, normalize class labels

### 8. CAMP3 / ADAM Antimicrobial Peptide Databases — AMP EXPANSION
- **CAMP**: http://www.camp3.bicnirrh.res.in (3,200+ AMPs with activity data)
- **ADAM**: http://bioinformatics.cs.ntou.edu.tw/adam (~7,000 AMPs)
- **Why ingest**: We have DBAASP (6,256) + DRAMP (8,532) + APD3 cache, but CAMP/ADAM have UNIQUE entries
- **Action**: Add loaders, dedupe by sequence

### 9. TB Alliance Compound Library — TB-SPECIFIC
- **URL**: https://www.tballiance.org/research/portfolio
- **Content**: Compounds in TB Alliance pipeline — bedaquiline, pretomanid, sutezolid, BPaL components, novel candidates
- **Why ingest**: TB is one of our 8 priority pathogens; TB Alliance has the deepest pipeline
- **Action**: Scrape + ingest as targeted Mtb compound set

### 10. NPAtlas Updates + COCONUT — NATURAL PRODUCTS
- **NPAtlas**: We have 36K rows (May 2025 snapshot); regular updates
- **COCONUT**: https://coconut.naturalproducts.net (~410K NPs, broader than NPAtlas)
- **Action**: Refresh NPAtlas, consider COCONUT subset for known antimicrobials

## Lower-Priority but Worth Tracking

- **BV-BRC** (Bacterial Bioinformatics Resource Center) — genomic + AMR gene context
- **NCBI Pathogen Detection** — surveillance data for emerging resistance
- **CDC NARMS** — surveillance data
- **PathOSA** — clinical isolate MIC data
- **arXiv/bioRxiv** — preprints on AMR (too noisy without curation)
- **IUPHAR/BPS** — pharmacology DB (more drug-target than AMR-specific)

## Action Plan (Pre-Kickoff)

### Tier 1 — DO BEFORE MAY 4 KICKOFF
1. **Continue teacher CoT batches** — proven pipeline, 2,193 seeds remaining (current cursor 193/2,386)
2. **Ingest CO-ADD** — biggest single value-add for Stage 2 (write `src/data/coadd.py`)
3. **Recent FDA approvals as targeted CoT** — sulbactam-durlobactam, aztreonam-avibactam, ceftobiprole, gepotidacin, tedizolid — 5 named-drug mechanism dives

### Tier 2 — DURING HACKATHON (May 4-10)
4. **Stage 3 RL setup** — verifiable rewards (already have safety reward + ML MIC predictor + structural-alert reward)
5. **EUCAST breakpoints** — for clinical interpretation
6. **WHO stewardship data** — for class-specific prescription context
7. **TDC benchmarks** — evaluate Lysos vs published baselines

### Tier 3 — POST-HACKATHON / PAPER PHASE
8. **CAMP/ADAM AMP expansion** — for AMP track
9. **COCONUT NP filtering** — broader natural products
10. **TB Alliance specific dataset** — TB track refinement

## On Token Strategy

Per user direction: **No Gemini embedder pivot.** Continue using Claude (me) for:
- Teacher CoT generation (current pipeline, ~150-300K tokens/batch session)
- Reasoning generation
- Future reward model training data

User has Claude Code subscription (already paid) — token usage is sunk cost. Avoid spending on external embedder APIs unless absolutely needed.

## Decision: Continue Strategy

**Primary track**: Keep grinding teacher CoT batches (currently 193/2,386 = 8.1% processed). Each batch adds ~16-20K tokens of high-quality reasoning.

**Parallel track**: Ingest CO-ADD as the highest-value missing data source. Should be a 2-4 hour engineering task (write loader + canonicalize SMILES + scaffold-aware split + merge into Stage 2 pro).

**Stage 3 RL**: Reward model components already wired. Hackathon Day 1 (May 4) should focus on:
- Cloud GPU smoke test (rocm/vllm:latest on MI300X)
- Stage 1 TxGemma-4 base training launch
- Stage 2 SFT plan finalization
