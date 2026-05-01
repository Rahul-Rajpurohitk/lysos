"""Reward functions for Stage 3 RL training.

Each module exports one or more reward functions with the signature:

    def reward_fn(samples: list[str], **kwargs) -> list[float]:
        '''Compute reward for each generated sample.

        Args:
            samples: list of model-generated strings (typically containing SMILES).

        Returns:
            list of float rewards, one per sample. Higher = better.
        '''

The Stage 3 GRPO trainer composes multiple reward fns into a weighted sum
based on configs/stage3_rl_grpo.yaml.
"""

from __future__ import annotations

import importlib
import logging
import re
from typing import Any, Callable

log = logging.getLogger(__name__)

# Pattern that pulls a SMILES out of a model response. The model is trained
# to emit responses like "SMILES: CC1(C)..." or fenced code, so we extract.
SMILES_PATTERNS = [
    re.compile(r"SMILES:\s*([^\s\n]+)"),
    re.compile(r"```(?:smiles|chem)?\s*\n?([^\n`]+)\n?```"),
    re.compile(r"<smiles>(.*?)</smiles>", re.DOTALL),
]


def extract_smiles(text: str) -> str | None:
    """Best-effort SMILES extraction from a model response."""
    if not text:
        return None
    text = text.strip()
    for pat in SMILES_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    # Last resort: assume the whole response is a SMILES if it has chemistry-ish chars
    if re.match(r"^[A-Za-z0-9@\[\]\(\)=\-+#\\/.%]+$", text):
        return text
    return None


def load_reward_fn(spec: str) -> Callable:
    """Load a reward function from a 'module.path:fn_name' spec."""
    if ":" not in spec:
        raise ValueError(f"reward spec must be 'module:fn', got {spec!r}")
    mod_path, fn_name = spec.split(":", 1)
    mod = importlib.import_module(mod_path)
    return getattr(mod, fn_name)


class CompositeReward:
    """Weighted sum of multiple reward components.

    Configured from cfg.reward.components in stage3_rl_grpo.yaml.
    """

    def __init__(self, components: list[dict], on_error: dict | None = None):
        self.fns: list[tuple[str, float, Callable, dict]] = []
        self.on_error = on_error or {"return": 0.0, "log_warning": True}
        total_weight = sum(c["weight"] for c in components)
        if abs(total_weight - 1.0) > 1e-6:
            log.warning("reward weights sum to %.4f, not 1.0 — proceeding anyway", total_weight)
        for c in components:
            fn = load_reward_fn(c["module"])
            self.fns.append((c["name"], c["weight"], fn, c.get("args", {})))
            log.info("loaded reward component: %s (weight=%.2f, module=%s)",
                     c["name"], c["weight"], c["module"])

    def __call__(self, samples: list[str], **shared_kwargs: Any) -> tuple[list[float], dict[str, list[float]]]:
        """Return (combined_rewards, per_component_rewards).

        Per-component rewards are returned for logging to wandb.
        """
        per: dict[str, list[float]] = {}
        for name, weight, fn, args in self.fns:
            try:
                merged_kwargs = {**shared_kwargs, **args}
                vals = fn(samples, **merged_kwargs)
                if not isinstance(vals, (list, tuple)) or len(vals) != len(samples):
                    raise ValueError(f"reward {name} returned bad shape: expected {len(samples)} got {len(vals) if hasattr(vals, '__len__') else 'scalar'}")
                per[name] = [float(v) for v in vals]
            except Exception as exc:  # noqa: BLE001
                if self.on_error["log_warning"]:
                    log.warning("reward %s crashed: %s — using fallback %s", name, exc, self.on_error["return"])
                per[name] = [float(self.on_error["return"])] * len(samples)

        combined = [0.0] * len(samples)
        for name, weight, _, _ in self.fns:
            for i, v in enumerate(per[name]):
                combined[i] += weight * v
        return combined, per
