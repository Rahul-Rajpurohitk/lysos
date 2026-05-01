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

## Source-by-source (status = 2026-05-01)

### Small molecules

| Source | Loader | API style | Live rows | Status |
|---|---|---|---|---|
| **ChEMBL** | `src/data/chembl.py` | REST (paginated) | **16,462** | ✅ verified live; widened to 8 standard_types in May-01 commit (test pull yielded +19-55%) |
| **DrugBank** | `src/data/drugbank.py` | open vocabulary CSV (ZIP) | **14,630** | ✅ verified live; vocab CSV path fixed May-01 (was failing on ZIP magic-bytes); structures SDF needs rdkit on VM |
| **ZINC** | `src/data/zinc.py` | bulk SMI files | 100 | ⚠ partial — only `fda` + `in-trials` subsets pulled |
| **BindingDB** | `src/data/bindingdb.py` | bulk TSV stream | 0 | ⚠ JSP-gated (`/access` page returns HTML, not the file) — manual download required |
| **PubChem** | `src/data/pubchem.py` | PUG REST | 0 | ⚠ most curated AIDs (2842, 540317, 720596, 488, 588352, 1626, 2098) retired by NCBI; only 1853, 1958 still active. Eutils search returns ~30 candidates per pathogen but they're small (<100 actives each) |

### Antimicrobial peptides

| Source | Loader | API style | Live rows | Status |
|---|---|---|---|---|
| **DBAASP** | `src/data/dbaasp.py` | REST listing + per-peptide detail | **6,256** | ✅ verified live; nested-dict schema fix applied; µM → µg/mL via peptide-MW computation |
| **DRAMP** | `src/data/dramp.py` | ZIP/XLSX downloads | **8,532** | ✅ verified live; `download.php?filename=...` path fix applied |
| **APD3** | `src/data/apd3.py` | bulk export | 0 | ❌ source URLs all 404 (site reorganized); mirror search pending |

### Targets / context

| Source | Loader | API style | Live rows | Status |
|---|---|---|---|---|
| **CARD** | `src/data/card.py` | bulk tarball + ARO ontology | **3,543** | ✅ verified live; species-path fix applied (`model_sequences.sequence[seq_id].NCBI_taxonomy.NCBI_taxonomy_name`) |
| **PDB** | `src/data/pdb.py` | RCSB Search + GraphQL | **3,136** | ✅ verified live; GraphQL schema fix applied (`polymer_entities[].rcsb_entity_source_organism[]`) |
| **TDC** | `scripts/prepare_tdc_data.py` | PyTDC builders | (runs on VM) | needs `PyTDC>=1.1.0` installed; runs from VM after `pip install -e .` |

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
2. **`scripts/prepare_amr_data.py`** — build the Stage 2 SFT dataset from raw CSVs.
   Currently produces **96,975 examples** across 9 task types.
3. **`scripts/prepare_stage3_prompts.py`** — build the 3,200-prompt RL set.
4. **`scripts/build_known_antibiotics_index.py`** — build the 20,489-row reference
   index used by EmbeddingGemma novelty + RAG + similar-drugs UI.
5. **`scripts/dedup_with_embeddings.py`** — (optional, VM-side) cluster Stage 2
   examples by semantic similarity, drop near-duplicates.
6. **`scripts/data_inventory.py`** — report what's on disk + per-pathogen counts.
7. **Push to HF Hub**: `--push-to-hub` on the prepare scripts pushes the 3 processed
   datasets (TDC Stage 1 — VM-side, AMR Stage 2 — LIVE, RL Stage 3 prompts — LIVE).

## Dataset sizes (real, post-DrugBank wiring)

| Dataset | Rows | HF Hub | Last updated |
|---|---|---|---|
| `data/processed/amr-stage2/{train,valid}` | 92,127 + 4,848 | [`rahul24raj/lysos-amr-stage2`](https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2) (live) | 2026-05-01 |
| `data/processed/amr-rl-prompts/{train,valid}` | 3,072 + 128 | [`rahul24raj/lysos-rl-prompts`](https://huggingface.co/datasets/rahul24raj/lysos-rl-prompts) (live) | 2026-05-01 |
| `data/processed/known_antibiotics_index.parquet` | 20,489 | (local — RAG / novelty) | 2026-05-01 |
| `data/processed/tdc-stage1/` | TBD | `rahul24raj/lysos-tdc-stage1` (reserved) | runs on VM |

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
