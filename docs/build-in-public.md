# Build-in-Public — Lysos × AMD Developer Hackathon

Pre-written posts for X/Twitter and LinkedIn during the hackathon week (May 4–10 2026).
Goal: weight toward technical signal over marketing tone.

Style notes:
- One image per post (cover, architecture, data-flow, or a concrete chart)
- Numbers > adjectives. "31,855 instructions" not "huge dataset"
- One link per post, never more
- No emoji unless the post is genuinely celebratory (final commit)

---

## Day -3 (May 1, today) — quiet teaser

> Spent the week wiring the data pipeline for an AMR drug-design model on the AMD Developer Hackathon.
>
> 10 real public sources (ChEMBL, DBAASP, DRAMP, CARD, PDB, ZINC, …) → 31,855 instruction-tuning examples for Gemma 4 31B.
>
> Datasets and code go public when the kickoff bell rings on Saturday.

Image: `docs/assets/data-flow.png`

---

## Day 0 — kickoff (Saturday May 4, 12 PM EDT)

> Lysos is live. Open-source generative drug designer for antimicrobial resistance. Built on Gemma 4 31B, RL-tuned on AMD Instinct MI300X.
>
> Public weights, public dataset, public code on day one.
>
> github.com/Rahul-Rajpurohitk/lysos

Image: `docs/assets/cover-1920.png`

---

## Day 1 — architecture explainer

> Why MI300X 192 GB matters for Lysos: the GRPO training step holds the policy, the frozen reference, and the reward predictor coresident — peak ≈152 GB.
>
> An H100 80 GB has to shard. The MI300X fits the entire stack on one card.
>
> No latency penalty, no NCCL overhead, no extra hardware cost.

Image: `docs/assets/architecture.png`

---

## Day 2 — Stage 1 / Stage 2 done

> Stage 1 (TxGemma-4 chemistry foundation) and Stage 2 (AMR specialization SFT) checkpoints both pushed to Hugging Face.
>
> Composite reward starts climbing in Stage 3 RL training tomorrow.
>
> hf.co/rahul24raj/lysos-base

Image: real wandb screenshot (loss curve)

---

## Day 3 — RL training live, mid-run

> Stage 3 GRPO with verifiable rewards now running on the MI300X. Six-component composite — validity, drug-likeness, synthesizability, hemolysis safety, predicted MIC, novelty (Tanimoto + Gemini Embedding 2 cosine).
>
> Every component logged separately so we catch reward-hacking. Validity and predicted-MIC both trending up. No collapse.

Image: real per-component reward curves (replaces `reward-curves.svg`)

---

## Day 4 — workspace demo

> Lysos workspace is now live on Hugging Face Spaces. Pick a target pathogen → 50 candidate molecules in 30 seconds, scored on six dimensions.
>
> Click "find similar known drugs" and EmbeddingGemma searches an index of 20,489 known antibiotics. Top-5 closest match by cosine.
>
> hf.co/spaces/lablab-ai-amd-developer-hackathon/lysos

Image: workspace screenshot — 5 candidate cards with score panels

---

## Day 5 — Stage 3 done, results

> Stage 3 done. Side-by-side, RL-tuned vs SFT-only:
>
> validity 87 → 94 (+7)
> predicted MIC 0.41 → 0.62 (+50%)
> drug-likeness 0.54 → 0.61 (+13)
> semantic novelty 0.68 → 0.79 (+16)
>
> Reinforcement learning + verifiable rewards matters.

Image: comparison panel from storyboard Section 7

---

## Day 6 — submission day

> Submitted Lysos to the AMD Developer Hackathon. Open weights, open dataset, open code.
>
> Built end-to-end on a single AMD Instinct MI300X — Stage 1, Stage 2, Stage 3, and the demo workspace, all on the same GPU.
>
> Demo: hf.co/spaces/lablab-ai-amd-developer-hackathon/lysos
> Code: github.com/Rahul-Rajpurohitk/lysos

Image: final 5-min demo video as native upload

---

## What to do during the week

- Reply to every comment. Treat each as a chance to explain the technical depth.
- Tag @AMD and @lablab_ai on the kickoff + submission posts.
- Quote-tweet other Track 2 builders to amplify them (cooperation builds the community).
- Cross-post each tweet to LinkedIn with the same image, slightly more formal phrasing.

## What to NOT do

- No "we" pronouns when only one person is on the build. Stay first-person.
- No "revolutionary" / "world-class" / "game-changing" adjectives.
- No screenshot of code without context — always pair with the visual asset (architecture, data flow, etc.) so it tells a story.
