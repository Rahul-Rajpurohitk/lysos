---
slug: scenarios/eval
loaded_when: "user intent is one of: evaluate, benchmark, compare, leaderboard, eval, test, baseline"
---

# Scenario: Evaluate

User wants quantitative comparison: Lysos-RL vs baselines, model
ablations, candidate vs known drug.

## Inputs needed

- **What** to compare (Lysos-RL vs Gemini Pro? Stage 2 vs Stage 3?)
- **On what** prompts (test holdout? OOD set? adversarial?)
- **How** scored (composite reward? LLM-as-judge? both?)

## Workflow A — head-to-head model comparison

1. Load `reports/gemini_25_pro_baseline.jsonl` (already computed: 99
   prompts × Gemini Pro answer + thinking trace).
2. Run Lysos-RL on same prompts via `LYSOS_INFERENCE_URL` (vLLM).
3. Render side-by-side panel: prompt → both answers → both scores.
4. Run `llm_as_judge_eval.py` for 4-axis qualitative scores.
5. Roll-up: mean composite + win-rate per axis + per task type.

## Workflow B — adapter ablation

1. List adapters under `./checkpoints/`: stage1, stage2, stage2.5, stage3.
2. For each, fire the eval prompts and accumulate per-stage scores.
3. Render bar chart: which stage contributed which delta to which axis.

## Workflow C — single-candidate comparator

1. User pastes a SMILES.
2. `/score` it.
3. `/similar` to find 3 closest known drugs.
4. Render: candidate vs each match: composite delta + axis-by-axis diff.

## Output

Right-panel artifact:
- Markdown summary at top (headline numbers)
- Embedded leaderboard table
- Embedded radar plot if axis-by-axis
- Provenance footer (which Lysos adapter, which judge model, when run)
