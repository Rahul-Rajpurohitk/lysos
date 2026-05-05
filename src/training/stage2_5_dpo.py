"""Stage 2.5 — Direct Preference Optimization on hard-negative pairs.

Inserts a short DPO alignment step between Stage 2 (AMR SFT) and Stage 3
(GRPO RL). Trains on the hard-negative pair dataset produced by
`scripts/mine_hard_negatives.py`.

Why between 2 and 3:
  * Stage 2 SFT teaches the model the AMR domain.
  * Stage 2.5 DPO teaches the model to PREFER balanced candidates over
    Pareto-trap candidates. The DPO loss directly encodes that
    "high-X-low-Y is worse than balanced", which GRPO would otherwise
    spend many expensive RL steps fumbling toward.
  * Stage 3 GRPO refines policy on the verifiable reward stack — but
    starts from a much better initialization.

Run on AMD Dev Cloud (Small 1x MI300X, ~30-60 min for 10K pairs):

    python -m src.training.stage2_5_dpo --config configs/stage2_5_dpo.yaml

Outputs:
  * LoRA adapter at cfg.training.output_dir
  * Pushed to HF Hub as rahul24raj/lysos-base-dpo
  * Wandb run with dpo/* metrics
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] stage2.5 | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("stage2.5")


def parse_args() -> argparse.Namespace:
    from src.config import add_config_args

    p = argparse.ArgumentParser(description="Stage 2.5 — DPO hard-negative alignment")
    add_config_args(p)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--smoke-test", action="store_true",
                   help="Train 1 step on 16 pairs to verify the loop")
    p.add_argument("--resume-from", type=str, default=None)
    return p.parse_args()


def _load_pair_dataset(path: str):
    """Load the parquet pair dataset and convert to TRL DPO format."""
    import pandas as pd
    from datasets import Dataset

    df = pd.read_parquet(path)
    # TRL DPO expects columns: prompt, chosen, rejected
    cols = ["prompt", "chosen", "rejected"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"DPO pair file missing columns: {missing}")
    log.info("Loaded %d pairs from %s", len(df), path)
    log.info("Hard-axis distribution:\n%s",
             df.groupby(["hard_axis_x", "hard_axis_y"]).size().to_string()
             if "hard_axis_x" in df.columns else "(no axis labels)")
    ds = Dataset.from_pandas(df[cols], preserve_index=False)
    return ds


def main() -> int:
    args = parse_args()

    from src.config import apply_cli_overrides, load_config

    log.info("Loading config: %s", args.config)
    cfg = load_config(args.config)
    cfg = apply_cli_overrides(cfg, args.override)

    if args.dry_run:
        print(json.dumps(cfg, indent=2, default=str))
        return 0

    log.info("Importing torch + transformers + trl + peft + datasets ...")
    t0 = time.perf_counter()
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    try:
        from trl import DPOConfig, DPOTrainer
    except ImportError as exc:
        log.error("TRL DPOTrainer not available — pip install trl>=0.11: %s", exc)
        return 2

    log.info("Imports done in %.1fs", time.perf_counter() - t0)

    torch.manual_seed(cfg.training.seed)

    # Wandb env
    if "wandb" in cfg.training.report_to and not os.environ.get("WANDB_API_KEY"):
        log.warning("WANDB_API_KEY not set; wandb logging will fail or skip.")
    os.environ.setdefault("WANDB_PROJECT", cfg.wandb.project)
    os.environ.setdefault("WANDB_NAME", cfg.run_name)
    if cfg.wandb.tags:
        os.environ.setdefault("WANDB_TAGS", ",".join(cfg.wandb.tags))

    log.info("Loading tokenizer: %s", cfg.model.base_id)
    tok = AutoTokenizer.from_pretrained(cfg.model.base_id, use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    log.info("Loading policy: %s (dtype=%s)", cfg.model.base_id, cfg.model.dtype)
    dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16,
             "float32": torch.float32}[cfg.model.dtype]
    model_kwargs = dict(
        torch_dtype=dtype,
        device_map="auto",
        trust_remote_code=cfg.model.trust_remote_code,
        use_cache=False,
    )
    if cfg.model.attn_impl == "flash_attention_2":
        model_kwargs["attn_implementation"] = "flash_attention_2"

    policy = AutoModelForCausalLM.from_pretrained(cfg.model.base_id, **model_kwargs)

    # Merge Stage 2 LoRA so DPO trains a fresh adapter on top.
    existing = (cfg.peft.get("load_existing_adapter")
                if hasattr(cfg.peft, "get") else None)
    if existing:
        log.info("Loading + merging Stage 2 adapter: %s", existing)
        policy = PeftModel.from_pretrained(policy, existing)
        policy = policy.merge_and_unload()

    if cfg.peft.enabled:
        lora_cfg = LoraConfig(
            r=cfg.peft.r, lora_alpha=cfg.peft.alpha,
            lora_dropout=cfg.peft.dropout, bias=cfg.peft.bias,
            task_type=cfg.peft.task_type,
            target_modules=list(cfg.peft.target_modules),
        )
        policy = get_peft_model(policy, lora_cfg)
        policy.print_trainable_parameters()

    if cfg.training.gradient_checkpointing:
        policy.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False})

    train_ds = _load_pair_dataset(cfg.dataset.train_path)
    if args.smoke_test:
        train_ds = train_ds.select(range(min(16, len(train_ds))))
        log.info("SMOKE: truncated to %d pairs", len(train_ds))

    # DPOConfig kwargs filtered against running TRL signature for fwd compat.
    import inspect as _ins
    dpo_kwargs = dict(
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
        max_steps=cfg.training.get("max_steps", -1),
        report_to=list(cfg.training.report_to),
        seed=cfg.training.seed,
        run_name=cfg.run_name,
        push_to_hub=cfg.hub.push_to_hub,
        hub_model_id=cfg.hub.get("hub_model_id"),
        hub_private_repo=cfg.hub.private,
        hub_strategy="checkpoint" if cfg.hub.get("push_strategy") == "checkpoint" else "end",
        beta=cfg.dpo.beta,
        max_length=cfg.dataset.max_length,
        max_prompt_length=cfg.dataset.max_prompt_length,
    )
    dpo_param_names = set(_ins.signature(DPOConfig).parameters.keys())
    dropped = {k: v for k, v in dpo_kwargs.items() if k not in dpo_param_names}
    if dropped:
        log.info("Dropping DPOConfig kwargs not supported: %s", list(dropped))
    dpo_kwargs = {k: v for k, v in dpo_kwargs.items() if k in dpo_param_names}
    dpo_args = DPOConfig(**dpo_kwargs)

    dpo_init_params = set(_ins.signature(DPOTrainer.__init__).parameters.keys())
    trainer_kwargs = dict(
        model=policy,
        args=dpo_args,
        train_dataset=train_ds,
    )
    if "ref_model" in dpo_init_params:
        trainer_kwargs["ref_model"] = None  # TRL auto-builds from beta
    if "processing_class" in dpo_init_params:
        trainer_kwargs["processing_class"] = tok
    elif "tokenizer" in dpo_init_params:
        trainer_kwargs["tokenizer"] = tok

    trainer_kwargs = {k: v for k, v in trainer_kwargs.items()
                      if k in dpo_init_params}
    trainer = DPOTrainer(**trainer_kwargs)

    # Cost protection
    try:
        from src.training.cost_callback import from_env as cost_from_env
        cb = cost_from_env()
        trainer.add_callback(cb)
        log.info("CostCallback armed: budget=$%.2f rate=$%.2f/h",
                 cb.budget_usd, cb.rate_per_hour)
    except Exception as exc:  # noqa: BLE001
        log.warning("CostCallback not attached: %s", exc)

    log.info("=" * 60)
    log.info("Starting DPO: %s", cfg.run_name)
    log.info("=" * 60)
    t_train = time.perf_counter()
    trainer.train(resume_from_checkpoint=args.resume_from)
    log.info("DPO done in %.1f minutes", (time.perf_counter() - t_train) / 60)

    log.info("Saving final adapter to %s", cfg.training.output_dir)
    trainer.save_model(cfg.training.output_dir)
    tok.save_pretrained(cfg.training.output_dir)

    if cfg.hub.push_to_hub:
        from src.training.hub_push import push_with_retry
        ok = push_with_retry(
            trainer,
            repo_id=cfg.hub.hub_model_id,
            commit_message=f"DPO complete - {cfg.run_name}",
            private=cfg.hub.private,
            max_retries=4, backoff_s=30.0,
        )
        if not ok:
            log.error("Hub push exhausted; LOCAL adapter at %s",
                      cfg.training.output_dir)
            return 3

    log.info("Stage 2.5 DPO complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
