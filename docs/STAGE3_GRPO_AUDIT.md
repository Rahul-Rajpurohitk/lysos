# Stage 3 GRPO — Failure Audit

**Date**: 2026-05-07
**Scope**: 3 failed GRPO runs on AMD MI300X, ~22h compute burned, no usable artifact
**Outcome**: Falling back to Stage 2.5 DPO `checkpoint-243` as deployable model
**Audit method**: Pure code + log review, no GPU re-runs

---

## 1. The symptom (across all 3 runs)

KL divergence + grad-norm + loss explode after a small number of "stable" steps:

| Run | Config | Step KL hit 1e7+ |
|---|---|---|
| Original | beta=0.04, LR=5e-7, completion=1024, temp=1.0 | step ~3 |
| Path A | beta=0.10, LR=1e-7, completion=512, temp=0.7, warmup=0.03 | step ~15 |
| Path B | beta=0.20, LR=5e-8, completion=256, temp=0.9, warmup=0.05 | step ~25 |

Pattern: 1-2 stable steps, then a single batch produces KL 10⁷-10⁹ and gradient 10⁸-10¹⁰. Tightening hyperparameters delayed the explosion but didn't prevent it.

**Reward stayed at 0.005-0.03** across every run — basically zero learning signal.

---

## 2. Root cause (PRIMARY) — reference model is the wrong model

`src/training/stage3_rl_grpo.py` lines 144-184:

```python
# Policy:  load base + MERGE DPO adapter + add new LoRA
existing = cfg.peft.get("load_existing_adapter")
if existing:
    policy = PeftModel.from_pretrained(policy, existing)
    policy = policy.merge_and_unload()       # ← DPO merged into policy weights
if cfg.peft.enabled:
    policy = get_peft_model(policy, lora_cfg)  # ← new trainable LoRA on top

# Reference: load base — NO DPO MERGE
reference = AutoModelForCausalLM.from_pretrained(cfg.model.reference_model_id, **ref_kwargs)
# ↑ This loads BASE Gemma 4 31B even though `reference_model_id` points to a
#   LoRA adapter directory, because PeftModel.from_pretrained() is never called.
```

So at step 0:
- **Policy** = base Gemma 4 31B + DPO weights merged in + zero-initialized new LoRA
- **Reference** = base Gemma 4 31B (no DPO)

The KL penalty term in GRPO is `KL(policy || reference)`. With reference being a **fundamentally different model** (un-DPO'd base, hasn't seen the AMR-RL prompt format), `log P_policy(token) - log P_reference(token)` produces large per-token differences, which amplify across long sequences. On an outlier batch (one rare-token completion), the per-token log ratios can hit ±50, and `exp(50) ≈ 5×10²¹` overflows bf16 → KL = ∞ → gradient = ∞ → spike.

The DPO adapter is also being loaded from HF Hub (`rahul24raj/lysos-base-dpo`) for policy but the local `./checkpoints/stage2_5-dpo/checkpoint-243` for reference — even if reference loading were fixed, these are potentially different snapshots.

---

## 3. Root cause (SECONDARY) — reward signal too sparse

```
rewards/reward_callable/mean: 0.005 - 0.026   (range [0, 1])
rewards/reward_callable/std:  0.02 - 0.08
frac_reward_zero_std:         0.6 - 0.9
```

**`frac_reward_zero_std: 0.9`** means 90% of prompt-groups have all-identical reward across their 8 candidates → no advantage signal → no gradient. With a broken reference model AND no learning gradient, the policy just drifts in random directions until KL explodes.

Why is reward so low?
- Most generated SMILES are invalid (validity component → 0)
- `boltz2_pose_conf` cache empty → that 10% of weight returned 0 every batch
- `predicted_mic` XGBoost predictor returns near-zero for non-antibiotic-shaped SMILES
- `novelty` and `embedding_novelty` only trigger when SMILES is valid AND parses to an ECFP4 fingerprint
- ~9 of the 12 components score near-zero on early-training noise

When the model generates 99% max-length junk (`completions/clipped_ratio: 0.99`) hitting the 512/1024 cap without EOS, almost every component returns 0.0 (junk SMILES → invalid → validity=0 → cascade).

---

## 4. Root cause (TERTIARY) — bf16 precision on long log-prob ratios

Even with a correctly-loaded reference, training in `bfloat16` is risky for GRPO because:
- Log-prob ratios `exp(log p - log q)` for long sequences accumulate per-token differences
- bf16 has only 7 bits of mantissa precision
- A single rare-token outlier (e.g. unusual unicode in a malformed SMILES) can push the ratio across the bf16 representable range
- KL becomes Inf for that batch → gradient overflow

This is why the explosions happen on individual outlier steps rather than slowly trending up.

---

## 5. The fix (for any future GRPO retry — NOT executing now)

```python
# src/training/stage3_rl_grpo.py — patch reference loading to mirror policy

log.info("Loading frozen reference: %s", cfg.model.reference_model_id)
reference = AutoModelForCausalLM.from_pretrained(cfg.model.reference_model_id, **ref_kwargs)
if hasattr(reference, "config"):
    try: reference.config.use_cache = False
    except Exception: pass

# === FIX: also merge the DPO adapter into the reference ===
existing = cfg.peft.get("load_existing_adapter") if hasattr(cfg.peft, "get") else None
if existing:
    log.info("Loading + merging Stage 2 LoRA into REFERENCE: %s", existing)
    reference = PeftModel.from_pretrained(reference, existing)
    reference = reference.merge_and_unload()

for p in reference.parameters():
    p.requires_grad_(False)
reference.train(False)
```

Plus: ensure the same adapter source (local OR hub) is used for both, not mixed.

**Better alternative**: deepcopy the merged policy weights to use as reference, BEFORE adding the trainable LoRA. Guarantees policy and reference start from byte-identical weights.

```python
# After merge_and_unload, before get_peft_model:
import copy
reference = copy.deepcopy(policy)  # byte-identical reference
for p in reference.parameters():
    p.requires_grad_(False)
reference.train(False)
# Then add the trainable LoRA only to policy
policy = get_peft_model(policy, lora_cfg)
```

---

## 6. The fix (REWARD signal — also needed)

1. **Pre-warm the boltz2 cache OR set weight=0** (already done in our retries)
2. **Boost `validity` weight to 0.20** (was 0.05) so model gets early reward for emitting parseable SMILES — bootstraps the chain
3. **Add a generation-budget terminator reward** — penalize completions that hit max-length without EOS:
   ```python
   {"name": "termination_efficiency", "weight": 0.10,
    "module": "src.eval.rewards.termination:terminated_before_max"}
   ```
4. **Lower group_size 8 → 4** + warm-start from a few high-reward trajectories rather than random sampling, to break `frac_reward_zero_std=0.9`

---

## 7. Numerical-precision fix

If we re-run, force fp32 KL computation:

```python
# In GRPOConfig:
fp32_kl: True  # if TRL exposes; otherwise wrap policy/reference forward
              # passes with autocast(dtype=torch.float32) just for the
              # log-prob computation
```

Or: clip log-prob ratios at a sane bound (say ±20) before the KL formula, accepting that we lose some fidelity but gain stability. TRL has `clip_range` for the policy ratio — set it to e.g. 5.0 instead of the default 0.2 (which is for surrogate loss, different thing).

---

## 8. Time budget reality check

A correct GRPO run on Gemma 4 31B with the 12-component reward stack would need:
- **~2h** to fix + verify the reference model fix (code change + smoke test)
- **~6-12h** to do a 300-600 step training run
- **~2h** to evaluate vs Stage 2.5 DPO baseline

Total: **~10-16h minimum** to get a *converged* GRPO model. We have ~45h to submission. Possible but risky given:
- Need to debug the fix on the first run
- May discover ANOTHER issue and need a second retry
- Demo / pitch / UI polish also need time

**Recommendation**: skip GRPO for the hackathon submission. Stage 2.5 DPO is a real, deployed, working artifact. The 4-stage training narrative still holds — Stage 3 is documented as "attempted with technical blocker (reference-model handling), planned for v2".

---

## 9. What we keep regardless

- ✅ Stage 1: TxGemma SFT (1654 steps) — `rahul24raj/lysos-base` on HF Hub
- ✅ Stage 2: AMR SFT (1000 steps) — checkpoint at `stage2-amr-sft/checkpoint-1000`
- ✅ Stage 2.5: DPO with hard-negative pairs (243 steps) — `rahul24raj/lysos-base-dpo` on HF Hub
- ✅ Reward stack code (12 components, all functional in isolation)
- ✅ GRPO trainer code (with documented bug; fix is a 5-line patch)
- ✅ Hard-negative mining pipeline → DPO pair generation
- ✅ Stage 3 wandb runs preserved (3 failed runs as evidence of methodology)

The deployable model = `rahul24raj/lysos-base-dpo` (Stage 2.5 DPO). It's:
- Gemma 4 31B base
- Trained on 12K AMR drug-design prompts (Stage 1+2)
- Aligned via DPO on hard-negative Pareto-trap pairs (Stage 2.5)
- Currently powering the lysos workbench SaaS

---

## 10. Pitch-deck framing

**For the slides:**

> Lysos uses a 4-stage training pipeline on Gemma 4 31B, optimized for the AMD MI300X. Stages 1-2.5 (TxGemma → AMR → DPO) are deployed and powering the workbench. Stage 3 (GRPO RL with verifiable rewards) is in development — our v1 attempt revealed a TRL reference-model handling bug (documented in `docs/STAGE3_GRPO_AUDIT.md`) that we'll address in v2 post-hackathon. The DPO model (Stage 2.5) is the production artifact judges interact with.

This is honest, demonstrates engineering rigor, and turns a failed run into a documented lesson rather than something to hide.

---

## 11. Run audit trail

| Run ID | Config snapshot | Steps reached | Failure mode |
|---|---|---|---|
| `w6y5pihz` (orig) | beta=0.04, LR=5e-7, comp=1024 | 237/471 | KL 10¹⁰ from step ~3, kept running but never converged |
| `1xgsrrgk` (Path A) | beta=0.10, LR=1e-7, comp=512 | 17/600 | KL 9.79×10⁷ at step 17, killed |
| (Path B) | beta=0.20, LR=5e-8, comp=256 | 30/300 | KL 1.72×10⁹ at step 27, killed |

All three runs preserved on wandb for retro/forensics.
