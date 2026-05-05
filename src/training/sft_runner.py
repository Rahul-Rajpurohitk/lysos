"""Shared SFT (Supervised Fine-Tuning) runner used by Stage 1 and Stage 2.

Both stages do the same thing — SFT on a chat-format dataset with LoRA — they
just differ in:
  - Starting model (Gemma 4 base vs Stage 1 output)
  - Whether to merge an existing adapter first
  - Training data
  - Learning rate / epochs / etc

All these are config-driven, so the actual training loop is identical.
This module exposes `run_sft(args)` which the stage-specific entry points
call with their default config.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

log = logging.getLogger(__name__)


def add_sft_args(parser: argparse.ArgumentParser) -> None:
    """Register the args used by both Stage 1 and Stage 2 entry points."""
    from src.config import add_config_args

    add_config_args(parser)
    parser.add_argument("--dry-run", action="store_true", help="Load + print config + exit")
    parser.add_argument("--smoke-test", action="store_true",
                        help="Train 1 step on a tiny subset to verify the loop")
    parser.add_argument("--resume-from", type=str, default=None,
                        help="Checkpoint path to resume from")


def run_sft(args: argparse.Namespace) -> int:
    """Run SFT training driven by args.config + overrides."""
    from src.config import apply_cli_overrides, load_config

    log.info("Loading config: %s", args.config)
    cfg = load_config(args.config)
    cfg = apply_cli_overrides(cfg, args.override)

    if args.dry_run:
        import json
        print(json.dumps(cfg, indent=2, default=str))
        return 0

    # Heavy imports
    log.info("Importing torch + transformers + trl + peft + datasets ...")
    t0 = time.perf_counter()
    import torch
    from datasets import load_dataset, load_from_disk
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import DataCollatorForCompletionOnlyLM, SFTConfig, SFTTrainer
    log.info("Imports done in %.1fs", time.perf_counter() - t0)

    torch.manual_seed(cfg.training.seed)

    # Wandb env
    if "wandb" in cfg.training.report_to and not os.environ.get("WANDB_API_KEY"):
        log.warning("WANDB_API_KEY not set; wandb logging will fail. Set it or remove from report_to.")
    os.environ.setdefault("WANDB_PROJECT", cfg.wandb.project)
    os.environ.setdefault("WANDB_NAME", cfg.run_name)
    if cfg.wandb.tags:
        os.environ.setdefault("WANDB_TAGS", ",".join(cfg.wandb.tags))

    # Tokenizer
    log.info("Loading tokenizer: %s", cfg.model.base_id)
    tok = AutoTokenizer.from_pretrained(cfg.model.base_id, use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
        log.info("pad_token unset; setting to eos_token (%r)", tok.eos_token)

    # Model
    log.info("Loading base model: %s (dtype=%s)", cfg.model.base_id, cfg.model.dtype)
    dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[cfg.model.dtype]
    model_kwargs = dict(
        torch_dtype=dtype,
        device_map="auto",
        trust_remote_code=cfg.model.trust_remote_code,
        use_cache=cfg.model.use_cache,
    )
    if cfg.model.attn_impl == "flash_attention_2":
        model_kwargs["attn_implementation"] = "flash_attention_2"
    model = AutoModelForCausalLM.from_pretrained(cfg.model.base_id, **model_kwargs)
    log.info("Model loaded. dtype=%s, device_map applied.", model.dtype)

    if cfg.training.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        log.info("Gradient checkpointing: ON")

    # PEFT — optionally merge existing adapter first (Stage 2/3 path)
    if cfg.peft.enabled:
        if cfg.peft.type != "lora":
            raise ValueError(f"only 'lora' supported for now, got {cfg.peft.type}")

        existing = cfg.peft.get("load_existing_adapter") if hasattr(cfg.peft, "get") else None
        if existing:
            log.info("Loading + merging existing adapter: %s", existing)
            model = PeftModel.from_pretrained(model, existing)
            model = model.merge_and_unload()

        lora_cfg = LoraConfig(
            r=cfg.peft.r,
            lora_alpha=cfg.peft.alpha,
            lora_dropout=cfg.peft.dropout,
            bias=cfg.peft.bias,
            task_type=cfg.peft.task_type,
            target_modules=list(cfg.peft.target_modules),
        )
        model = get_peft_model(model, lora_cfg)
        model.print_trainable_parameters()

    # Data
    log.info("Loading dataset: source=%s, path=%s, hub_id=%s",
             cfg.dataset.source, cfg.dataset.path, cfg.dataset.get("hub_id"))
    if cfg.dataset.source == "local":
        ds = load_from_disk(cfg.dataset.path)
    elif cfg.dataset.source == "hub":
        ds = load_dataset(cfg.dataset.hub_id)
    else:
        raise ValueError(f"unknown dataset source: {cfg.dataset.source}")

    train_ds = ds[cfg.dataset.split_train] if cfg.dataset.split_train in ds else ds["train"]
    eval_ds = ds[cfg.dataset.split_eval] if cfg.dataset.split_eval in ds else None

    if args.smoke_test:
        log.info("SMOKE TEST: truncating dataset to 32 examples")
        train_ds = train_ds.select(range(min(32, len(train_ds))))
        if eval_ds:
            eval_ds = eval_ds.select(range(min(8, len(eval_ds))))

    log.info("Train examples: %d", len(train_ds))
    log.info("Eval  examples: %d", len(eval_ds) if eval_ds else 0)

    # SFTTrainer
    sft_args = SFTConfig(
        output_dir=cfg.training.output_dir,
        num_train_epochs=cfg.training.num_train_epochs,
        per_device_train_batch_size=cfg.training.per_device_train_batch_size,
        per_device_eval_batch_size=cfg.training.per_device_eval_batch_size,
        gradient_accumulation_steps=cfg.training.gradient_accumulation_steps,
        gradient_checkpointing=cfg.training.gradient_checkpointing,
        learning_rate=cfg.training.learning_rate,
        lr_scheduler_type=cfg.training.lr_scheduler_type,
        warmup_ratio=cfg.training.warmup_ratio,
        weight_decay=cfg.training.weight_decay,
        optim=cfg.training.optim,
        max_grad_norm=cfg.training.max_grad_norm,
        bf16=cfg.training.bf16,
        tf32=cfg.training.tf32,
        logging_steps=cfg.training.logging_steps,
        eval_strategy=cfg.training.eval_strategy if eval_ds else "no",
        eval_steps=cfg.training.eval_steps,
        save_strategy=cfg.training.save_strategy,
        save_steps=cfg.training.save_steps,
        save_total_limit=cfg.training.save_total_limit,
        load_best_model_at_end=cfg.training.load_best_model_at_end and eval_ds is not None,
        metric_for_best_model=cfg.training.metric_for_best_model,
        greater_is_better=cfg.training.greater_is_better,
        group_by_length=cfg.training.group_by_length,
        report_to=list(cfg.training.report_to),
        ddp_find_unused_parameters=cfg.training.ddp_find_unused_parameters,
        remove_unused_columns=cfg.training.remove_unused_columns,
        dataloader_num_workers=cfg.training.dataloader_num_workers,
        seed=cfg.training.seed,
        run_name=cfg.run_name,
        push_to_hub=cfg.hub.push_to_hub,
        hub_model_id=cfg.hub.get("hub_model_id"),
        hub_private_repo=cfg.hub.private,
        hub_strategy="checkpoint" if cfg.hub.get("push_strategy") == "checkpoint" else "end",
        max_seq_length=cfg.dataset.max_seq_length,
        packing=cfg.dataset.packing,
        dataset_text_field=cfg.dataset.text_field,
    )

    response_template = cfg.dataset.response_template
    collator = DataCollatorForCompletionOnlyLM(
        response_template=response_template,
        tokenizer=tok,
    )

    trainer = SFTTrainer(
        model=model,
        args=sft_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        tokenizer=tok,
        data_collator=collator,
    )

    # Cost protection — emits cost/* metrics to wandb + hard-stops over budget.
    try:
        from src.training.cost_callback import from_env as cost_from_env
        cb = cost_from_env()
        trainer.add_callback(cb)
        log.info("CostCallback armed: budget=$%.2f rate=$%.2f/h",
                 cb.budget_usd, cb.rate_per_hour)
    except Exception as exc:  # noqa: BLE001
        log.warning("CostCallback not attached: %s", exc)

    log.info("=" * 60)
    log.info("Starting SFT: %s", cfg.run_name)
    log.info("=" * 60)
    t_train = time.perf_counter()
    trainer.train(resume_from_checkpoint=args.resume_from)
    log.info("Training done in %.1f minutes", (time.perf_counter() - t_train) / 60)

    log.info("Saving final adapter to %s", cfg.training.output_dir)
    trainer.save_model(cfg.training.output_dir)
    tok.save_pretrained(cfg.training.output_dir)

    if cfg.hub.push_to_hub:
        log.info("Pushing final to HF Hub: %s (private=%s)",
                 cfg.hub.hub_model_id, cfg.hub.private)
        trainer.push_to_hub(commit_message=f"Training complete — {cfg.run_name}")

    log.info("SFT done.")
    return 0
