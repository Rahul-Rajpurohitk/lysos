# Competitor Analysis

How Lysos compares to existing generative drug-design systems. The
positioning that the methods paper + pitch deck must articulate clearly.

## Comparison table

| System | Base | Specialization | Architecture | Reward / Training | AMR coverage | Workbench | Open weights |
|--------|------|----------------|--------------|-------------------|--------------|-----------|--------------|
| **Lysos** (this work) | Gemma 4 31B | AMR (8 priority pathogens) | Multi-agent (Designer, Critic, Strategist, Editor) + 25 tools | SFT + GRPO 12-component | ✅ Native | ✅ FastAPI + React | ✅ |
| TxGemma (Google 2024) | Gemma 2 7-27B | Therapeutic intent + ADMET | Single-LM | SFT only on TDC | ❌ Generic | ❌ | ✅ |
| Tx-LLM (Google 2024) | Gemma 2 70B | Multi-modal therapeutics | Single-LM | SFT only | ❌ Generic | ❌ | Partial |
| MolGPT (Bagal 2022) | Custom 6L Transformer | SMILES generation | Decoder-only | Standard MLE | ❌ Generic | ❌ | ✅ |
| ChemBERTa | RoBERTa | Property prediction | Encoder-only | MLM only | ❌ | ❌ | ✅ |
| GPT-4 (zero-shot) | OpenAI GPT-4 | General | Closed | RLHF | Limited zero-shot | ❌ | ❌ |
| Claude Opus (zero-shot) | Anthropic | General | Closed | Constitutional AI | Limited zero-shot | ❌ | ❌ |
| MoFormer / Moltransformer | BERT-class | Reaction prediction | Encoder-only | Standard | ❌ | ❌ | ✅ |
| ChemFormer (BioNeMo) | T5-base | Generative + retrosynthesis | Encoder-decoder | Standard | ❌ | ❌ | ✅ |

## Differentiator analysis

### vs TxGemma

Same base philosophy (Gemma + therapeutic specialization). TxGemma covers
**broad therapeutics** (28 TDC ADME/Tox tasks) but does NOT specialize in:
- Pathogen-target reasoning
- Multi-agent Workbench coordination
- 8-pathogen resistome / first-line therapy / escape mutation grounding
- Antimicrobial-specific reward components (predicted_mic, hemolysis,
  spectrum, resistance_robustness)
- Manual teacher distillation (we have 78K traces; TxGemma has none)

**Lysos advantage**: AMR specialization layer on top of TxGemma-class base.

### vs Tx-LLM

Tx-LLM is multi-modal (text + structure). Larger base (70B). Different goal
(therapeutic property prediction across modalities).

**Lysos advantage**: agentic Workbench + reward stack tuned for AMR design,
not property prediction.

### vs MolGPT

MolGPT is a SMILES generator. Single-task. No agent / tool / reasoning.

**Lysos advantage**: not just generating SMILES — reasoning, tool use,
clinical positioning, manufacturing analysis, regulatory awareness.

### vs ChemBERTa / MolFormer

These are property predictors (SMILES → numeric output). Encoder-only.
Cannot generate.

**Lysos advantage**: generation + reasoning + multi-task agentic system.

### vs GPT-4 / Claude zero-shot

GPT-4 + Claude can answer drug-design questions but with:
- No specialization for AMR (zero-shot retrieval from training cutoff)
- No tool-use specifically for chemistry tools (predict_mic_pathogen, etc.)
- No structured Workbench memory / ledger
- No GRPO-aligned design objective
- API cost per inference (~$0.01-0.10 per query at scale)

**Lysos advantage**: open-weight + zero-cost-per-inference + AMR-specialized
+ Workbench-aware. Closed model can't replicate the 12-component reward
calibration without training.

### vs ChemFormer / MoFormer

Reaction prediction + retrosynthesis. Different problem (we use
AizynthFinder for retrosynthesis as a tool, not as base model).

**Lysos advantage**: integrates retrosynthesis as ONE of 25 tools, plus
generation, reasoning, agent coordination.

## Lysos positioning statement

> Lysos is the first **agentic** drug-design system **specialized** for
> antimicrobial resistance, built on Gemma 4 with **78K manually-authored
> teacher distillation traces** across 7 layers, supervised by a
> **12-component GRPO reward stack** calibrated on real AizynthFinder
> retrosynthesis routes and Boltz-2 3D pose data, evaluated on **7
> quantitative leaderboard metrics** including OOD pathogens, adversarial
> robustness, and reasoning faithfulness. Unlike TxGemma's broad-therapeutic
> design or Tx-LLM's multi-modal property prediction, Lysos targets the
> specific pain point of new-antibiotic discovery: navigating the 8 WHO-
> priority pathogens' resistomes to design candidates that pivot AROUND
> first-line therapy classes.

## Benchmark plan (post-train)

| Metric | Lysos-RL | Gemma 4 zero | GPT-4 zero | Claude zero | TxGemma | Tx-LLM |
|--------|----------|--------------|-------------|-------------|---------|--------|
| chem_validity | TBD | ~70% (est) | ~85% (est) | ~85% (est) | ~80% (est) | ~88% (est) |
| novelty_tanimoto | TBD | TBD | TBD | TBD | N/A | N/A |
| mic_rmse_holdout | TBD | TBD | TBD | TBD | N/A (no AMR) | N/A |
| admet_pass_rate | TBD | TBD | TBD | TBD | TBD | TBD |
| tool_call_accuracy | TBD | N/A | TBD | TBD | N/A | N/A |
| refusal_robustness | TBD (target 100%) | TBD | TBD | TBD | N/A | N/A |
| reasoning_faithfulness | TBD | TBD | TBD | TBD | TBD | TBD |

`eval/comparative_benchmark.py` is set up to populate this table once
models are served.

## Citation

Lysos cites + builds on:
- Google DeepMind. TxGemma technical report 2024.
- Bagal et al. 2022. MolGPT: Molecular Generation Using a Transformer-Decoder Model. JCIM.
- Chithrananda et al. 2020. ChemBERTa-2: Towards Chemical Foundation Models. arXiv.
- Shao et al. 2024. DeepSeekMath / GRPO. arXiv:2402.03300.
