---
title: Launch readiness — what's still possible before AMD credits land
date: 2026-05-01
status: active
priority: P0
horizon: T-3 days to kickoff (Mon May 4, 12:00 PM EDT)
---

# Lysos — launch readiness plan

The submission window opens Mon May 4 12:00 PM EDT and closes Sun May 10
3:00 PM EDT. AMD Dev Cloud credits are expected to land Sat May 2.

This plan separates work into three buckets:

1. **DONE** — already shipped, verified, in the repo
2. **PRE-CREDITS PRE-WORK** — things we can still do on this Mac before May 2
3. **DAY-1 RUNBOOK** — the exact sequence to execute the moment credits arrive

---

## 1. DONE — verified state of the repo (2026-05-01)

### Code + dataset

| Area | What | Verification |
|---|---|---|
| Repo | `github.com/Rahul-Rajpurohitk/lysos` · ~70 commits | `git log --oneline` |
| Stage 2 dataset | 222,606 examples · 9 task types · live on HF Hub | `datasets.load_dataset("rahul24raj/lysos-amr-stage2")` |
| Stage 3 RL prompts | 3,200 prompts · 8 pathogens × 2 modalities · live | `datasets.load_dataset("rahul24raj/lysos-rl-prompts")` |
| RAG index | 20,489 known antibiotics with EmbeddingGemma vectors | `data/processed/known_antibiotics_index.parquet` |
| Module verifier | 24 / 24 modules import clean | `make verify` |
| Reward unit tests | 12 pass, 1 skip (rdkit) | `make test` |
| Training dry-runs | Stage 1, 2, 3 all parse configs cleanly | `python -m src.training.stage{1,2,3}_* --dry-run` |
| Frontend build | 1573 modules, 0 errors, 160 KB JS bundle | `npm run build` in `workspace/web/` |
| Backend boot | All 6 routes register, /api/health 200, static frontend served | `uvicorn workspace.api.server:app` |
| EmbeddingGemma | All 5 integration phases shipped | `vault/plans/2026-05-01-embeddinggemma-integration.md` |

### Submission artifacts

| Artifact | Path | Status |
|---|---|---|
| Pitch deck (10 slides, Marp) | `docs/pitch-deck.md` | ready, render with `make pitch-pdf` |
| Demo video storyboard | `docs/demo-video-storyboard.md` | ready for shoot post-training |
| Cover image (16:9) | `docs/assets/cover-1920.{svg,png}` | ✓ |
| Square thumbnail | `docs/assets/thumbnail-square.{svg,png}` | ✓ |
| Architecture diagram | `docs/assets/architecture.{svg,png}` | ✓ |
| Data-flow diagram | `docs/assets/data-flow.{svg,png}` | ✓ |
| Reward-curves mockup | `docs/assets/reward-curves.{svg,png}` | ⚠ swap with real wandb after Stage 3 |
| ROCm-SMI mockup | `docs/assets/rocm-smi-mockup.{svg,png}` | ⚠ swap with real `rocm-smi` capture |
| Workspace screenshot | `docs/assets/workspace-screenshot.png` | ✓ real, captured from local build |
| Build-in-Public posts | `docs/build-in-public.md` | drafted day -3 → submission day |
| Judging-criteria map | `docs/judging-criteria-map.md` | ready |
| Model cards | `model_cards/lysos-rl.md` + `model_cards/lysos-amr-stage2.md` | ready (push at submission) |
| CITATION.cff | repo root | ready |
| examples/ | quickstart · score-one-smiles · find-similar-drugs | ready |

### Deploy infrastructure

| Tool | Path | Purpose |
|---|---|---|
| `scripts/vm_bootstrap.sh` | one-shot AMD VM setup | clone, deps, HF cache pre-warm, smoke, datasets |
| `scripts/deploy_to_hf_space.py` | assemble + push to HF Space | `make space-deploy` (HF_TOKEN required) |
| `scripts/render_assets.py` | SVG → PNG | rsvg → inkscape → headless-chrome chain |
| `Makefile` targets | `verify` · `test` · `fetch` · `inventory` · `assets` · `pitch-pdf` · `space-deploy` · `build-index` · `web-build` · `api-dev` · `docker` | |

---

## 2. PRE-CREDITS PRE-WORK — what's left to ship before May 2

These are all doable on this Mac without GPU access. Ranked by leverage.

### High-leverage (do these)

#### A. Submission writeup (≤ 1500 chars) — `docs/submission-writeup.md`

lablab requires a short submission description. Compress slides 1+2+3
of the pitch deck. ~30 min.

#### B. Marp PDF render — `docs/lysos-pitch.pdf`

Install Marp CLI, run `make pitch-pdf`, sanity-check the slides. The
frontmatter is already in `docs/pitch-deck.md`.

```bash
npm i -g @marp-team/marp-cli
make pitch-pdf
open docs/lysos-pitch.pdf
```

If the styles need tweaking — they will, Marp's defaults are spartan —
add custom CSS to the `style:` block in the frontmatter.

#### C. Wider ChEMBL re-fetch (~30 min)

The May-01 ChEMBL widening (`standard_types` += `EC50`, `GI50`, `Activity`,
`Inhibition`; cap 5K → 8K) showed +19% (MRSA) to +55% (Mtb) on a partial
test. Run the full sweep across 8 pathogens.

```bash
python -m src.data.chembl --output data/raw/chembl_antibiotics.csv \
    --max-per-pathogen 8000 --refresh
python scripts/prepare_amr_data.py
# rebuilds Stage 2 with the bigger ChEMBL corpus
# expected: ~110-115K examples (was 222,606)
```

Then re-push to HF Hub.

#### D. Stage 2 EmbeddingGemma dedup pass (~10 min)

Run the dedup script to drop near-duplicates from the 222,606-row Stage 2.
Expected to drop 5-15%. Cleaner training, less reward-hacking risk.

```bash
python scripts/dedup_with_embeddings.py \
    --input data/processed/amr-stage2 \
    --output data/processed/amr-stage2-dedup \
    --threshold 0.95
```

(Note: this script needs the EmbeddingGemma model loaded — slow on Mac
but works. Or defer to VM where it's faster.)

#### E. APD3 GitHub mirror discovery

The current APD3 site URLs all 404. Search GitHub for FASTA mirrors.
Likely candidates: `wishartlab/apd3-mirror`, `aroka/amp-databases`. Wire
into `src/data/apd3.py`. Even +1-2K curated AMPs is meaningful.

### Medium-leverage (nice to have)

#### F. Submission writeup variants

Lablab + AMD dev cloud likely each want different lengths. Pre-write:
- 280 chars (one tweet)
- 1500 chars (lablab submission)
- ~250 words (HF Space card README)

#### G. Workspace UI: error-state polish

When the API model isn't loaded (which is normal pre-VM), the UI shows
a generic error. Replace with a clear "model warming up — first request
takes 60s" message. Helps the live demo recover gracefully.

#### H. PubChem fresh-AID discovery

Use NCBI eutils to find currently-live antibacterial AIDs with high
active-compound counts. Wire the new AIDs into `src/data/pubchem.py`.
Could yield 1-5K extra activity records.

### Low-leverage (skip unless we have hours to burn)

#### I. BindingDB workaround

The JSP-gated download requires session cookies + manual click. Not
worth automating for a 1-week hackathon.

#### J. DiffDock integration

10+ GB extra, ~30s per candidate latency. Out of scope for v1.

---

## 3. DAY-1 RUNBOOK — the exact sequence the moment credits land

### T+0:00 — credits confirmed in DigitalOcean

```bash
# On laptop:
git pull
git tag pre-training-baseline -m "checkpoint before any GPU run"
git push --tags
```

### T+0:05 — spin up Small 1× MI300X for smoke test ($1.99/hr)

Boot the VM via DigitalOcean console. SSH in.

### T+0:10 — bootstrap

```bash
# On VM (one command):
curl -sSL https://raw.githubusercontent.com/Rahul-Rajpurohitk/lysos/main/scripts/vm_bootstrap.sh | bash
```

This:
1. Verifies ROCm + MI300X visible
2. Clones the repo
3. `pip install -e .`
4. Pre-warms HF cache (Gemma 4 31B + EmbeddingGemma — 60+ GB download)
5. Runs `make verify` + `scripts/smoke_test_rocm.py`
6. Pulls live HF datasets

Expected wall-clock: 15-25 min depending on HF download speed.

### T+0:35 — smoke test the full inference path

```bash
# On VM:
python -c "
from src.inference.generate import LysosGenerator
g = LysosGenerator(model_id='google/gemma-4-31B-it', enable_rag=False)
out = g.design('MRSA', n=2, max_new_tokens=128)
print(out)
"
```

If this works, we have proof of life on AMD. Time to commit.

### T+0:45 — pre-VM-build TDC Stage 1 dataset

```bash
# On VM (PyTDC needs python deps that are too heavy for Mac):
pip install PyTDC
python scripts/prepare_tdc_data.py --output data/processed/tdc-stage1
python scripts/prepare_tdc_data.py --output data/processed/tdc-stage1 \
    --push-to-hub rahul24raj/lysos-tdc-stage1
```

### T+1:30 — Tear down Small VM, spin up Large 8× MI300X ($15.04/hr)

The size up is needed for Stage 1 — TxGemma-4 trains on Large for ~6-8 hr
wall-clock. (Stages 2 + 3 go back to Small.)

### T+1:45 — Stage 1 (TxGemma-4) kicks off

```bash
# On Large 8× VM:
bash scripts/vm_bootstrap.sh   # rerun on the new node
python -m src.training.stage1_txgemma4 \
    --config configs/stage1_txgemma4.yaml \
    2>&1 | tee logs/stage1.log
```

While Stage 1 runs (6-8 hr), open laptop and:
- Tweet the kickoff post (`docs/build-in-public.md` Day 0)
- Watch the live train metrics on wandb
- Polish anything that surfaces as a bug

### T+9:00 — Stage 1 finishes; back to Small VM

```bash
# Push Stage 1 checkpoint to HF Hub:
python -c "
from huggingface_hub import upload_folder
upload_folder(
    folder_path='./checkpoints/stage1-txgemma4/final',
    repo_id='rahul24raj/txgemma-4-31b',
    repo_type='model',
)
"

# Tear down Large, spin up Small:
# (DigitalOcean console — saves ~$13/hr while we're not using 8 cards)
```

### T+9:30 — Stage 2 (AMR SFT) on Small

```bash
# On Small VM:
python -m src.training.stage2_amr_sft \
    --config configs/stage2_amr_sft.yaml \
    2>&1 | tee logs/stage2.log
```

15-20 hr wall-clock. While running, polish workspace UI bugs.

### T+27:00 — Stage 2 finishes; Stage 3 RL kicks off

```bash
python -m src.training.stage3_rl_grpo \
    --config configs/stage3_rl_grpo.yaml \
    2>&1 | tee logs/stage3.log
```

15-25 hr wall-clock. **Capture `rocm-smi` output during Stage 3 GRPO step**
— this is the 152 GB callout that anchors the AMD utilization story:

```bash
rocm-smi --showmeminfo vram --showpids > docs/assets/rocm-smi-real.txt
```

Save to repo. Same with the wandb run URL.

### T+50:00 — Stage 3 done; demo workspace deploys

```bash
# Push final model:
upload to rahul24raj/lysos-rl

# Deploy workspace:
HF_TOKEN=$HF_TOKEN make space-deploy

# Test the deployed Space:
curl https://lablab-ai-amd-developer-hackathon-lysos.hf.space/api/health
```

### T+52:00 — Record demo video

Per `docs/demo-video-storyboard.md` — 8 sections, 5 min total.

### T+56:00 — Build pitch deck PDF, write writeup

```bash
make pitch-pdf
# Marp renders docs/pitch-deck.md → docs/lysos-pitch.pdf
```

Update `docs/pitch-deck.md` with real numbers from training:
- Real Stage 3 vs Stage 2 reward comparison (from wandb)
- Real cost (sum of `digitaloceanv2 invoices` for the week)
- Final dataset sizes if changed

### T+60:00 — Submission day (Sun May 9, 24h before deadline)

Submit via lablab portal:
- Cover image PNG
- Pitch deck PDF
- 5-min MP4
- Submission writeup (≤ 1500 chars)
- GitHub URL
- HF Space URL
- HF model URLs

Then: `git tag v1.0-submission`. Sleep.

---

## 4. Risk register (what could go wrong)

| Risk | Likelihood | Mitigation |
|---|---|---|
| Gemma 4 31B not yet on HF Hub at kickoff time | Low | Backup model: `gemma-4-26B-A4B-it` (MoE, also frontier) |
| ROCm + Gemma 4 + Optimum-AMD has a bug | Medium | Use HF Transformers without Optimum-AMD (slower but works); fall back to CPU pretokenize |
| TRL GRPO trainer broken on ROCm | Medium | Switch to DPO (simpler RL, more mature) — pre-existing config option |
| Stage 1 fails or is slow | Medium | Skip Stage 1; jump direct to Stage 2 from base Gemma 4. Lose the "TxGemma-4 release" angle, keep the Lysos angle. |
| Demo workspace fails to deploy on HF Space | Low | Pre-recorded fallback video; same demo runs from `make api-dev` on the VM |
| Idle VM accidental burn ($48 per 24 hr on Large) | Medium | Hard rule: destroy VM at end of every session. Set $50 alert. |
| Out of credits | Low | Stage 1 is the expensive one ($90-120). Reserve $50+ for Stage 2 + 3 + buffer. |
| Demo video > 5 min | Medium | Storyboard targets 4:30 max — 30s buffer for trim |

---

## 5. What we explicitly are NOT doing in v1

These are ROADMAP "stretch goals" — listed here for clarity, deferred for v2.

- **DiffDock binding pose prediction** — adds 10+ GB and 30s/candidate latency
- **3D molecule visualization in workspace** — Mol*/3Dmol.js — Q3 2026
- **MoE variant comparison (gemma-4-26B-A4B-it)** — only if Day 4 ahead of schedule
- **Wet-lab partner outreach** — Q3 2026
- **Multimodal protein-structure input** — needs `gemini-embedding-2` (paid API), Q4 2026
- **HF Science leaderboard submission** — post-hackathon
- **Continued pre-training for peptides as separate fine-tune** — v2
- **Genomic resistance prediction extension** — v2

---

## 6. Acceptance criteria for "ready to launch"

By Sat May 2 12:00 PM EDT (T-46 hr to kickoff), these all must be green:

- [x] All non-GPU code paths verified locally
- [x] Stage 2 + Stage 3 datasets live on HF Hub
- [x] Pitch deck rendered to PDF
- [x] Demo video storyboard finalized
- [x] Visual assets (cover, architecture, data-flow) PNG-rendered
- [x] vm_bootstrap.sh tested for syntax
- [ ] Submission writeup drafted at all 3 lengths
- [ ] HF_TOKEN scoped + saved in 1Password
- [ ] $50 spend alert set in DigitalOcean
- [ ] AMD credits confirmed visible in DigitalOcean billing
