"""cost_callback.py — live cost emission during training.

Hooks into HF Trainer to log:
  cost/hours_elapsed
  cost/per_hour          (depends on n_gpus + GPU class)
  cost/projected_total_usd
  cost/budget_pct_used

Triggers a hard stop if `budget_usd` is exceeded — guards against runaway
training (e.g. hung run on Large 8x MI300X eating $24/hr).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

try:
    from transformers import TrainerCallback as _TrainerCallback
except ImportError:  # pragma: no cover — only happens at config-only load
    class _TrainerCallback:  # type: ignore[no-redef]
        """Fallback no-op base; real Trainer requires the real one."""

log = logging.getLogger(__name__)

# USD/hour rates on AMD Developer Cloud (verified 2026-04)
DEFAULT_RATES = {
    "mi300x_small_1gpu": 3.0,
    "mi300x_large_8gpu": 24.0,
}


class CostCallback(_TrainerCallback):
    """TrainerCallback subclass for live cost tracking + budget hard-stop.

    Subclasses TrainerCallback so the transformers callback dispatcher
    finds default no-op handlers for every event we don't override.
    """

    def __init__(
        self,
        gpu_class: str = "mi300x_small_1gpu",
        budget_usd: float = 300.0,
        rates: dict[str, float] | None = None,
        hard_stop: bool = True,
    ):
        super().__init__()
        self.rates = rates or DEFAULT_RATES
        self.gpu_class = gpu_class
        self.rate_per_hour = self.rates.get(gpu_class, 3.0)
        self.budget_usd = budget_usd
        self.hard_stop = hard_stop
        self.start_time: float | None = None

    def on_train_begin(self, args: Any, state: Any, control: Any, **kw):
        self.start_time = time.time()
        log.info(
            "[CostCallback] gpu_class=%s rate=$%.2f/h budget=$%.2f hard_stop=%s",
            self.gpu_class, self.rate_per_hour, self.budget_usd, self.hard_stop,
        )

    def on_step_end(self, args: Any, state: Any, control: Any, **kw):
        if self.start_time is None:
            return

        # Operator killswitch: if /tmp/lysos_stop exists, stop cleanly at
        # the next step boundary. Pair with scripts/killswitch.py.
        if os.path.exists("/tmp/lysos_stop"):
            log.error("[CostCallback] /tmp/lysos_stop present — operator "
                      "requested stop. Stopping training.")
            control.should_training_stop = True
            try:
                import wandb
                if wandb.run is not None:
                    wandb.log({"cost/operator_stop": 1.0},
                              step=state.global_step, commit=False)
            except Exception:
                pass
            return

        elapsed_h = (time.time() - self.start_time) / 3600
        spent = elapsed_h * self.rate_per_hour
        # Project total — assume linear extrapolation if we know max_steps
        if state.max_steps and state.global_step > 0:
            projected_total = (state.max_steps / state.global_step) * spent
        else:
            projected_total = spent
        pct = 100 * projected_total / self.budget_usd if self.budget_usd else 0

        try:
            import wandb
            if wandb.run is not None:
                wandb.log({
                    "cost/hours_elapsed": elapsed_h,
                    "cost/per_hour": self.rate_per_hour,
                    "cost/spent_usd": spent,
                    "cost/projected_total_usd": projected_total,
                    "cost/budget_pct_used": pct,
                }, step=state.global_step, commit=False)
        except Exception as exc:  # noqa: BLE001
            log.debug("wandb cost log failed: %s", exc)

        # Hard stop: kill the run before it blows the budget.
        if self.hard_stop and projected_total > self.budget_usd * 1.05:
            log.error(
                "[CostCallback] PROJECTED total $%.2f exceeds budget $%.2f. "
                "Stopping training. (Adjust hard_stop=False or budget_usd to override.)",
                projected_total, self.budget_usd,
            )
            control.should_training_stop = True


def from_env() -> CostCallback:
    """Build a CostCallback from env vars set by run_training_pipeline.sh."""
    return CostCallback(
        gpu_class=os.environ.get("LYSOS_GPU_CLASS", "mi300x_small_1gpu"),
        budget_usd=float(os.environ.get("LYSOS_BUDGET_USD", "300")),
        hard_stop=os.environ.get("LYSOS_HARD_STOP_ON_BUDGET", "1") != "0",
    )
