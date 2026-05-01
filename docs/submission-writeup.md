# Lysos — submission writeups (3 lengths)

The lablab portal asks for a project description and HF Space wants a card.
Pre-written here; copy-paste at submission time.

---

## A. 280 characters (one tweet)

> Lysos: open-source generative drug designer for antimicrobial resistance.
> Gemma 4 31B + RL with verifiable rewards on a single AMD MI300X.
> 96K SFT examples, 8 priority pathogens, two Gemma models coresident.
> github.com/Rahul-Rajpurohitk/lysos

(279 chars — fits on X)

---

## B. 1500 characters (lablab submission portal)

> **Lysos** is an open-source generative drug designer for antimicrobial resistance.
>
> Antimicrobial resistance kills 1.27M people every year today, projected to reach 10M/year by 2050. Pharma has largely abandoned antibiotic R&D. Lysos uses generative AI to design novel antibacterial molecules in seconds against drug-resistant pathogens, with publicly verifiable activity scores.
>
> **Built on Gemma 4 31B-it**, fine-tuned in three stages on a single AMD Instinct MI300X:
> 1. **Stage 1 — TxGemma-4 chemistry foundation** (Therapeutics Data Commons, ~50 tasks)
> 2. **Stage 2 — AMR specialization SFT** on 222,606 instruction examples drawn from 7 real public sources (ChEMBL, DBAASP, DRAMP, DrugBank, CARD, PDB, ZINC)
> 3. **Stage 3 — GRPO reinforcement learning** with 7 verifiable reward components: validity, drug-likeness (QED+Lipinski), synthesizability, hemolysis safety, predicted MIC, Tanimoto novelty, and EmbeddingGemma-300m semantic novelty
>
> **Why MI300X**: the GRPO step holds policy + reference + reward predictor coresident — peak ≈152 GB. An H100 80 GB has to shard. The MI300X 192 GB fits the entire training stack on a single card.
>
> **Two Gemma-family models on one GPU**: Gemma 4 31B for generation (62 GB FP16) + EmbeddingGemma 300m for retrieval, novelty, and a "find similar drugs" UI feature (1 GB).
>
> **Open**: Apache-2.0 weights, public dataset on HF Hub, MIT-licensed code on GitHub, reproducible Docker image. Runs end-to-end on AMD Developer Cloud at <$240 per training run.

(~1,490 chars)

---

## C. ~250 words (HF Space card README)

> # Lysos — generative drug designer for antimicrobial resistance
>
> Built on Gemma 4 31B + EmbeddingGemma 300m, RL-tuned on AMD Instinct MI300X.
>
> ## What it does
> Pick a target pathogen (MRSA, M. tuberculosis, ESBL+ E. coli, K. pneumoniae CRE, A. baumannii, P. aeruginosa, VRE, N. gonorrhoeae). Lysos generates 50 candidate antibacterial molecules in under 30 seconds, each scored on six dimensions: predicted MIC, drug-likeness, synthesizability, hemolytic safety, structural novelty (Tanimoto), and semantic novelty (EmbeddingGemma cosine distance to a 20,489-row known-antibiotics index).
>
> Click "find similar known drugs" on any candidate to see the top-5 closest known antibiotics by cosine similarity. Useful for novelty checks and mechanism-of-action guesses.
>
> ## How it was trained
> Three-stage pipeline on a single AMD Instinct MI300X:
> 1. **Stage 1**: chemistry foundation on Therapeutics Data Commons.
> 2. **Stage 2**: 222,606 AMR instruction-tuning examples from 7 real public sources.
> 3. **Stage 3**: GRPO reinforcement learning with 7 verifiable reward components, all logged separately to wandb to detect reward-hacking.
>
> The MI300X 192 GB is the prerequisite — RL training peak is ~152 GB. An H100 80 GB has to shard.
>
> ## Resources
> - Code: github.com/Rahul-Rajpurohitk/lysos
> - Stage 2 dataset: huggingface.co/datasets/rahul24raj/lysos-amr-stage2 (222,606 ex.)
> - Stage 3 prompts: huggingface.co/datasets/rahul24raj/lysos-rl-prompts (12,000 prompts)

---

## Submission checklist

- [ ] Copy A → X (kickoff post)
- [ ] Copy B → lablab portal "project description" field
- [ ] Copy C → `huggingface.co/spaces/lablab-ai-amd-developer-hackathon/lysos` README (auto-pushed by `make space-deploy`)
