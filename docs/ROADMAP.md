# Lysos Roadmap

> Hackathon clock starts Mon May 4, 12:00 PM EDT. Submission Sun May 10, 3:00 PM EDT.

## Pre-kickoff (Apr 30 → May 3)

### Done (verified)

- [x] Tech spec locked (`docs/tech-spec.md`)
- [x] GitHub repo initialized — 70+ commits on `main`
- [x] HF Space slug `lysos` reserved in `lablab-ai-amd-developer-hackathon` org
- [x] HF Hub model slugs reserved (`rahul24raj/txgemma-4-31b`, `rahul24raj/lysos-base`, `rahul24raj/lysos-rl`)
- [x] **10 real data loaders implemented + verified live**: ChEMBL ✓, DBAASP ✓, DRAMP ✓, CARD ✓, DrugBank ✓, PDB ✓, ZINC ✓ · BindingDB ⚠ JSP-gated · PubChem ⚠ AIDs retired · APD3 ⚠ source 404
- [x] **Stage 2 dataset v2 live on HF Hub** — `rahul24raj/lysos-amr-stage2-pro-v2` · **364,432 train + 29,300 valid + 55 held-out test** · 27 task types including the new elite named-drug CoT slice (333 entries across 14 reasoning task types, oversampled 25x to 5% of training compute)
- [x] **Stage 3 RL prompts live on HF Hub** — `rahul24raj/lysos-rl-prompts` (12,000 prompts)
- [x] **Known-antibiotics RAG index** — `data/processed/known_antibiotics_index.parquet` (20,489 rows from ChEMBL+DBAASP+DRAMP)
- [x] Verifier (`make verify` 24/24) + 13 unit tests (12 pass, 1 skip-no-rdkit) + Makefile shipped
- [x] **Workspace verified end-to-end** — FastAPI boots, all 6 routes register, frontend builds clean (1573 modules, 160KB JS), real screenshot captured
- [x] **EmbeddingGemma 300m integration — all 5 phases shipped** (novelty reward + RAG + dedup + similar-drugs UI + index)
- [x] **Pitch deck (10 slides, Marp-PDF-ready)** — `docs/pitch-deck.md` with frontmatter
- [x] **Demo video storyboard** — `docs/demo-video-storyboard.md` (5-min, 8 sections, beat-by-beat)
- [x] **Visual assets (5 SVG + 6 PNG)** — cover, thumbnail, architecture, data-flow, reward-curves, ROCm-SMI, workspace screenshot
- [x] **Build-in-Public posts drafted** — `docs/build-in-public.md` (day -3 → submission)
- [x] **Judging-criteria map** — `docs/judging-criteria-map.md` (artifact-by-axis index)
- [x] **HF model + dataset cards** — `model_cards/lysos-rl.md`, `model_cards/lysos-amr-stage2.md` (v1), `model_cards/lysos-amr-stage2-pro-v2.md` (v2 NEW, on HF)
- [x] **VM bootstrap script** — `scripts/vm_bootstrap.sh` (one-shot AMD VM setup)
- [x] **HF Space deploy script** — `scripts/deploy_to_hf_space.py` + `make space-deploy`
- [x] **Asset renderer** — `scripts/render_assets.py` (rsvg → inkscape → headless-chrome chain)
- [x] **CITATION.cff** — academic-citation file for the GitHub repo
- [x] **examples/** — quickstart.py, score_smiles.py, find_similar_drugs.py + README
- [x] AMR dataset URLs + licensing confirmed (no DUA dependencies)
- [x] **Stage 2 v2 elite reasoning slice** — 388 named-drug CoT entries (333 train + 55 held-out test) merged into pro v2; 14 reasoning task types weighted to 5% of training compute (25x oversample); zero leakage verified
- [x] **Stage 2 v2 smoke-test** — `scripts/smoke_test_stage2_v2.py` 8/8 PASSED (caught + fixed pre-existing config typos for drug_smiles + natural_product_origin task names)
- [x] **Named-drug QC pass** — `scripts/qc_named_drug.py` cleaned 2 corrupt entries; verified schema + zero internal duplicates + zero held-out test leakage

### GPU-blocked / waiting on credits (Sat May 2 expected)

- [ ] AMD Dev Cloud credits confirmed in DigitalOcean
- [ ] ROCm + Gemma 4 + Optimum-AMD smoke test (`scripts/smoke_test_rocm.py` ready)
- [ ] TRL GRPO trainer ROCm compatibility verified
- [ ] vLLM/ROCm Docker boots cleanly on MI300X (1hr smoke)
- [ ] Stage 1 (TxGemma-4) dry-run with PyTDC installed
- [ ] Real `rocm-smi` capture during Stage 3 (replaces `rocm-smi-mockup.svg`)
- [ ] Real wandb screenshots of reward curves (replaces `reward-curves.svg`)

### Optional polish (cheap if I have time)

- [ ] Run wider ChEMBL fetch (8K/pathogen, +EC50/GI50/Inhibition types) — yields ~20-50% more rows per pathogen
- [ ] Re-run dedup on the 222,606-row Stage 2 with EmbeddingGemma to drop near-duplicates
- [ ] Find new working PubChem AIDs (most curated retired) — eutils search returns ~30 candidates per pathogen
- [ ] Mirror APD3 from a GitHub fork (current site URLs all 404)
- [ ] Render `docs/pitch-deck.md` to PDF via Marp (one `npm i` away)

## Day 1 — Mon May 4 (kickoff + Stage 1)

- [ ] 12pm EDT: kickoff stream watched
- [ ] `git tag pre-training-baseline` on laptop
- [ ] Spin up Small 1× MI300X for smoke test ($1.99/hr)
- [ ] `bash scripts/vm_bootstrap.sh` — full VM setup (~25 min)
- [ ] `scripts/smoke_test_rocm.py` passes
- [ ] First inference smoke: generate 2 SMILES from base Gemma 4 31B
- [ ] PyTDC install + `prepare_tdc_data.py` → push `lysos-tdc-stage1`
- [ ] Tear down Small, spin up Large 8× MI300X ($15.04/hr)
- [ ] Stage 1 (TxGemma-4) kicks off
- [ ] Day 0 social post per `docs/build-in-public.md`
- [ ] Stage 1 finishes by EOD (6-8 hr wall-clock); push `txgemma-4-31b` to HF Hub
- [ ] Tear down Large; spin Small back up

## Day 2 — Tue May 5 (Stage 2 + workspace)

- [ ] Stage 2 (AMR SFT) on Small MI300X — 15-20 hr wall-clock
- [ ] Workspace polishing: ensure Stage 1 model serves correctly
- [ ] Day 1 social post — architecture explainer + `architecture.png`
- [ ] Stage 2 finishes EOD-ish; push `lysos-base` to HF Hub

## Day 3 — Wed May 6 (Stage 3 RL)

- [ ] Stage 3 (GRPO) kicks off on Small — 15-25 hr wall-clock
- [ ] **Capture real `rocm-smi` output during a GRPO step → swap into mockup**
- [ ] **Capture wandb screenshots of per-component reward → swap into reward-curves.png**
- [ ] Day 2 social post — Stage 1 + 2 done, RL in progress
- [ ] Workspace deploy dry-run via `make space-deploy`

## Day 4 — Thu May 7 (RL finalization)

- [ ] Stage 3 completes; push final `lysos-rl` to HF Hub
- [ ] Workspace HF Space goes live with the trained model
- [ ] Demo dry-run #1 against the live Space
- [ ] Pitch deck refresh: substitute mockups with real wandb / rocm-smi screenshots
- [ ] Day 3 social post — Stage 3 done, side-by-side numbers

## Day 5 — Fri May 8 (record + polish)

- [ ] Demo video shot + edited per `docs/demo-video-storyboard.md` (target ≤4:45)
- [ ] Cover image final pass (already shipped at 1920×1080)
- [ ] Submission writeup at all three lengths (280 chars / 1500 chars / 250 words)
- [ ] Buffer day for bugs
- [ ] Day 4 social post — workspace demo

## Day 6 — Sat May 9 (submit early)

- [ ] Final submission package assembled
- [ ] Submitted to lablab.ai (24h before the deadline)
- [ ] If on-site invitation: travel to SF
- [ ] Day 5 social post — submission day

## Day 7 — Sun May 10 (deadline + pitch)

- [ ] 3pm EDT: submission deadline (we're already in)
- [ ] If on-site: 5pm EDT on-stage pitch

## Stretch goals (if Day 4 ahead of schedule)

- [ ] 26B-A4B MoE variant comparison
- [ ] Live wet-lab partnership outreach
- [ ] HF Science leaderboard submission
- [ ] Tuberculosis-specific pathogen benchmark
- [ ] Genomic resistance prediction extension
- [ ] Continued pre-training for peptides as separate fine-tune
