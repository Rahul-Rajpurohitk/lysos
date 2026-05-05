# End-to-End Pipeline

Lysos has 7 sequential stages from sprint planning to model deployment.
Each stage has its own data artifacts, configs, and verification harness.

## Stage 0: Sprint Planning

- Define which (pathogen, target) campaigns to run
- Allocate compute / budget envelope per campaign
- Curate the resistome briefing + target PDBs
- Lock the constraint profile per campaign

**Artifacts**: sprint config YAML, campaign plan markdown in
`vault/plans/active/YYYY-MM-DD-<topic>.md`

## Stage 1: Data Prep (CPU)

- Source ingestion (ChEMBL, DrugBank, NPAtlas, DBAASP, DRAMP, etc.)
- Standardization (chemistry corpus cleanup: peptide-as-SMILES detection, stereo, tautomer)
- Synthetic data generation (decoys, augmentation, agentic traces, teacher distill)
- Dataset bake (`pro-vN`)
- Smoke tests + manifest hash

**Artifacts**: `data/processed/amr-stage2-pro-vN`, `MANIFEST.json`

## Stage 2: Stage-1 SFT (TxGemma-4)

- 8× MI300X, ~6h
- Replicate Google's TxGemma recipe on Gemma 4 base
- 28 ADME/Tox/HTS task instruction tuning
- Output: `rahul24raj/txgemma-4-31b`

## Stage 3: Stage-2 SFT (Lysos AMR-spec)

- 1× MI300X, ~12h
- SFT on `amr-stage2-pro-vN` (~380K rows for v10)
- Multi-task mixing per `task_mix` in config
- Response template: `<start_of_turn>model\n`
- Output: `rahul24raj/lysos-base`

## Stage 4: Stage-3 GRPO RL

- 1× MI300X, ~10h
- Group-relative policy optimization on `amr-rl-prompts-v3`
- 12-component reward stack (validity, MIC, ADMET, novelty, ...)
- Reference model = Stage 2 base (frozen)
- Output: `rahul24raj/lysos-rl`

## Stage 5: Eval Harness

- 7 quantitative leaderboard metrics:
  - chem_validity
  - novelty_tanimoto
  - MIC_RMSE
  - ADMET_pass
  - tool_call_accuracy
  - refusal_robustness
  - reasoning_faithfulness
- Locked configs (`eval/run_all.py` with `EVAL_CONFIG`)
- Pre-train baseline + post-train deltas

**Artifacts**: `reports/eval_v3.json`

## Stage 6: Deployment

- vLLM serving (rocm/vllm:latest container on MI300X)
- Lysos Workbench frontend (FastAPI + React/Vite)
- HF Space for public demo (Docker SDK)
- Model card + dataset card + manifest exposure

**Artifacts**: `workspace/api`, `workspace/web`, HF Space

## Feedback Loop (continuous)

- Wet-lab results inform predictor calibration
- User interventions trigger constraint updates
- Failure modes feed back into the eval harness
- Each loop produces a new sprint deliverable

## Reproducibility

Given (`git_sha`, `dataset_hash`, `reward_stack_version`), the same input +
training config will produce the same model output. The manifest captures
all three, so any reported metric is reproducible.
