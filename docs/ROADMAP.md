# Lysos Roadmap

> Hackathon clock starts Mon May 4, 12:00 PM EDT. Submission Sun May 10, 3:00 PM EDT.

## Pre-kickoff (Apr 30 → May 3)

- [x] Tech spec locked
- [x] GitHub repo initialized
- [x] HF Space slug `lysos` reserved in `lablab-ai-amd-developer-hackathon` org
- [x] HF Hub model slugs reserved (`rahul24raj/txgemma-4-31b`, `rahul24raj/lysos-base`, `rahul24raj/lysos-rl`)
- [x] **10 real data loaders implemented** (chembl, dbaasp, dramp, card, bindingdb, pubchem, zinc, apd3, drugbank, pdb)
- [x] **Stage 2 dataset built and pushed to HF Hub** — `rahul24raj/lysos-amr-stage2` (21,007 examples)
- [x] **Stage 3 RL prompts pushed to HF Hub** — `rahul24raj/lysos-rl-prompts` (3,200 prompts)
- [x] Verifier + 13 unit tests + Makefile shipped
- [x] Workspace API (FastAPI) + UI (Vite/React/Tailwind) + Docker — full demo stack
- [x] EmbeddingGemma 300m research + integration plan (vault/research, vault/plans)
- [x] AMR dataset URLs + DUA paths confirmed (no DUA dependencies)
- [ ] AMD Dev Cloud credits confirmed in DigitalOcean (expected Sat May 2)
- [ ] All 5 official AMD/lablab workshop videos watched
- [ ] ROCm + Gemma 4 + Optimum-AMD compatibility smoke-tested (waits for credits)
- [ ] TRL GRPO trainer ROCm compat verified (waits for credits)
- [ ] EmbeddingGemma 300m integration (Phases 1–5 of vault/plans)
- [ ] DBAASP heavy-fetch finish + Stage 2 re-build with bigger AMP corpus
- [ ] Pitch deck skeleton drafted
- [ ] Cover image draft v1
- [ ] Demo video storyboard

## Day 1 — Mon May 4 (Foundation training)

- [ ] 12pm ET: kickoff stream watched
- [ ] Spin up Large 8× MI300X
- [ ] Stage 1 (TxGemma-4) training kicks off
- [ ] Workspace UI scaffold deployed (no model needed yet)
- [ ] AMR dataset preparation started
- [ ] First social post (Build-in-Public)
- [ ] Stage 1 finishes by EOD

## Day 2 — Tue May 5 (AMR specialization)

- [ ] Stage 2 (AMR SFT) on Small MI300X
- [ ] Workspace UI: first end-to-end with Stage 1 model
- [ ] Scoring engine integrations (RDKit, DiffDock)
- [ ] Daily social post

## Day 3 — Wed May 6 (RL training)

- [ ] Stage 3 (GRPO) kicks off
- [ ] Workspace UI: scoring + 3D viz integrated
- [ ] First end-to-end generation working
- [ ] Daily social post

## Day 4 — Thu May 7 (Integration + polish)

- [ ] Stage 3 completes; final model on HF Hub
- [ ] Workspace UI polished, pre-loaded targets working
- [ ] Demo dry-run #1
- [ ] Slides locked
- [ ] Daily social post

## Day 5 — Fri May 8 (Record + polish)

- [ ] Demo video shot + edited
- [ ] Cover image finalized
- [ ] Submission writeup drafted
- [ ] Buffer day for bugs
- [ ] Daily social post

## Day 6 — Sat May 9 (Submission)

- [ ] Final submission package assembled
- [ ] Submitted to lablab.ai (24h before deadline)
- [ ] If on-site invitation: travel to SF
- [ ] Daily social post

## Day 7 — Sun May 10 (Deadline + pitch)

- [ ] 3pm EDT: submission deadline
- [ ] If on-site: 5pm EDT on-stage pitch

## Stretch goals (if Day 4 ahead of schedule)

- [ ] 26B-A4B MoE variant comparison
- [ ] Live wet-lab partnership outreach
- [ ] HF Science leaderboard submission
- [ ] Tuberculosis-specific pathogen benchmark
- [ ] Genomic resistance prediction extension
- [ ] Continued pre-training for peptides as separate fine-tune
