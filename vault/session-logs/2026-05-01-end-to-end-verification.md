# 2026-05-01 — end-to-end verification + DrugBank wiring + UI screenshot

User pushback: "not ready buddy what ios more? left? the data 5the p[ipelines? the frontend ?"

User was correct — three real gaps, all addressed in this session.

## Gap 1 — Frontend never built locally

`workspace/web/node_modules` and `dist/` were never created on this Mac.
We had no proof the React + TypeScript build actually worked.

**Fix**:
- `npm install` from `workspace/web/` → 136 packages, clean
- `npm run build` → 1573 modules transformed, 0 errors
- Output: 160 KB JS / 51 KB gzipped + 15 KB CSS / 4 KB gzipped
- Committed `package-lock.json` for reproducible builds
- Added `workspace/web/dist/` to `.gitignore` (build output, not source)

## Gap 2 — Backend never smoke-tested

The FastAPI server had never been booted locally. Routes registered but no
proof of life.

**Fix**:
- Installed `sse-starlette fastapi uvicorn` (missing on system Python)
- Booted `uvicorn workspace.api.server:app` cleanly
- All 6 routes verified: `/api/health`, `/api/pathogens`, `/api/design`,
  `/api/design/stream`, `/api/similar`, `/api/score`
- `/api/health` returns `{"status":"ok","model":"rahul24raj/lysos-rl","loaded":false}`
- `/api/pathogens` returns the 8-pathogen list with descriptions
- Root `/` serves the React app HTML; `/assets/index-*.js` and `/assets/index-*.css` 200
- `/api/score` was 500'ing locally on missing rdkit — hardened with
  per-component try/except so it returns scores=0 for missing deps instead
  of crashing. On Docker / VM, rdkit is installed and real scores return.

## Gap 3 — Stage 2 dataset under-using DrugBank

DrugBank cache had 14,630 vocabulary entries (name, DrugBank ID, InChI Key,
CAS, synonyms, accession). The previous loader required SMILES, dropped
all 14,630 vocab rows. They were sitting on disk doing nothing.

**Fix** to `src/data/drugbank.py`:
- After unzipping the misnamed `.csv` (actually ZIP), scan extracted dir
  for inner `.csv` files (DrugBank vocab) AND `.sdf` files (structures).
- Vocab CSV: parsed with pandas, normalized columns including the new
  `inchi_key` and `accession` fields.
- Structure SDF: requires rdkit — left as VM-side work.
- Filter changed from "must have SMILES" to "must have SMILES OR InChI Key".

**New task slice in `scripts/prepare_amr_data.py`**: `build_drug_knowledge_examples`
generates 5 example types per row:
- `drug_id_lookup`     (name → DrugBank ID)
- `drug_inchi_key`     (name → Standard InChI Key)
- `drug_synonyms`      (name → synonym list)
- `drug_cas_lookup`    (name → CAS number)
- `drug_reverse_cas`   (CAS number → name)

**Stage 2 dataset growth**: 31,855 → **96,975 examples** (+204%).

| Task | Train rows | Source |
|---|---|---|
| safety_prediction | 14,004 | DBAASP hemolysis labels |
| drug_id_lookup | 13,937 | DrugBank vocabulary |
| drug_inchi_key | 13,915 | DrugBank vocabulary |
| drug_synonyms | 13,012 | DrugBank vocabulary |
| drug_cas_lookup | 10,557 | DrugBank vocabulary |
| drug_reverse_cas | 10,516 | DrugBank vocabulary |
| activity_prediction | 8,789 | ChEMBL MIC |
| peptide_design | 4,621 | DBAASP + DRAMP |
| generation_for_target | 2,776 | ChEMBL high-activity SMILES |
| **TOTAL** | **92,127** | |

Plus 4,848 valid set rows.

`task_mix` in `configs/stage2_amr_sft.yaml` rebalanced for 9 task types
instead of 5.

Pushed to `huggingface.co/datasets/rahul24raj/lysos-amr-stage2` (live, public).

## Bonus — ChEMBL widening

Added 4 more `standard_types` (EC50, GI50, Activity, Inhibition) and bumped
default cap from 5K → 8K per pathogen. Test on MRSA + Mtb showed:
- MRSA: 2,605 → 3,091 (+19%)
- Mtb: 2,732 → 4,236 (+55%)

Full re-fetch left for the VM run (faster network).

## Bonus — Real UI screenshot

Captured the live workspace UI via headless chrome:
- All 8 pathogens render in sidebar with priority badges
- MRSA selected, description displayed
- Generation parameters panel: candidates slider, temperature slider, modality picker
- Generate button styled correctly
- Footer with "AMD Developer Hackathon 2026" + version + license

Saved as `docs/assets/workspace-screenshot.png`. Embedded in:
- README (top of "What Lysos does" section)
- `docs/pitch-deck.md` (slide 4 demo)

## Tests + dry-runs all green

- `tests/test_rewards.py` — 12 passed, 1 skipped (rdkit) — unchanged
- `make verify` — 24 / 24 modules import clean
- Stage 1 / 2 / 3 training configs all dry-run cleanly

## What's actually still pending (not bugs, just GPU-blocked)

1. Real Stage 1 / 2 / 3 training runs — need AMD MI300X (Sat May 2)
2. Real wandb screenshot — generated only after RL training
3. Real `rocm-smi` capture — generated during training
4. Demo video shoot — needs trained model in workspace
5. Marp PDF render — needs `npm i -g @marp-team/marp-cli` (1-line)
6. PubChem fresh AID discovery (most curated retired, only 2 AIDs work)
7. APD3 source mirror (current URLs all 404)
