"""Mid-training evaluation callback — runs the 7-metric eval after every save.

Plugs into HuggingFace Trainer + GRPOTrainer via callbacks. After each
`save_steps`, generates 50 candidates, runs them through the reward stack,
logs metrics to wandb. Catches regressions early; lets us kill bad runs
before burning the budget.

Usage:
  from src.training.eval_callback import LysosMidTrainCallback
  trainer.add_callback(LysosMidTrainCallback(eval_prompts_path="...", n_samples=50))
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class LysosMidTrainEvaluator:
    """Runs a 50-prompt evaluation after every checkpoint save."""

    def __init__(
        self,
        eval_prompts_path: str | Path,
        n_samples: int = 50,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        log_to_wandb: bool = True,
    ):
        self.path = Path(eval_prompts_path)
        self.n_samples = n_samples
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.log_to_wandb = log_to_wandb
        self._prompts = None
        self._reward_fn = None

    def _load_prompts(self) -> list[str]:
        if self._prompts is not None:
            return self._prompts
        prompts = []
        if self.path.suffix == ".jsonl":
            with self.path.open() as f:
                for line in f:
                    if not line.strip(): continue
                    r = json.loads(line)
                    p = r.get("prompt") or (r.get("messages", [{}])[0].get("content") if r.get("messages") else None)
                    if p:
                        prompts.append(p)
        prompts = prompts[:self.n_samples]
        self._prompts = prompts
        log.info("MidTrainEvaluator: loaded %d prompts from %s", len(prompts), self.path)
        return prompts

    def _load_reward_fn(self):
        if self._reward_fn is not None:
            return self._reward_fn
        try:
            import yaml
            from src.eval.rewards import CompositeReward
            cfg_path = Path(__file__).resolve().parents[2] / "configs/stage3_rl_grpo.yaml"
            cfg = yaml.safe_load(cfg_path.read_text())
            self._reward_fn = CompositeReward(
                components=cfg["reward"]["components"],
                on_error=cfg["reward"].get("on_error"),
            )
        except Exception as exc:
            log.warning("MidTrainEvaluator: could not load reward fn: %s", exc)
            self._reward_fn = None
        return self._reward_fn

    def on_save(self, args, state, control, model=None, tokenizer=None, **kwargs: Any):
        """Called after each checkpoint save."""
        prompts = self._load_prompts()
        if not prompts or model is None or tokenizer is None:
            return

        log.info("MidTrainEvaluator @ step %d — generating %d samples", state.global_step, len(prompts))
        try:
            import torch
        except ImportError:
            return

        # Switch model to inference mode
        model.train(False)
        completions = []
        for prompt in prompts:
            try:
                inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024).to(model.device)
                with torch.no_grad():
                    output_ids = model.generate(
                        **inputs,
                        max_new_tokens=self.max_new_tokens,
                        temperature=self.temperature,
                        do_sample=self.temperature > 0,
                        pad_token_id=tokenizer.pad_token_id,
                    )
                completion = tokenizer.decode(output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
                completions.append(completion)
            except Exception as exc:
                log.warning("Generation failed for prompt: %s", str(exc)[:80])
                completions.append("")
        model.train(True)

        # Score
        reward_fn = self._load_reward_fn()
        if reward_fn:
            try:
                combined, per_comp = reward_fn(completions)
                avg_combined = sum(combined) / max(len(combined), 1)
                metrics = {
                    "midtrain/composite_avg": avg_combined,
                    "midtrain/composite_max": max(combined) if combined else 0,
                    "midtrain/composite_min": min(combined) if combined else 0,
                }
                for name, vals in per_comp.items():
                    metrics[f"midtrain/{name}_avg"] = sum(vals) / max(len(vals), 1)

                log.info("MidTrainEvaluator @ step %d:", state.global_step)
                for k, v in metrics.items():
                    log.info("  %s = %.3f", k, v)

                if self.log_to_wandb:
                    try:
                        import wandb
                        if wandb.run is not None:
                            wandb.log(metrics, step=state.global_step, commit=False)
                    except Exception:
                        pass
            except Exception as exc:
                log.warning("MidTrainEvaluator scoring failed: %s", exc)


class LysosMidTrainCallback:
    """HF Trainer-compatible callback wrapper around MidTrainEvaluator."""

    def __init__(self, *args, **kwargs):
        self.evaluator = LysosMidTrainEvaluator(*args, **kwargs)

    def on_save(self, args, state, control, **kwargs):
        self.evaluator.on_save(args, state, control, **kwargs)

    # No-op for other events
    def on_train_begin(self, *a, **kw): pass
    def on_train_end(self, *a, **kw): pass
    def on_step_begin(self, *a, **kw): pass
    def on_step_end(self, *a, **kw): pass
    def on_evaluate(self, *a, **kw): pass
    def on_log(self, *a, **kw): pass
    def on_init_end(self, *a, **kw): pass
    def on_epoch_begin(self, *a, **kw): pass
    def on_epoch_end(self, *a, **kw): pass
    def on_substep_end(self, *a, **kw): pass
    def on_predict(self, *a, **kw): pass
