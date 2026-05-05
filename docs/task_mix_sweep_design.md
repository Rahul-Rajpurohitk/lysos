# Task-Mix Sweep — Experiment Design

The current `task_mix` weights in `configs/stage2_amr_sft.yaml` are
hand-tuned. This design doc specifies a sweep to find optimal weights
post-Stage-2-SFT.

## Hypothesis

Hand-tuned weights bias toward generation_for_target + activity_prediction
(combined 34% of mix). A sweep may reveal that more weight on agentic
multi-turn reasoning (long_form_designer_loop, three_way_dialogue) yields
better tool-call accuracy + reasoning faithfulness without hurting
chemistry validity / MIC accuracy.

## Sweep parameters

| Parameter | Values |
|-----------|--------|
| Generation weight | {0.10, 0.15, 0.18, 0.22, 0.30} |
| Activity weight | {0.10, 0.14, 0.16, 0.20} |
| Long-form weight | {0.05, 0.10, 0.15, 0.20} |
| Architecture weight | {0.05, 0.10, 0.15} |
| Eval-aligned weight | {0.05, 0.10, 0.15} |
| Other tasks (uniform) | remainder |

Total: 5 × 4 × 4 × 3 × 3 = **720 configurations**. Filter to ~30 that
satisfy: each weight ≥ 0.02, weights sum to 1.0, no individual task > 0.3.

## Procedure

1. **Train** a small Stage-2 SFT (5K steps, LoRA r=16) for each configuration
   - Total: 30 × ~30min = 15h compute
2. **Evaluate** each on 200-row dev split: 7-metric quick eval
3. **Score** = weighted avg of (chem_validity, novelty, MIC RMSE, ADMET,
   tool-call accuracy)
4. **Pick** the top-3 configurations
5. Run **full** Stage-2 SFT (12h) on each top-3
6. Final: pick the best-of-3 by full eval

## Compute budget

- Sweep: ~15h × 1× MI300X = ~$45-60
- Top-3 full: 3 × 12h × 1× MI300X = ~$108-144
- Total: ~$160-200 → ~50-65% of $300 budget

## Decision points

- If sweep reveals a single dominant configuration → run only that
- If sweep is flat (no significant improvement) → stick with hand-tuned
  weights, save the sweep budget
- If sweep reveals a non-obvious combo → document the surprise in methods
  paper

## Status

DEFERRED post-hackathon. Hand-tuned weights used for hackathon submission.
