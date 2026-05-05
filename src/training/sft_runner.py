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
    from trl import SFTConfig, SFTTrainer
    # DataCollatorForCompletionOnlyLM was removed in TRL 1.x; SFTConfig now
    # carries `completion_only_loss=True` to do the same thing.
    try:
        from trl import DataCollatorForCompletionOnlyLM  # TRL <= 0.x
        _USE_LEGACY_COLLATOR = True
    except ImportError:
        _USE_LEGACY_COLLATOR = False
    log.info("Imports done in %.1fs (TRL legacy collator: %s)",
             time.perf_counter() - t0, _USE_LEGACY_COLLATOR)

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

    # Tokenizer alignment guard — if loading from a previously trained adapter,
    # confirm the tokenizer vocab size matches the base model's. A drift here
    # silently breaks training (embedding indices off by N).
    existing_for_check = (cfg.peft.get("load_existing_adapter")
                          if hasattr(cfg.peft, "get") else None)
    if existing_for_check:
        try:
            from pathlib import Path as _P
            tok_dir = _P(existing_for_check)
            if (tok_dir / "tokenizer_config.json").exists():
                from transformers import AutoTokenizer as _AT
                prior_tok = _AT.from_pretrained(str(tok_dir), use_fast=True)
                if prior_tok.vocab_size != tok.vocab_size:
                    raise RuntimeError(
                        f"Tokenizer vocab drift! base={tok.vocab_size} "
                        f"adapter={prior_tok.vocab_size}. Training with this "
                        f"mismatch corrupts embeddings. Use `--override "
                        f"model.base_id={existing_for_check}` so the same "
                        f"tokenizer is used end-to-end."
                    )
                log.info("Tokenizer alignment OK: vocab=%d matches prior adapter at %s",
                         tok.vocab_size, existing_for_check)
        except RuntimeError:
            raise  # bubble up the assertion
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not verify tokenizer alignment: %s", exc)

    # Model
    log.info("Loading base model: %s (dtype=%s)", cfg.model.base_id, cfg.model.dtype)
    dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[cfg.model.dtype]
    model_kwargs = dict(
        torch_dtype=dtype,
        device_map="auto",
        trust_remote_code=cfg.model.trust_remote_code,
    )
    if cfg.model.attn_impl == "flash_attention_2":
        model_kwargs["attn_implementation"] = "flash_attention_2"
    # Try AutoModelForCausalLM first; for Gemma 4 (multimodal-wrapper) and
    # similar conditional-generation models, fall back to AutoModel which
    # picks the right class and we extract the text decoder.
    try:
        model = AutoModelForCausalLM.from_pretrained(cfg.model.base_id, **model_kwargs)
    except (ValueError, KeyError) as exc:
        log.warning("AutoModelForCausalLM failed (%s); trying AutoModel", exc)
        from transformers import AutoModel
        model = AutoModel.from_pretrained(cfg.model.base_id, **model_kwargs)
    # Set use_cache *after* load (some wrappers reject use_cache in __init__)
    if hasattr(model, "config"):
        try:
            model.config.use_cache = cfg.model.use_cache
        except Exception:
            pass
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

        # For multimodal Gemma 4 wrappers, scope LoRA to the text decoder
        # only (skip vision_tower and embed_vision which use Gemma4ClippableLinear
        # that PEFT cannot wrap). exclude_modules takes a regex; vision_tower
        # and embed_vision are the multimodal-only sub-trees.
        lora_kwargs = dict(
            r=cfg.peft.r,
            lora_alpha=cfg.peft.alpha,
            lora_dropout=cfg.peft.dropout,
            bias=cfg.peft.bias,
            task_type=cfg.peft.task_type,
            target_modules=list(cfg.peft.target_modules),
        )
        # Skip multimodal towers if the model has them (Gemma 4 31B-it case)
        if hasattr(model, "vision_tower") or any("vision_tower" in n
                                                  for n, _ in model.named_modules()):
            lora_kwargs["exclude_modules"] = r".*(vision_tower|embed_vision|audio).*"
            log.info("Multimodal model detected: exclude_modules set on vision/audio paths")
        lora_cfg = LoraConfig(**lora_kwargs)
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

    # Our datasets store `messages` as a JSON-stringified list-of-dicts so
    # they round-trip through Arrow cleanly. TRL 1.x expects either a
    # native chat list-of-dicts OR a single `text` field. Render to text
    # via the tokenizer chat template and pass that.
    import json as _json
    def _to_text(example):
        msgs = example.get("messages")
        if isinstance(msgs, str):
            try:
                msgs = _json.loads(msgs)
            except Exception:
                # Fallback: treat as plain text
                return {"text": msgs}
        if isinstance(msgs, list):
            txt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
        else:
            txt = str(msgs or "")
        return {"text": txt}

    log.info("Pre-processing dataset: rendering chat-template to text field...")
    train_ds = train_ds.map(_to_text, num_proc=4,
                            remove_columns=[c for c in train_ds.column_names
                                            if c not in ("task",)])
    if eval_ds is not None:
        eval_ds = eval_ds.map(_to_text, num_proc=4,
                              remove_columns=[c for c in eval_ds.column_names
                                              if c not in ("task",)])
    log.info("Train examples: %d", len(train_ds))
    log.info("Eval  examples: %d", len(eval_ds) if eval_ds else 0)

    # SFTTrainer args (TRL-version-aware)
    common_sft_kwargs = dict(
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
        packing=cfg.dataset.packing,
        dataset_text_field="text",  # we render to a text column above
    )

    # max_seq_length renamed to max_length in TRL 1.x
    import inspect as _ins
    sft_param_names = set(_ins.signature(SFTConfig).parameters.keys())
    if "max_seq_length" in sft_param_names:
        common_sft_kwargs["max_seq_length"] = cfg.dataset.max_seq_length
    else:
        common_sft_kwargs["max_length"] = cfg.dataset.max_seq_length
    if "completion_only_loss" in sft_param_names:
        common_sft_kwargs["completion_only_loss"] = True

    # Filter kwargs that the running TRL doesn't know about (group_by_length
    # etc were dropped in TRL 1.x). Log what's dropped so we don't lose
    # behavior silently.
    dropped = {k: v for k, v in common_sft_kwargs.items() if k not in sft_param_names}
    if dropped:
        log.info("Dropping SFTConfig kwargs not supported by trl: %s", list(dropped))
    common_sft_kwargs = {k: v for k, v in common_sft_kwargs.items() if k in sft_param_names}
    sft_args = SFTConfig(**common_sft_kwargs)

    # Trainer construction differs in TRL 1.x: tokenizer -> processing_class,
    # collator built internally when completion_only_loss=True.
    sft_init_params = set(_ins.signature(SFTTrainer.__init__).parameters.keys())
    trainer_kwargs = dict(
        model=model,
        args=sft_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
    )
    if "processing_class" in sft_init_params:
        trainer_kwargs["processing_class"] = tok
    else:
        trainer_kwargs["tokenizer"] = tok

    if _USE_LEGACY_COLLATOR and "data_collator" in sft_init_params:
        # Legacy explicit collator (TRL <=0.x)
        response_template = cfg.dataset.response_template
        trainer_kwargs["data_collator"] = DataCollatorForCompletionOnlyLM(
            response_template=response_template, tokenizer=tok,
        )

    trainer = SFTTrainer(**trainer_kwargs)

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

    # Persist a default GenerationConfig so inference matches what we trained with.
    try:
        from transformers import GenerationConfig
        gen_cfg = GenerationConfig(
            do_sample=True,
            temperature=cfg.inference.get("temperature", 0.7) if hasattr(cfg, "inference") else 0.7,
            top_p=cfg.inference.get("top_p", 0.95) if hasattr(cfg, "inference") else 0.95,
            top_k=cfg.inference.get("top_k", 50) if hasattr(cfg, "inference") else 50,
            max_new_tokens=cfg.inference.get("max_new_tokens", 512) if hasattr(cfg, "inference") else 512,
            pad_token_id=tok.pad_token_id,
            eos_token_id=tok.eos_token_id,
        )
        gen_cfg.save_pretrained(cfg.training.output_dir)
        log.info("GenerationConfig saved to %s", cfg.training.output_dir)
    except Exception as exc:  # noqa: BLE001
        log.warning("GenerationConfig save failed: %s", exc)

    if cfg.hub.push_to_hub:
        from src.training.hub_push import push_with_retry
        ok = push_with_retry(
            trainer,
            repo_id=cfg.hub.hub_model_id,
            commit_message=f"Training complete — {cfg.run_name}",
            private=cfg.hub.private,
            max_retries=4,
            backoff_s=30.0,
        )
        if not ok:
            log.error("Hub push exhausted retries; LOCAL CHECKPOINT PRESERVED at %s",
                      cfg.training.output_dir)
            log.error("Manual recovery: `huggingface-cli upload %s %s`",
                      cfg.hub.hub_model_id, cfg.training.output_dir)
            return 3

    log.info("SFT done.")
    return 0
