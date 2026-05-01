# Lysos — judging criteria map

Mapping the lablab.ai / AMD Developer Hackathon judging criteria to the
specific artifacts we've shipped. Use this as a one-page index when
preparing the submission and during judging conversations.

## Lablab judging criteria

The four axes (per the lablab handbook):

1. **Presentation** — clarity of pitch, visual quality of deck + video
2. **Application of Technology** — depth of AMD MI300X / ROCm utilization
3. **Business Value** — TAM/SAM, customer mapping, monetization plan
4. **Originality** — novelty of approach, USP vs competitors

---

## 1. Presentation

| Artifact | Path | Status |
|---|---|---|
| Pitch deck (10 slides, Marp-PDF) | `docs/pitch-deck.md` | ready, render with `make pitch-pdf` |
| Cover image (1920×1080) | `docs/assets/cover-1920.{svg,png}` | ✓ shipped |
| Architecture diagram | `docs/assets/architecture.{svg,png}` | ✓ shipped |
| Data pipeline diagram | `docs/assets/data-flow.{svg,png}` | ✓ shipped |
| Demo video storyboard | `docs/demo-video-storyboard.md` | ready for shoot |
| Workspace UI (deployable HF Space) | `workspace/` | code complete, deploy via `make space-deploy` |
| Build-in-public posts | `docs/build-in-public.md` | drafted, daily posting plan |

Visual identity:
- Color: dark biomedical (`#06121a` background, `#00e6b9` Lysos teal)
- Type: JetBrains Mono for values, Inter for narrative
- Style: numbers > adjectives, no marketing-speak

## 2. Application of Technology

The MI300X 192 GB story is the central technology pitch:

| Claim | Evidence |
|---|---|
| Single-card RL training (no sharding) | Slide 5 + Section 6 of storyboard + `architecture.svg` memory budget bar |
| 152 GB peak fits on MI300X, busts H100 80 GB | `docs/tech-spec.md` §4 + `rocm-smi-mockup.svg` |
| Three-stage training pipeline | `src/training/stage{1,2,3}_*.py` + corresponding `configs/*.yaml` |
| Six-component verifiable reward | `src/eval/rewards/` + `tests/test_rewards.py` |
| ROCm + vLLM + TRL working together | `docker/Dockerfile.rocm` + `scripts/smoke_test_rocm.py` |
| Two Gemma-family models coresident | `workspace/api/server.py` lazy-loads both |
| EmbeddingGemma novelty + RAG + similar-drugs | `src/eval/rewards/embedding_novelty.py` + `src/inference/retrieval.py` + workspace UI |

Reproducibility:
- All training configs in `configs/` (YAML, dry-run-able)
- All data sources in `src/data/` (10 real loaders, all open-license)
- All rewards in `src/eval/rewards/` (unit-tested)
- VM bootstrap: `bash scripts/vm_bootstrap.sh` does everything from a fresh AMD VM

## 3. Business Value

| Slide / artifact | What it covers |
|---|---|
| Pitch slide 2 (problem) | 1.27M deaths/year today, 10M projected by 2050 |
| Pitch slide 7 (business value) | TAM $50B antibiotic market, SAM $5–10B novel R&D |
| Pitch slide 9 (roadmap) | Q3 2026 wet-lab partnerships, 2027 spin-out |
| `docs/tech-spec.md` §1 (motivation) | Detailed problem framing |
| Customers identified | BARDA + CARB-X + academic AMR labs + pharma rare-disease + biosecurity (DARPA, IARPA) |
| Revenue model | Dataset + model licensing, enterprise hosting, cost-per-design API |

Why pharma left the market: high R&D cost, low antibiotic margins, slow regulatory cycle. Lysos's cost structure (one MI300X, ~$240/training run, open weights) changes the calculus.

## 4. Originality

| Differentiator | Evidence |
|---|---|
| Open-source frontier-model AMR designer | First of its kind. No equivalent open project exists. |
| Frontier model (Gemma 4 31B, April 2026) | Most projects are still on older models — ours uses the latest |
| Verifiable rewards (not human prefs) | 6-component reward, every term computable & open-source |
| Single-GPU training pitch | Most public RL drug-design uses multi-node — we run everything on one MI300X |
| Two Gemma-family models coresident | Generator + Embedder on same card — only possible with 192 GB |
| Real public data only (no proprietary) | 10 sources, all freely available, all open license |

Pitch slide 8 has the side-by-side competitor table (Insilico, Recursion, Atomwise, ChemLLM, Galactica).

---

## Quick navigation for judges

If you have **5 minutes**, watch:
- The 5-min demo video (will be embedded in the lablab submission)

If you have **15 minutes**, additionally read:
- `README.md` (top of page) — what + why
- The pitch deck (`docs/pitch-deck.md` rendered as PDF) — 10 slides
- `STATUS.md` — what's been shipped to date

If you have **30 minutes**, additionally explore:
- `docs/tech-spec.md` — architecture in detail
- `src/training/stage3_rl_grpo.py` — the heart of the training stack
- `src/eval/rewards/embedding_novelty.py` — the EmbeddingGemma novelty reward
- The live workspace at `huggingface.co/spaces/lablab-ai-amd-developer-hackathon/lysos`

---

## Submission checklist

- [ ] Cover image PNG (≤ 5 MB) → `docs/assets/cover-1920.png` (910 KB ✓)
- [ ] Pitch deck PDF → `make pitch-pdf` then attach `docs/lysos-pitch.pdf`
- [ ] 5-min MP4 demo video → record per `docs/demo-video-storyboard.md`
- [ ] Submission writeup (≤ 1500 chars) → use `docs/pitch-deck.md` slide 1+2+3 condensed
- [ ] GitHub repo URL → https://github.com/Rahul-Rajpurohitk/lysos
- [ ] HF Space URL → https://huggingface.co/spaces/lablab-ai-amd-developer-hackathon/lysos
- [ ] HF model URLs → 3 reserved slugs at `huggingface.co/rahul24raj/`
