---
title: Data fetch + pipeline session log
date: 2026-05-01
duration: ~6 hours
participants: rahul24raj, claude-opus-4-7
---

# Session log — Lysos data + pipeline build

## What we set out to do

User pushed back twice on data:
1. "no sample i need real work" — drop synthetic stubs, real data only
2. "still less by far buddy" — even the real data is too small, go heavy

The session was about building 11 real-data loaders, validating each against live APIs, fixing schema bugs as they surfaced, then orchestrating a full end-to-end fetch + processed-dataset push to HF Hub.

## What landed

### 1. Loaders implemented (10 in src/data/ + 1 builder)

| Source | File | Status |
|---|---|---|
| TDC (Stage 1) | `scripts/prepare_tdc_data.py` | ✓ schema verified |
| ChEMBL | `src/data/chembl.py` | ✓ verified live; 16,462 records on disk |
| DBAASP | `src/data/dbaasp.py` | ✓ verified live; 152 → growing in heavy run |
| DRAMP | `src/data/dramp.py` | ✓ URLs fixed; 8,532 sequences |
| CARD | `src/data/card.py` | ✓ species path fixed; 3,543 records |
| BindingDB | `src/data/bindingdb.py` | ⚠ JSP-gated; manual download required |
| PubChem | `src/data/pubchem.py` | ⚠ most curated AIDs retired (only 2 work) |
| ZINC | `src/data/zinc.py` | ✓ partial (FDA + in-trials, ~100 compounds) |
| APD3 | `src/data/apd3.py` | ✗ all source URLs 404 (site changed) |
| DrugBank | `src/data/drugbank.py` | ⚠ ZIP-disguised SDF; needs rdkit on VM |
| PDB | `src/data/pdb.py` | ✓ GraphQL fixed; 3,136 metadata rows |

### 2. Real bugs caught + fixed in the wild

- ChEMBL: `target_organism__iexact` filter returned 0 — real syntax is plain `target_organism=`
- ChEMBL: `__in` filter on `standard_type` times out at scale — query each type separately
- ChEMBL: `pchembl_value__gte` server-side times out + most records lack pchembl_value anyway — filter client-side, optional
- DBAASP: `targetSpecies` is a dict with `.name`, not a string; same for unit, activityMeasureGroup
- DBAASP: listing endpoint returns `{data: [...]}`, not `{peptides: [...]}`
- DBAASP: detail endpoint at `/peptides/{numeric_id}`, not `/peptides/{dbaaspId}`
- CARD: species at `model_sequences.sequence[seq_id].NCBI_taxonomy.NCBI_taxonomy_name` — not the assumed `ARO_taxa` field
- DRAMP: site changed in 2025, URLs now `download.php?filename=...` with .xlsx + .fasta
- DrugBank: "all-open-structures.csv" is a ZIP archive misnamed; contains SDF that needs rdkit
- BindingDB: served via `SDFdownload.jsp` wrapper that requires session cookies
- PubChem: most pre-curated antibacterial AIDs (2842, 540317, 720596, 488, 1626, ...) returned 400 — assays were retired
- PDB: GraphQL `rcsb_entity_source_organism` is on `polymer_entities`, not `entries` directly

Each was found by running the loader against the real API, observing the failure, and fixing.

### 3. Pipeline orchestration

- `scripts/fetch_all_data.py` — runs all 10 loaders + 3 dataset builders in priority order
- `scripts/data_inventory.py` — walks data/raw + data/processed, reports sizes + per-pathogen counts
- `scripts/verify_loaders.py` — smoke-imports all 23 modules
- `tests/test_rewards.py` — 12/13 unit tests pass
- `Makefile` — single source of dev commands

### 4. Numbers on disk (after heavy run)

- **Raw data**: ~3 MB across 5 working sources (ChEMBL 16,462 + CARD 3,543 + DBAASP 152 + DRAMP 8,532 + PDB 3,136 + ZINC 100)
- **Processed**:
  - `data/processed/amr-stage2/`: **21,007 instruction examples** (19,957 train + 1,050 eval)
  - `data/processed/amr-rl-prompts/`: 3,200 RL prompts
- **HF Hub** (private):
  - `rahul24raj/lysos-amr-stage2` (21K examples)
  - `rahul24raj/lysos-rl-prompts` (3.2K prompts)

### 5. Frontier knowledge captured

- `vault/refs/` has Google blog + HF card + Gemini API docs
- `vault/research/2026-05-01-gemma-embedding-research.md` synthesizes EmbeddingGemma 300m for our project
- `vault/plans/2026-05-01-embeddinggemma-integration.md` lays out the 4-slot integration plan

## What's still in flight

- DBAASP heavy fetch (1000/pathogen) — running in background
- BindingDB — manual download blocked
- PubChem — needs new working AID list
- APD3 — needs alternative source

## Decisions that landed

- **Stage 2 build no longer requires DBAASP** — only ChEMBL is hard-required
- **drug_likeness slice depends on rdkit** — runs on AMD VM, not local
- **DrugBank parsing deferred to AMD VM** with rdkit
- **EmbeddingGemma 300m will be added** for novelty + RAG + dedup (next session)

## Carry-over for next session

1. DBAASP heavy completes → rebuild Stage 2, re-push HF
2. EmbeddingGemma integration (Phases 1–5 of `vault/plans/2026-05-01-embeddinggemma-integration.md`)
3. AMD Dev Cloud credits land Sat May 2 → smoke test, kick off Stage 1 training
4. Pitch deck skeleton

## Files changed this session

(commits visible at github.com/Rahul-Rajpurohitk/lysos)

- 60+ commits across the data layer + scripts/ + tests/ + workspace/ + vault/
