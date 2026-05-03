# Lysos — submission writeups (3 lengths)

The lablab portal asks for a project description and HF Space wants a card.
Pre-written here; copy-paste at submission time. Updated 2026-05-03 for the
Stage 2 pro v2 dataset (364K train + elite reasoning slice).

---

## A. 280 characters (one tweet)

> Lysos: open-source generative drug designer for antimicrobial resistance.
> Gemma 4 31B + GRPO on a single AMD MI300X.
> 364K SFT examples + 14-task elite reasoning slice + ML MIC predictor reward.
> github.com/Rahul-Rajpurohitk/lysos

(258 chars — fits on X)

---

## B. 1500 characters (lablab submission portal)

> **Lysos** is an open-source generative drug designer for antimicrobial resistance.
>
> AMR kills 1.27M people every year, projected to reach 10M/year by 2050. Pharma has largely abandoned antibiotic R&D. Lysos uses generative AI to design novel antibacterial molecules in seconds against drug-resistant pathogens, with publicly verifiable activity scores.
>
> **Built on Gemma 4 31B-it**, trained in three stages on a single AMD Instinct MI300X:
> 1. **Stage 1 — TxGemma-4 chemistry foundation** (Therapeutics Data Commons, 28 ADMET/binding/tox tasks)
> 2. **Stage 2 — AMR specialization SFT** on the new `lysos-amr-stage2-pro-v2` dataset: 364,432 train + 29,300 valid + 55 held-out test, 27 task types from 9 real public sources (ChEMBL, DBAASP, DRAMP, DrugBank, DrugCentral, NPAtlas, CARD, PDB, ZINC) plus a 333-entry **elite named-drug chain-of-thought slice** (14 reasoning task types, 25x oversampled to 5% of training compute)
> 3. **Stage 3 — GRPO reinforcement learning** with 8 verifiable reward components: validity, structural alerts, predicted MIC (XGBoost ML predictor on Morgan fingerprints, scaffold-CV MAE 0.62, R² 0.56 — not a heuristic), QED drug-likeness, SA synthesizability, hemolysis safety, Tanimoto Morgan-FP novelty, Gemini Embedding 2 semantic novelty
>
> **Why MI300X**: GRPO holds policy + reference + reward predictor coresident — peak ≈152 GB. An H100 80 GB has to shard. The MI300X 192 GB fits the entire training stack on a single card.
>
> **Best open generator + best closed embedder**: Gemma 4 31B-it runs on the MI300X (62 GB FP16) for molecule generation, paired with Gemini Embedding 2 (gemini-embedding-001, 3072d Matryoshka, MTEB top-1) via Google API for retrieval, semantic novelty, and the "find similar drugs" UI feature.
>
> Apache-2.0 weights, public dataset on HF Hub, MIT-licensed code, reproducible Docker. <$240 per training run on AMD Developer Cloud.

(~1,490 chars)

---

## C. ~250 words (HF Space card README)

> # Lysos — generative drug designer for antimicrobial resistance
>
> Built on Gemma 4 31B + Gemini Embedding 2, RL-tuned on AMD Instinct MI300X.
>
> ## What it does
> Pick a target pathogen (MRSA, M. tuberculosis, ESBL+ E. coli, K. pneumoniae CRE, A. baumannii, P. aeruginosa, VRE, N. gonorrhoeae). Lysos generates 50 candidate antibacterial molecules in under 30 seconds, each scored on 8 dimensions: predicted MIC (XGBoost ML predictor — not a heuristic, scaffold-CV MAE 0.62), structural-alerts liability (PAINS+Brenk+NIH+Lipinski+Veber), drug-likeness (QED), synthesizability (SA score), hemolytic safety, structural novelty (Tanimoto Morgan FP), and semantic novelty (Gemini Embedding 2 cosine vs 20,489-row known-antibiotics index).
>
> Click "find similar known drugs" on any candidate to see the top-5 closest known antibiotics by cosine similarity. Useful for novelty checks and mechanism-of-action guesses.
>
> ## How it was trained
> Three-stage pipeline on a single AMD Instinct MI300X:
> 1. **Stage 1**: chemistry foundation on Therapeutics Data Commons (28 tasks).
> 2. **Stage 2**: AMR specialization on `lysos-amr-stage2-pro-v2` — 364K examples across 27 task types from 9 real sources, including a 333-entry elite chain-of-thought reasoning slice (14 reasoning task types, 25x oversampled).
> 3. **Stage 3**: GRPO RL with 8 verifiable reward components, all logged separately to wandb to detect reward-hacking.
>
> The MI300X 192 GB is the prerequisite — RL training peak is ~152 GB. An H100 80 GB has to shard.
>
> ## Resources
> - Code: github.com/Rahul-Rajpurohitk/lysos
> - Stage 2 v2 dataset: huggingface.co/datasets/rahul24raj/lysos-amr-stage2-pro-v2 (364,432 train + 29,300 valid + 55 held-out test)
> - Stage 3 prompts: huggingface.co/datasets/rahul24raj/lysos-rl-prompts (12,000 prompts)
> - Held-out reasoning eval: `examples/score_held_out_named_drug.py` (5-axis scoring)

---

## Submission checklist

- [ ] Copy A → X (kickoff post)
- [ ] Copy B → lablab portal "project description" field
- [ ] Copy C → `huggingface.co/spaces/lablab-ai-amd-developer-hackathon/lysos` README (auto-pushed by `make space-deploy`)
- [ ] PDF version of pitch deck: `docs/pitch-deck.pdf` (already rendered via `marp docs/pitch-deck.md --pdf`)
