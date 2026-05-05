# Lysos — Master Execution Plan

> Single source of truth for what's locked in, what's running, and what
> fires next. Updated continuously alongside `TECH_DOC.md`.

## Lock-in summary (as of 2026-05-05)

| Component               | Choice                              | Status |
|-------------------------|-------------------------------------|--------|
| Base LLM                | `google/gemma-4-31b-it`             | ✓ on disk (62 GB) |
| Fine-tune method        | LoRA across 4 stages                | ✓ wired |
| Adapter chain           | S1 → S2 → S2.5 (DPO) → S3 (GRPO)    | ✓ configs chained |
| Embedding model         | `gemini-embedding-2` (3072-d, 8192-token input, multimodal) | ✓ codebase pinned |
| Embedding template      | A2 — structural + physicochem (~150 tok/row) via `src/embeddings/enrichment.py` | ✓ shared utility, 5 call sites |
| Stage 1 / 2 max_seq_length | 4096 → **8192** | ✓ bumped |
| Stage 3 prompt / completion | 1024 / 512 → **2048 / 1024** | ✓ bumped |
| Stage 2.5 DPO prompt / max | 768 / 2048 → **1024 / 4096** | ✓ bumped |
| Pro-v12 corpus          | locked, no TxGemma dilution          | ✓ kept |
| Stack pairing           | Gemini Embedding 2 + Gemma 4 31B    | confirmed by user |

## Budget — Gemini API ($10 prepaid; ~$4 of work locked in)

| Use                                              | Spend         | Status   |
|--------------------------------------------------|---------------|----------|
| Gemini Embedding 2 — precompute 30K refs (rich text) | ~$0.20    | running now |
| Gemini Embedding 2 — Stage 3 query embeddings    | ~$0.02        | post-train |
| Gemini Embedding 2 — eval / hard-neg miner       | ~$0.07        | post-train |
| Gemini 2.5 Pro — comparator (200-prompt zero-shot baseline) | ~$1.25 | scripted, runs after Stage 3 |
| Gemini 2.5 Pro — mechanism enrichment (top 200 named drugs) | ~$1.50 | scripted, runs anytime |
| Gemini 2.5 Pro — LLM-as-judge (50 held-out responses) | ~$1.00   | scripted, runs after Stage 3 |
| Buffer for retries + experiments                 | ~$5.96        | reserved |
| **Total committed**                              | **~$4.04**    | of $10 prepaid |

## Compute budget — AMD MI300X ($300; ~$222 committed)

| Stage                     | Hardware       | Wall  | Cost  | Output |
|---------------------------|----------------|-------|-------|--------|
| Stage 1 — TxGemma SFT     | 8× MI300X Large | ~6h  | ~$144 | `rahul24raj/txgemma-4-31b` |
| Stage 2 — AMR SFT pro-v12 | 1× MI300X Small | ~12h | ~$36  | `rahul24raj/lysos-base` |
| Stage 2.5 — mine + DPO    | 1× MI300X Small | ~1h  | ~$3   | `rahul24raj/lysos-base-dpo` |
| Stage 3 — GRPO RL         | 1× MI300X Small | ~12h | ~$36  | `rahul24raj/lysos-rl` |
| Eval + leaderboard render | 1× MI300X Small | ~1h  | ~$3   | reports/leaderboard.html |
| **Total**                 |                |       | **~$222** | $78 buffer |

## Files added / changed in this round

```
NEW
  src/embeddings/enrichment.py            shared template; 5 call sites use it
  scripts/run_gemini_comparator.py        Gemini 2.5 Pro zero-shot baseline
  scripts/enrich_named_drugs_with_gemini.py  Gemini 2.5 Pro mechanism enrichment
  scripts/llm_as_judge_eval.py            Gemini 2.5 Pro qualitative critic

CHANGED — model pin (gemini-embedding-001 → gemini-embedding-2)
  src/embeddings/gemini.py                MODEL_NAME constant
  src/embeddings/__init__.py              docstring
  src/eval/rewards/embedding_novelty.py   reward fn + load precompute path
  src/inference/retrieval.py              IndexedDoc.as_document_text uses
                                          shared enrichment
  scripts/precompute_embeddings.py        rich-text via build_document_text
  scripts/verify_keys.py                  test endpoint
  scripts/dedup_with_embeddings.py        model id
  scripts/build_known_antibiotics_index.py model id
  workspace/api/server.py                 docstring

CHANGED — context bumps (4K → 8K Gemma 4)
  configs/stage1_txgemma4.yaml            max_seq_length 4096 → 8192
  configs/stage2_amr_sft.yaml             max_seq_length 4096 → 8192
  configs/stage3_rl_grpo.yaml             max_prompt 1024→2048, max_compl 512→1024
  configs/stage2_5_dpo.yaml               max_length 2048→4096, max_prompt 768→1024
```

## Execution order on the AMD MI300X

```
0. Local (now, before VM)
   ✓ verify_keys.py            green (HF + Gemini-2 + WANDB + Anthropic)
   ✓ precompute_embeddings.py  running — produces artifacts/embeddings/
                               known-antibiotics-gemini.parquet

1. Provision Large 8× MI300X
   bash scripts/vm_bootstrap.sh
     → ROCm check, deps, key verify, dataset pulls, reward cache pulls,
       Gemma 4 31B-it pre-warm, smoke tests
   bash scripts/run_training_pipeline.sh stage1
     → ~6h, $144, pushes rahul24raj/txgemma-4-31b
   spin down  →  $144 spent

2. Provision Small 1× MI300X
   bash scripts/vm_bootstrap.sh
   bash scripts/run_training_pipeline.sh stage2     # ~12h, $36 → lysos-base
   bash scripts/run_training_pipeline.sh stage2_5   # mine + DPO, $3 → lysos-base-dpo
   bash scripts/run_training_pipeline.sh stage3     # ~12h, $36 → lysos-rl

3. Eval + comparator + judge
   python eval/run_all.py
   python scripts/run_gemini_comparator.py --out reports/gemini_25_pro_baseline.jsonl
   python scripts/llm_as_judge_eval.py --responses reports/lysos_rl_responses.jsonl \
                                       --out reports/lysos_rl_judge_scores.jsonl
   python scripts/enrich_named_drugs_with_gemini.py     # one-time
   python scripts/save_artifacts_locally.py             # mirror everything

4. Deploy
   vllm serve rahul24raj/lysos-rl  --port 8000  --max-model-len 8192
   workspace/api/server.py         points LYSOS_INFERENCE_URL at the VM
```

## Safety nets — already wired

```
preflight_check.py     gates all 4 stages on keys + deps + datasets + reward stack
checkpoint_resilience  3-retry per stage + HF Hub recovery on local corruption
cost_callback          emits cost/* to wandb each step; hard-stops at $315
hub_push_with_retry    4-retry exponential + read-after-write verify
killswitch.py          --soft / --hard / --wipe-all from a remote laptop
wandb_monitor.py       list / status / tail / alert / diff
verify_keys.py         live HTTP per credential; vm_bootstrap fails fast on missing
```

## Test status (pre-launch)

```
  9   workspace/tests/test_agentic_flow.py
  9   workspace/tests/test_server_hardening.py
 12   workspace/tests/test_sandbox.py
 10   scripts/tests/test_safety_nets.py
  4   scripts/tests/test_hard_negative_mine.py
  4   scripts/test_loss_masking.py (separate runner)
  e2e scripts/smoke_pipeline_e2e.py — S1 → S2 → S2.5 → S3 on tiny-gpt2 in ~30s

 57+ tests + e2e all green
```

## What's still pending (you action)

- AMD MI300X VM SSH access — when ready, drop me the command and I drive
  the rest from `bash scripts/vm_bootstrap.sh` onward.
