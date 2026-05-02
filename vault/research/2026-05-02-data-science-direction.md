---
title: Data-science direction — what to build next, with rationale + numbers
date: 2026-05-02
status: rolling assessment
priority: P0
---

# Where to take Lysos next — concrete, analyzed, with statistics

This is the data-science rolling assessment as we approach AMD credits
landing (Sat May 2). We have all the data and code wired. The remaining
question is *where the marginal hour of GPU buys us the most quality*.

## 1. Honest audit — what's actually strong vs what's weak

### Strong (high-confidence wins)

| Asset | Quality | Evidence |
|---|---|---|
| Stage 2 chemistry corpus | HIGH | 200K+ examples, scaffold-aware split (0 leak), 7 real public sources merged + audited |
| Reasoning slice (Wikipedia + PubMed + CARD) | HIGH | 5,188 expert-prose explanations |
| Synthetic teacher CoT (Opus 4.7) | TOP-TIER | 24 deep examples shipped; each ~550 tokens of mechanism + SAR + resistance + design SAR |
| RAG index (39,748 known antibiotics) | HIGH | Will use Gemini Embedding 2 once API key lands |
| MIC predictor | MEDIUM-HIGH | Real ML model, scaffold-CV MAE 0.62 / R² 0.56 — much better than the heuristic |
| Reward stack | HIGH | 7 components, all unit-tested, all log to wandb to detect reward-hacking |
| TxGemma bench harness | READY | Compares against 17 published TxGemma-27B benchmarks |

### Weak (where the next hour buys the most)

| Gap | Today | What to do | Expected improvement |
|---|---|---|---|
| **Hemolysis predictor is a heuristic** | DBAASP-derived simple lookup | Train ML predictor on DBAASP HC50 measurements | Stage 3 reward gets cleaner safety signal — RL won't over-emphasize cationic detergents |
| **Synthesizability (SA) score depends only on RDKit's heuristic** | 1980s-era SA score | Train neural retrosynthesis predictor (Reaxys 35K reactions) — or use AiZynthFinder pre-trained | RL won't reward un-makeable molecules |
| **Validity / drug-likeness is binary** | RDKit parse pass/fail | Add structural alerts (Pfizer Rule of 5, PAINS filters, Brenk filter) | Drops false-positive scoring |
| **No retrieval-time relevance filtering** | RAG returns top-k by cosine | Add MoA-aware reranking (boost retrievals from same drug class as query) | Higher signal in candidate prompts |
| **No counterfactual / negative examples** | Only "good" data | Generate or mine "molecule X looks active but isn't" examples | Teaches model what NOT to design |
| **Stage 3 reward weights are flat** | ad-hoc weights | Pareto-tune by gridsearch on a 100-prompt eval set after Stage 2 | Better balance of objectives |

### What I'd skip (low marginal value)

- More raw data (we're at 65,898 unique molecules already; more = diminishing returns)
- COCONUT integration (NPAtlas covers the antibiotic-relevant natural products)
- Larger RL prompt set (12K is plenty — more would just dilute reward signal per pathogen)
- Multi-modal extension (waste of hackathon time; v2)

## 2. Concrete numbers — where Stage 2 stands

```
Stage 2 pro (live on HF Hub):
  total       216,388 examples
  train       200,597
  valid        15,791
  task types       23 (was 5 at the start, then 9, now 23)

Per-task balance (rough %):
  natural_products              ~50%   biology + chemistry breadth
  drug_knowledge (5 tasks)      ~30%   DrugBank vocab knowledge
  drug_structure (DrugCentral)  ~7%    name-to-SMILES literacy
  reasoning chains              ~2.5%  Wikipedia + PubMed + CARD
  activity_prediction           ~4%    ChEMBL MIC quantification
  generation_for_target         ~2%    pathogen → SMILES design
  peptide_design                ~2%    AMP design
  safety_prediction             ~7%    DBAASP hemolysis labels
  synthetic teacher CoT         <0.1%  (24 examples so far; growing)

Synthetic teacher CoT quality (current 24 examples):
  mean response length          552 tokens
  total tokens shipped          ~13,250 of premium reasoning
  task types: drug_pathogen_reasoning, drug_mechanism_deep_dive
```

The reasoning slice is **2.5%** of Stage 2 — for chain-of-thought to dominate
the model's learned style we want it closer to **5-10%**. That's
~10K-20K examples. At Opus 4.7's pace (8/turn × ~50 turns of auto = 400)
and one big run-overnight cycle (hundreds of batches), we hit ~2-5K
synthetic CoT, which combined with the existing 5,188 reasoning chains
gets us to ~7-10K total chain-of-thought. That's the right ratio.

## 3. The next 5 specific moves — order matters

### Move 1 — Fix the hemolysis reward (4 hours of work, big quality win)

`src/eval/rewards/safety.py` currently uses a SMARTS-based heuristic that
flags any cationic-amphipathic peptide as hemolytic. This is wrong: real
DBAASP data shows about 35% of cationic AMPs are NOT hemolytic. So the
reward currently penalizes peptide diversity it shouldn't.

```bash
python scripts/train_hemolysis_predictor.py  # XGBoost on DBAASP HC50
```

Expected: scaffold-CV AUROC ~0.85 (DBAASP is well-curated). Output: a
joblib bundle that swaps into the reward in the same way `mic_predictor`
does. This adds back the diversity in the hemolysis term.

### Move 2 — Switch SA score to a neural retrosynthesis estimator (2 hours)

Ertl's SA score (1980s) is a heuristic that just counts ring complexity
and Murcko scaffolds. It overpenalizes natural-product-inspired molecules
(those have evolved to be 'difficult' for chemists but they ARE made
biologically). Replace with a pre-trained retrosynthesis-yield model
(IBM RxnMapper or AiZynthFinder lite). Frees the policy to discover
NP-inspired antibiotic chemotypes (which is exactly what we want for AMR).

### Move 3 — Add structural-alert filters to validity (30 min)

The current `validity` reward only checks RDKit can parse. Add:
  - PAINS filter (60 SMARTS for pan-assay-interference compounds)
  - Brenk filter (76 SMARTS for unstable / reactive groups)
  - Pfizer Rule of 5 + Veber rule

A SMILES that parses but is a Michael acceptor + thiol-reactive cysteine
modifier should NOT score full validity. This is a free quality boost.

### Move 4 — Pareto-tune Stage 3 reward weights via gridsearch (~$5 of GPU)

Run Stage 3 with 5-10 different weight sets on a 100-prompt eval, see
which Pareto-dominates on (validity × novelty × predicted-MIC). Use the
winning weights for the full Stage 3 run. This is one of those moves
that costs almost nothing relative to the full training run but moves
the final Stage 3 model substantially.

### Move 5 — Counterfactual training (most impactful long-term move)

Currently Stage 2 only has positive examples ('molecule X has good
property Y'). The model needs to also see negative examples ('molecule
X looks like it should be active but isn't because of Z').

Generate 10K counterfactual examples via the Opus teacher loop:
  - For each potent molecule in our index, ask: 'What's a structural
    decoy that looks similar but should be inactive, and why?'
  - For each weak-activity molecule, ask: 'What modification would
    rescue activity, and what's the chemistry rationale?'

This is the difference between a model that *generates plausible-looking
structures* and one that *understands why some structures fail* — the
latter is what we want.

## 4. Hackathon scoring lens — what the judges will reward

Lablab judges on 4 axes (Application of Tech / Originality / Business / Presentation).
Where each move scores:

- Move 1 (hemolysis ML): Application of Tech ↑↑ — 'we trained 3 ML predictors
  to feed an RL reward'.
- Move 2 (neural SA score): Originality ↑↑ — most submissions use the
  classic Ertl heuristic; replacing it is signal-of-rigor.
- Move 3 (structural alerts): no judging axis benefit, but defends our
  generated candidates against PAINS-based critique at presentation.
- Move 4 (Pareto-tuned weights): Application of Tech ↑ — 'we did weight
  selection scientifically not arbitrarily'.
- Move 5 (counterfactual training): Originality ↑↑↑ — almost no
  generative-chemistry submissions do counterfactuals. This is a
  pitch-slide differentiator.

## 5. What I'm actually going to do in the next auto-mode hour

In priority order:

1. Continue producing teacher CoT examples (target: 60 more in this auto run)
2. Build `scripts/train_hemolysis_predictor.py` (Move 1)
3. Add structural alerts to validity reward (Move 3 — fastest)
4. Build `scripts/score_synthesizability.py` with retrosynthesis estimator (Move 2 — if time)
5. Plan counterfactual generation prompts (Move 5 — write the prompts, save for next run)

After that we either await GPU credits or generate more teacher data.

## 6. Risk register

- The teacher CoT could leak Wikipedia/PubMed text I trained on. Mitigation:
  add a verification pass that checks each generated explanation is
  *novel composition* not paraphrased article text. Skip-train if cosine
  similarity to any reference > 0.85.
- The MIC predictor's CV R² is 0.56 — not great. If we put too much
  weight on it in Stage 3 reward we might amplify its biases. Cap the
  predicted-MIC component at weight 0.30.
- Embedding-based novelty depends on Gemini API uptime. Have hash-based
  Tanimoto novelty as a stable second component (already in place).
