# Lysos data pipeline

A reference for the end-to-end flow from public APIs to Stage-2 ready training data.

```
                            ┌───────────────────────────────────────┐
                            │           PUBLIC SOURCES (10)         │
                            └───────────────────────────────────────┘

   ZINC      APD3      CARD     DRAMP    DrugBank   ChEMBL   DBAASP   PubChem   BindingDB   PDB
     │         │         │         │         │         │        │         │           │        │
     ▼         ▼         ▼         ▼         ▼         ▼        ▼         ▼           ▼        ▼
   ╭─────────────────────────────────────────────────────────────────────────────────────────╮
   │                              src/data/<source>.py                                         │
   │   - Cache to data/raw/<source>_cache/                                                     │
   │   - Normalize schema                                                                       │
   │   - Filter to AMR pathogens (8 priority targets)                                          │
   │   - Output CSV / JSON to data/raw/                                                         │
   ╰─────────────────────────────────────────────────────────────────────────────────────────╯
                                            │
                                            ▼
                            ┌───────────────────────────────────────┐
                            │         data/raw/*.csv (~1-2 GB)       │
                            └───────────────────────────────────────┘
                                            │
                              ┌─────────────┼─────────────┐
                              ▼             ▼             ▼
                  ┌───────────────────────────────────────────────┐
                  │   prepare_tdc_data.py (Stage 1 — TxGemma-4)   │
                  │   prepare_amr_data.py (Stage 2 — AMR SFT)     │
                  │   prepare_stage3_prompts.py (Stage 3 — RL)    │
                  └───────────────────────────────────────────────┘
                                            │
                                            ▼
                            ┌───────────────────────────────────────┐
                            │     data/processed/*  (~600 MB)        │
                            │     HF Datasets on disk + on Hub       │
                            └───────────────────────────────────────┘
                                            │
                                            ▼
                            ┌───────────────────────────────────────┐
                            │   Training (AMD MI300X)                │
                            │   Stage 1 → TxGemma-4                  │
                            │   Stage 2 → Lysos-base                 │
                            │   Stage 3 → Lysos-RL (final)           │
                            └───────────────────────────────────────┘
```

## Source-by-source

### Small molecules

| Source | Loader | API style | What we extract |
|---|---|---|---|
| **ChEMBL** | `src/data/chembl.py` | REST (paginated) | bacterial activity records (MIC/MBC/IC50/Ki) — SMILES + value + units, normalized to `mic_log_ug_per_ml` |
| **BindingDB** | `src/data/bindingdb.py` | bulk TSV download (streaming) | bacterial-target binding affinities (Ki/Kd/IC50/EC50) |
| **PubChem** | `src/data/pubchem.py` | PUG REST | curated antibacterial bioassay panels (AID lists), active compounds + SMILES |
| **DrugBank** | `src/data/drugbank.py` | open data CSVs | drug knowledge: SMILES, name, indication |
| **ZINC** | `src/data/zinc.py` | bulk SMI files | drug-like / FDA / investigational SMILES (chemistry prior) |

### Antimicrobial peptides

| Source | Loader | API style | What we extract |
|---|---|---|---|
| **DBAASP** | `src/data/dbaasp.py` | REST listing + per-peptide detail | sequence + per-strain MIC + hemolysis (with µM → µg/mL conversion via computed peptide MW) |
| **APD3** | `src/data/apd3.py` | bulk export + GitHub mirror | curated AMP sequences + activity free-text |
| **DRAMP** | `src/data/dramp.py` | ZIP downloads | ~22K AMPs across General/Patent/Clinical sets |

### Targets / context

| Source | Loader | API style | What we extract |
|---|---|---|---|
| **CARD** | `src/data/card.py` | bulk tarball + ARO ontology | resistance gene catalog: gene name, drug class, mechanism, pathogen |
| **PDB** | `src/data/pdb.py` | RCSB Search + GraphQL | protein structure metadata for AMR pathogens, ligand SMILES per entry |

## Standard schemas

All small-molecule loaders output the same row shape so they can be
concatenated:

```
smiles, pathogen_short, mic_log_ug_per_ml, name, chembl_id,
standard_type, standard_value, standard_units, pchembl_value,
target_organism
```

All AMP loaders share:

```
sequence, pathogen_short, target_organism, hemolytic_int,
source, mic_ug_per_ml, length, name, dbaasp_id
```

Where a source doesn't have a field, it's left null.

## AMR pathogen short codes

| Short | Full name | Why on the priority list |
|---|---|---|
| `MRSA` | Staphylococcus aureus (MRSA) | Hospital-acquired, blood + skin + bone infections |
| `Mtb` | Mycobacterium tuberculosis | 1.5M deaths/yr; MDR/XDR strains need new classes |
| `EColi-CRE` | Escherichia coli (ESBL+ / CRE) | Bloodstream + UTI, often untreatable |
| `KpneuCRE` | Klebsiella pneumoniae (CRE) | WHO highest priority, mortality up to 50% |
| `Abaum` | Acinetobacter baumannii | ICU pneumonia, often pan-resistant |
| `Paer` | Pseudomonas aeruginosa | Intrinsically resistant, leading CF lung infection |
| `VRE` | Enterococcus faecium / faecalis | Bloodstream + endocarditis |
| `NGono` | Neisseria gonorrhoeae | Drug-resistant gonorrhea verge of untreatability |

## Run order

1. **`scripts/fetch_all_data.py`** — orchestrator that runs all 10 loaders + builders.
   Cheap/fast loaders first, expensive last.
2. **`scripts/data_inventory.py`** — report what's actually on disk + per-pathogen counts.
3. **Push to HF Hub**: `--push-to-hub` flag on the orchestrator pushes the 3 processed
   datasets (TDC Stage 1, AMR Stage 2, RL Stage 3 prompts).

## Caching strategy

Each loader writes its raw output to `data/raw/<source>.csv`. If that file exists,
the loader treats it as cached and does NOT refetch unless `--refresh` is passed.

Bulk-download loaders (DRAMP, BindingDB, CARD, ZINC) also cache the downloaded
zip/tarball under `data/raw/<source>_cache/` so a re-parse doesn't re-download.

`scripts/fetch_all_data.py` respects this — failing late steps don't invalidate
earlier successful ones.

## Privacy / licensing

All sources are open-license, public-domain, or research-use:

- ChEMBL: CC-BY-SA 3.0
- DBAASP: free academic + commercial
- APD3: free academic
- DRAMP: free academic
- CARD: open data (ARO ontology MIT-licensed)
- BindingDB: open release
- PubChem: U.S. Government public domain
- ZINC: open
- DrugBank Open Data: CC0 / CC-BY-NC (varies by file)
- PDB: open

No proprietary or DUA-gated data is in the pipeline.
