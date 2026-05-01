"""Config loader with simple inheritance support.

Loads YAML configs that can declare `_inherit: another_file.yaml` to merge in
defaults from a base config. Stage configs override base values; nested dicts
are deep-merged.

Usage:
    from src.config import load_config
    cfg = load_config("configs/stage1_txgemma4.yaml")
    print(cfg.model.base_id)
"""

from __future__ import annotations

import argparse
import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


class AttrDict(dict):
    """Dict that exposes keys as attributes for ergonomic access (cfg.model.base_id)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for k, v in list(self.items()):
            self[k] = self._convert(v)

    @classmethod
    def _convert(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return cls(v)
        if isinstance(v, list):
            return [cls._convert(x) for x in v]
        return v

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = self._convert(value)


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins on conflicts."""
    out = deepcopy(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path, *, _seen: set[Path] | None = None) -> AttrDict:
    """Load a YAML config, recursively resolving _inherit chains."""
    p = Path(path).resolve()
    _seen = _seen or set()
    if p in _seen:
        raise ValueError(f"circular _inherit chain at {p}")
    _seen.add(p)

    with open(p) as f:
        raw = yaml.safe_load(f) or {}

    inherit = raw.pop("_inherit", None)
    base: dict = {}
    if inherit:
        # Resolve _inherit relative to the current file's directory
        inherit_path = (p.parent / inherit).resolve()
        base = load_config(inherit_path, _seen=_seen)

    merged = deep_merge(base, raw)
    return AttrDict(merged)


def apply_cli_overrides(cfg: AttrDict, overrides: list[str]) -> AttrDict:
    """Apply --override key=value pairs to a config.

    Supports dotted keys: --override training.learning_rate=1e-5
    Casts to int / float / bool when obvious.
    """
    for spec in overrides:
        if "=" not in spec:
            log.warning("ignoring malformed override: %s", spec)
            continue
        key, raw_val = spec.split("=", 1)
        casted = _cast(raw_val.strip())
        _set_nested(cfg, key.split("."), casted)
        log.info("override: %s = %r", key, casted)
    return cfg


def _set_nested(d: dict, keys: list[str], value: Any) -> None:
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, AttrDict())
    cur[keys[-1]] = value


def _cast(s: str) -> Any:
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if s.lower() in ("none", "null"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def add_config_args(parser: argparse.ArgumentParser) -> None:
    """Register --config and --override args on an argparser."""
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to YAML config (e.g. configs/stage1_txgemma4.yaml)",
    )
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        help="Override a config key. Repeatable. Example: --override training.learning_rate=1e-5",
    )


def env_or(cfg_value: str | None, env_var: str | None, *, required: bool = False) -> str | None:
    """Return env var if cfg_value is None or empty; useful for tokens."""
    if cfg_value:
        return cfg_value
    if env_var:
        v = os.environ.get(env_var)
        if v:
            return v
    if required:
        raise ValueError(f"missing config value (env: {env_var})")
    return None
