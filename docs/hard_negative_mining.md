# Hard-Negative Mining for Lysos

## Why this matters

The Lysos 12-component reward stack defines what a "good" antibiotic candidate
looks like along several orthogonal axes. Naive RL optimizes the COMPOSITE,
which lets the policy collapse onto cheap myopic strategies:

  * Generate `Cl[H+]` → high `validity`, near-zero `predicted_mic`, but
    composite is non-zero so RL sticks with it.
  * Generate a known antibiotic with one atom changed → high
    `predicted_mic` and `drug_likeness_qed`, but `novelty=0`.
  * Generate a long peptidomimetic → high `predicted_mic` and `novelty`,
    but `synthesizability` is impossible — useless in the lab.

Each of these is a **Pareto trap**: looks good on a subset of components,
fails on at least one critical orthogonal axis. The composite reward
notices over the long run, but only after the model has wasted thousands
of GRPO steps exploring that trap.

**Hard-negative mining = pre-computing these traps and showing them to the
model as explicit DPO `rejected` examples** so it learns the orthogonal
axes faster, with much less RL spend.

## The 12 components and known cognitive traps

Reward stack (sums to 1.0 in `configs/stage3_rl_grpo.yaml`):

```
validity              0.05  — "is this a parseable SMILES at all"
structural_alerts     0.05  — Brenk/PAINS reactive groups
predicted_mic         0.20  — kill activity vs target pathogen (xgboost)
drug_likeness_qed     0.05  — QED rule-of-5 friendliness
synthesizability      0.10  — can a chem lab actually make this (SAscore + AiZynth)
hemolysis_safety      0.10  — RBC lysis risk (xgboost on 8K dataset)
novelty               0.10  — Tanimoto distance from known antibiotics
embedding_novelty     0.10  — Gemini Embedding 2 cosine novelty
boltz2_pose_conf      0.05  — does the molecule actually dock to the target
spectrum_breadth      0.10  — works against >1 priority pathogen
resistance_robustness 0.05  — keeps activity under known escape mutations
pareto_entry          0.05  — joint Pareto-front membership across the above
```

**The critical axis pairs (anti-correlations the policy can game):**

| Pair                         | Trap pattern                                | Why it's hard |
|------------------------------|---------------------------------------------|---------------|
| MIC × hemolysis              | High kill + kills red blood cells           | Kill mechanism is often membrane disruption — kills *everything*  |
| MIC × synthesizability       | Active in silico, impossible to synth       | xgboost rewards exotic functional groups; chemists can't make them |
| novelty × validity           | Brand-new scaffold but invalid valence      | Diverse-sampling explores invalid space first |
| novelty × QED                | New scaffold but breaks rule-of-5           | Most truly novel space is non-druglike |
| pose × MIC                   | Docks well but doesn't bind kinetically    | Static pose ≠ activity; many poses are spurious |
| spectrum × resistance_robust | Wide spectrum but loses to one mutation     | Wide spectrum often = single conserved target |
| structural_alerts × novelty  | Novel because it has reactive PAINS group   | PAINS = unprecedented = high novelty score |
| hemolysis × QED              | Looks druglike but is amphipathic           | Membrane-active drugs often pass QED filter |

## Mining algorithm

```
INPUT:
    rl_prompts: list[str]              # Stage 3 RL prompt corpus
    generator: LysosGenerator          # current best policy (or Gemma 4 base)
    K_per_prompt: int = 20             # candidates per prompt
    reward_fn: CompositeReward         # 12-component stack

OUTPUT:
    pairs: list[(prompt, chosen, rejected, hard_axis)]

ALGORITHM:
    for prompt in rl_prompts:
        candidates = generator.sample(
            prompt, K=K_per_prompt,
            temperature=[0.5, 0.7, 0.9, 1.2, 1.5]   # diverse temperatures
            top_p=0.95
        )
        scores = reward_fn(candidates)               # K x 12 matrix

        # For each axis pair, find the trap candidates
        for (X, Y) in HARD_AXIS_PAIRS:
            # rejected = top-quartile on X but bottom-quartile on Y
            x_high = quartile_mask(scores[:, X], q=0.75, direction="above")
            y_low  = quartile_mask(scores[:, Y], q=0.25, direction="below")
            trap_idx = x_high & y_low
            if trap_idx.sum() == 0: continue

            # chosen = balanced (top-quartile on COMPOSITE; not in trap)
            comp = scores @ weights
            top_comp = top_k(comp, k=3)
            balanced = top_comp - trap_idx          # exclude trap candidates

            for r in trap_idx.argmax():             # hardest of the traps
                for c in balanced[:1]:              # best balanced
                    pairs.append((prompt, candidates[c], candidates[r],
                                  hard_axis=(X,Y)))

    return pairs
```

Diversity controls:
  * Multi-temperature sampling expands the candidate distribution.
  * We keep at most 3 pairs per (prompt, axis) so popular prompts don't
    dominate the dataset.
  * We dedup by InChIKey on both `chosen` and `rejected` to avoid the
    same molecule appearing on both sides.

## Output format

Parquet with columns:
```
prompt           str   — Stage 3 RL prompt
chosen           str   — winning completion (full text incl SMILES: ...)
rejected         str   — losing completion (Pareto trap)
chosen_smiles    str   — extracted SMILES from chosen
rejected_smiles  str   — extracted SMILES from rejected
chosen_scores    json  — 12-component breakdown for chosen
rejected_scores  json  — 12-component breakdown for rejected
chosen_composite  float
rejected_composite float
hard_axis_x      str   — name of the X-component
hard_axis_y      str   — name of the Y-component (the one rejected fails)
gap_x            float — chosen[X] - rejected[X]
gap_y            float — chosen[Y] - rejected[Y]
```

This format is consumed directly by TRL's `DPOTrainer`.

## How we use it

**Two paths, both run before final GRPO:**

### Path A — Stage 2.5 DPO alignment
Insert a short DPO step between Stage 2 SFT and Stage 3 GRPO. Typically
1 epoch over 5K-20K pairs, ~30-60 min on 1× MI300X. The model learns to
prefer balanced candidates over Pareto-trap candidates, which means GRPO
starts from a much better policy.

Config: `configs/stage2_5_dpo.yaml`
Run:    `python -m src.training.stage2_5_dpo --config configs/stage2_5_dpo.yaml`

### Path B — RL prompt augmentation
Augment Stage 3 GRPO prompts with examples of "fix this Pareto trap"
prompts. The model gets explicit signal "here's a candidate that scored
high on X but low on Y — propose an alternative that keeps X high AND
fixes Y." This is added to `rl_prompts_v3` to produce `rl_prompts_v4`.

We pick path A (DPO) because:
1. It's a proper RL pre-training objective; doesn't depend on prompt design.
2. DPO is well-understood and has TRL support out of the box.
3. The Pareto signal is encoded directly in the loss, not just shown
   in-context.

We may add path B later if there's GRPO budget left after Stage 3.

## Sample sizes + cost

| Stage         | Candidates | Pairs   | Time on 1× MI300X    | Cost ($3/h) |
|---------------|------------|---------|----------------------|-------------|
| Mining        | 12K prompts × 20 = 240K | ~10K  | ~6h (gen+score)     | $18         |
| DPO training  | 10K pairs × 1 epoch     | n/a   | ~1h                 | $3          |

So adding hard-negative DPO costs ~$21 and adds an alignment layer that
GRPO would otherwise spend ~$50-100 of compute fumbling toward.

## Validation

Before running mining at scale, smoke test:

```bash
python scripts/mine_hard_negatives.py \
    --prompts data/processed/rl_prompts_v3 \
    --max_prompts 16 \
    --candidates_per_prompt 4 \
    --out /tmp/hard_negatives_smoke.parquet \
    --use_stub_generator   # for CI; replace with --model_id rahul24raj/lysos-base on VM
```

This runs on CPU in ~30s and produces a small parquet for inspection.

## Future extensions

  * **Adversarial scaffold attack**: deliberately ask the policy to find
    "a molecule that looks similar to penicillin but kills RBCs" — used
    as an out-of-distribution probe.
  * **Mutation hard-negatives**: take a chosen candidate, mutate one
    functional group, score, treat as rejected if score drops past
    threshold.
  * **Cross-pathogen transfer**: candidates that work on MRSA but fail
    on Mtb — train spectrum_breadth-aware policy.
