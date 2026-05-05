"""Stage 3 — GRPO RL training with verifiable rewards.

Group Relative Policy Optimization (DeepSeek-R1 style). For each prompt, the
model generates G samples; rewards are computed for each; advantages are
group-normalized (no value model needed); the policy updates against a KL
constraint to a frozen reference.

This is THE stage where MI300X 192 GB is mandatory:
  - Policy model (~62 GB BF16)
  - Frozen reference model (~62 GB BF16)
  - Activations + gradients during gen + grad step
  - KV cache for G generations per prompt
  Total > 150 GB during training. H100 80 GB cannot fit. We can.

Run on AMD Dev Cloud (Small 1x MI300X):

    python -m src.training.stage3_rl_grpo --config configs/stage3_rl_grpo.yaml

Smoke-test on 8 prompts:

    python -m src.training.stage3_rl_grpo \
        --config configs/stage3_rl_grpo.yaml \
        --smoke-test
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] stage3 | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("stage3")


def parse_args() -> argparse.Namespace:
    from src.config import add_config_args

    p = argparse.ArgumentParser(description="Stage 3 - GRPO RL on Lysos base")
    add_config_args(p)
    p.add_argument("--dry-run", action="store_true", help="Load config + reward fns + exit")
    p.add_argument("--smoke-test", action="store_true",
                   help="Train 8 prompts to verify the loop")
    p.add_argument("--resume-from", type=str, default=None)
    p.add_argument("--reward-only", action="store_true",
                   help="Skip training; just score samples from a file")
    p.add_argument("--reward-input", type=str, default=None,
                   help="When --reward-only: path to file of model outputs (one per line)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    from src.config import apply_cli_overrides, load_config
    from src.eval.rewards import CompositeReward

    log.info("Loading config: %s", args.config)
    cfg = load_config(args.config)
    cfg = apply_cli_overrides(cfg, args.override)

    if args.dry_run:
        print(json.dumps(cfg, indent=2, default=str))
        return 0

    log.info("Building composite reward function with %d components", len(cfg.reward.components))
    reward_fn = CompositeReward(
        components=cfg.reward.components,
        on_error=cfg.reward.get("on_error"),
    )

    if args.reward_only:
        if not args.reward_input:
            log.error("--reward-only requires --reward-input")
            return 1
        with open(args.reward_input) as f:
            samples = [line.rstrip("\n") for line in f if line.strip()]
        log.info("Scoring %d samples", len(samples))
        combined, per_component = reward_fn(samples)
        for i, (s, r) in enumerate(zip(samples, combined)):
            comps = ", ".join(f"{name}={vals[i]:.3f}" for name, vals in per_component.items())
            print(f"[{r:+.3f}]  {comps}\n  {s[:120]}{'...' if len(s) > 120 else ''}\n")
        return 0

    log.info("Importing torch + transformers + trl + peft + datasets ...")
    t0 = time.perf_counter()
    import torch
    from datasets import load_from_disk, load_dataset
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    try:
        from trl import GRPOConfig, GRPOTrainer
    except ImportError as exc:
        log.error("TRL GRPOTrainer not available - upgrade trl >= 0.11: %s", exc)
        return 2

    log.info("Imports done in %.1fs", time.perf_counter() - t0)

    torch.manual_seed(cfg.training.seed)

    os.environ.setdefault("WANDB_PROJECT", cfg.wandb.project)
    os.environ.setdefault("WANDB_NAME", cfg.run_name)
    if cfg.wandb.tags:
        os.environ.setdefault("WANDB_TAGS", ",".join(cfg.wandb.tags))

    log.info("Loading tokenizer: %s", cfg.model.base_id)
    tok = AutoTokenizer.from_pretrained(cfg.model.base_id, use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    log.info("Loading policy: %s (dtype=%s)", cfg.model.base_id, cfg.model.dtype)
    dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[cfg.model.dtype]
    model_kwargs = dict(
        torch_dtype=dtype,
        device_map="auto",
        trust_remote_code=cfg.model.trust_remote_code,
        use_cache=False,
    )
    if cfg.model.attn_impl == "flash_attention_2":
        model_kwargs["attn_implementation"] = "flash_attention_2"

    policy = AutoModelForCausalLM.from_pretrained(cfg.model.base_id, **model_kwargs)

    existing = cfg.peft.get("load_existing_adapter") if hasattr(cfg.peft, "get") else None
    if existing:
        log.info("Loading + merging Stage 2 LoRA: %s", existing)
        policy = PeftModel.from_pretrained(policy, existing)
        policy = policy.merge_and_unload()

    if cfg.peft.enabled:
        lora_cfg = LoraConfig(
            r=cfg.peft.r,
            lora_alpha=cfg.peft.alpha,
            lora_dropout=cfg.peft.dropout,
            bias=cfg.peft.bias,
            task_type=cfg.peft.task_type,
            target_modules=list(cfg.peft.target_modules),
        )
        policy = get_peft_model(policy, lora_cfg)
        policy.print_trainable_parameters()

    if cfg.training.gradient_checkpointing:
        policy.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})

    log.info("Loading frozen reference: %s", cfg.model.reference_model_id)
    ref_kwargs = dict(model_kwargs)
    reference = AutoModelForCausalLM.from_pretrained(cfg.model.reference_model_id, **ref_kwargs)
    for p in reference.parameters():
        p.requires_grad_(False)
    reference.train(False)

    log.info("Loading prompts: %s", cfg.dataset.path)
    if cfg.dataset.source == "local":
        ds = load_from_disk(cfg.dataset.path)
    elif cfg.dataset.source == "hub":
        ds = load_dataset(cfg.dataset.hub_id)
    else:
        raise ValueError(f"unknown dataset source: {cfg.dataset.source}")

    train_ds = ds[cfg.dataset.split_train] if cfg.dataset.split_train in ds else ds["train"]
    eval_ds = ds[cfg.dataset.split_eval] if cfg.dataset.split_eval in ds else None

    if args.smoke_test:
        log.info("SMOKE TEST: 8 prompts only")
        train_ds = train_ds.select(range(min(8, len(train_ds))))
        if eval_ds:
            eval_ds = eval_ds.select(range(min(4, len(eval_ds))))

    log.info("Train prompts: %d", len(train_ds))
    log.info("Eval  prompts: %d", len(eval_ds) if eval_ds else 0)

    # Survival counters — log how often we fall back so we can spot silent
    # degradation (e.g. RDKit OOM on a specific scaffold class).
    _rwd_state = {"crashes_total": 0, "fallback_total": 0, "calls": 0}

    def reward_callable(prompts: list[str], completions: list[str], **_: Any) -> list[float]:
        """Robust GRPO reward wrapper.

        Per-sample isolation: if scoring one sample raises, only that sample
        gets reward=0; the rest of the batch is unaffected. If the entire
        composite fn crashes (rare, e.g. xgboost segfault), every sample in
        the batch gets 0 and we count the crash but DON'T raise — losing one
        step of an RL run is acceptable; killing a 10h training run is not.
        """
        _rwd_state["calls"] += 1
        try:
            combined, per_component = reward_fn(completions)
        except Exception as exc:  # noqa: BLE001
            _rwd_state["crashes_total"] += 1
            log.error(
                "[reward_callable] composite reward raised: %s -- "
                "returning zeros for this batch (n=%d, crashes_total=%d).",
                exc, len(completions), _rwd_state["crashes_total"],
            )
            try:
                import wandb
                if wandb.run is not None:
                    wandb.log({"reward/crashes_total": _rwd_state["crashes_total"]},
                              commit=False)
            except Exception:
                pass
            return [0.0] * len(completions)

        # Defensive: if composite returned a wrong length, pad/truncate.
        if len(combined) != len(completions):
            log.warning(
                "[reward_callable] reward fn returned %d values for %d completions; padding zeros",
                len(combined), len(completions),
            )
            n = len(completions)
            combined = (list(combined) + [0.0] * n)[:n]

        # Replace any NaN/Inf with 0 (RL gradient blow-up protection).
        import math
        n_bad = 0
        for i, v in enumerate(combined):
            if not math.isfinite(v):
                combined[i] = 0.0
                n_bad += 1
        if n_bad:
            _rwd_state["fallback_total"] += n_bad
            log.warning("[reward_callable] %d non-finite rewards zeroed (total=%d)",
                        n_bad, _rwd_state["fallback_total"])

        try:
            import wandb
            if wandb.run is not None:
                avg = {f"reward/{name}": sum(vals) / len(vals)
                       for name, vals in per_component.items()}
                avg["reward/non_finite_zeroed"] = _rwd_state["fallback_total"]
                avg["reward/crashes_total"] = _rwd_state["crashes_total"]
                wandb.log(avg, commit=False)
        except Exception:
            pass
        return combined

    grpo_args = GRPOConfig(
        output_dir=cfg.training.output_dir,
        num_train_epochs=cfg.training.num_train_epochs,
        per_device_train_batch_size=cfg.training.per_device_train_batch_size,
        gradient_accumulation_steps=cfg.training.gradient_accumulation_steps,
        gradient_checkpointing=cfg.training.gradient_checkpointing,
        learning_rate=cfg.training.learning_rate,
        lr_scheduler_type=cfg.training.lr_scheduler_type,
        warmup_ratio=cfg.training.warmup_ratio,
        weight_decay=cfg.training.weight_decay,
        optim=cfg.training.optim,
        max_grad_norm=cfg.training.max_grad_norm,
        bf16=cfg.training.bf16,
        logging_steps=cfg.training.logging_steps,
        save_strategy=cfg.training.save_strategy,
        save_steps=cfg.training.save_steps,
        save_total_limit=cfg.training.save_total_limit,
        eval_strategy=cfg.training.eval_strategy if eval_ds else "no",
        eval_steps=cfg.training.eval_steps,
        max_steps=cfg.training.get("max_steps", -1),
        report_to=list(cfg.training.report_to),
        seed=cfg.training.seed,
        run_name=cfg.run_name,
        push_to_hub=cfg.hub.push_to_hub,
        hub_model_id=cfg.hub.get("hub_model_id"),
        hub_private_repo=cfg.hub.private,
        num_generations=cfg.rl.num_generations,
        max_prompt_length=cfg.dataset.max_prompt_length,
        max_completion_length=cfg.dataset.max_completion_length,
        temperature=cfg.rl.temperature,
        top_p=cfg.rl.top_p,
        top_k=cfg.rl.top_k,
        beta=cfg.model.beta,
        use_vllm=cfg.rl.use_vllm,
    )

    trainer = GRPOTrainer(
        model=policy,
        ref_model=reference,
        reward_funcs=[reward_callable],
        args=grpo_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        tokenizer=tok,
    )

    # Cost protection — emits cost/* metrics + hard-stops over budget.
    try:
        from src.training.cost_callback import from_env as cost_from_env
        cb = cost_from_env()
        trainer.add_callback(cb)
        log.info("CostCallback armed: budget=$%.2f rate=$%.2f/h",
                 cb.budget_usd, cb.rate_per_hour)
    except Exception as exc:  # noqa: BLE001
        log.warning("CostCallback not attached: %s", exc)

    log.info("=" * 60)
    log.info("Starting GRPO: %s", cfg.run_name)
    log.info("=" * 60)
    t_train = time.perf_counter()
    trainer.train(resume_from_checkpoint=args.resume_from)
    log.info("Training done in %.1f minutes", (time.perf_counter() - t_train) / 60)

    log.info("Saving final adapter to %s", cfg.training.output_dir)
    trainer.save_model(cfg.training.output_dir)
    tok.save_pretrained(cfg.training.output_dir)

    # Persist GenerationConfig so the served Lysos-RL matches the
    # generation distribution we trained against.
    try:
        from transformers import GenerationConfig
        gen_cfg = GenerationConfig(
            do_sample=True,
            temperature=cfg.rl.temperature,
            top_p=cfg.rl.top_p,
            top_k=cfg.rl.top_k,
            max_new_tokens=cfg.dataset.max_completion_length,
            pad_token_id=tok.pad_token_id,
            eos_token_id=tok.eos_token_id,
        )
        gen_cfg.save_pretrained(cfg.training.output_dir)
        log.info("GenerationConfig saved (T=%.2f, top_p=%.2f, top_k=%d, max_new_tokens=%d)",
                 cfg.rl.temperature, cfg.rl.top_p, cfg.rl.top_k,
                 cfg.dataset.max_completion_length)
    except Exception as exc:  # noqa: BLE001
        log.warning("GenerationConfig save failed: %s", exc)

    # Persist final reward callable diagnostic counters
    log.info("Reward callable stats: calls=%d crashes=%d non_finite_zeroed=%d",
             _rwd_state["calls"], _rwd_state["crashes_total"], _rwd_state["fallback_total"])

    if cfg.hub.push_to_hub:
        from src.training.hub_push import push_with_retry
        ok = push_with_retry(
            trainer,
            repo_id=cfg.hub.hub_model_id,
            commit_message=f"GRPO RL complete - {cfg.run_name}",
            private=cfg.hub.private,
            max_retries=4,
            backoff_s=30.0,
        )
        if not ok:
            log.error("Hub push exhausted; LOCAL CHECKPOINT PRESERVED at %s",
                      cfg.training.output_dir)
            log.error("Recover: huggingface-cli upload %s %s",
                      cfg.hub.hub_model_id, cfg.training.output_dir)
            return 3

    log.info("Stage 3 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
