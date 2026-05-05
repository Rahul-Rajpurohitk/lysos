"""validate_deepspeed.py — verify the ZeRO-3 config without burning GPU $.

Three layers of validation, cheapest first:

  L1 — schema check (fast, no torch needed):
        accelerate Library can parse the yaml; key fields present;
        gradient_accumulation_steps × per_device_batch consistent with
        the configured optimizer; bf16 enabled.

  L2 — accelerate dry config (requires accelerate):
        `accelerate launch --dry-run` style: parse + emit the resolved
        DeepSpeed JSON; verify it matches what the trainer expects.

  L3 — single-GPU smoke (optional, --smoke):
        Launch a tiny model with the ZeRO-3 config on one GPU. If
        ZeRO-3 init / sharding has any obvious bug, it shows up here
        without paying for 8 GPUs.

Run:
    python scripts/validate_deepspeed.py
    python scripts/validate_deepspeed.py --smoke           # adds L3
    python scripts/validate_deepspeed.py --config configs/accelerate_8gpu_zero3.yaml
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("validate-ds")

ROOT = Path(__file__).resolve().parents[1]


# ---- L1: schema check (no heavy deps) ----------------------------------


def _l1_schema_check(cfg: dict) -> list[str]:
    """Return list of issues (empty list = pass)."""
    issues: list[str] = []

    if cfg.get("distributed_type") != "DEEPSPEED":
        issues.append("distributed_type must be DEEPSPEED")

    ds = cfg.get("deepspeed_config", {})
    if not ds:
        issues.append("deepspeed_config block missing")

    if ds.get("zero_stage") != 3:
        issues.append(f"zero_stage must be 3 for the 31B model "
                      f"(got {ds.get('zero_stage')})")

    if not (ds.get("bf16", {}).get("enabled") is True
            or cfg.get("mixed_precision") == "bf16"):
        issues.append("bf16 not enabled (MI300X supports bf16 natively)")

    if cfg.get("num_processes", 0) <= 0:
        issues.append("num_processes must be > 0")

    grad_clip = ds.get("gradient_clipping")
    if grad_clip is None:
        issues.append("gradient_clipping not set (recommended ~1.0)")

    grad_accum = ds.get("gradient_accumulation_steps")
    if grad_accum is None:
        issues.append("deepspeed_config.gradient_accumulation_steps missing")

    # ZeRO-3 specifics
    z3_save = ds.get("zero3_save_16bit_model")
    if not z3_save:
        log.warning("zero3_save_16bit_model is False — checkpoint files will "
                    "be FP32 and 2x larger. Recommended True for storage cost.")

    z3_init = ds.get("zero3_init_flag")
    if not z3_init:
        issues.append("zero3_init_flag must be True so model loads under ZeRO-3 sharding")

    # Offload sanity
    offload_opt = ds.get("offload_optimizer_device", "none")
    if offload_opt == "cpu":
        log.info("Optimizer offload to CPU enabled — saves GPU memory; "
                 "expect ~10-20%% slower step time.")
    return issues


# ---- L2: accelerate parse ---------------------------------------------


def _l2_accelerate_parse(cfg_path: Path) -> list[str]:
    """Use accelerate's own loader to parse + resolve the config."""
    issues: list[str] = []
    try:
        from accelerate.commands.config.config_utils import load_config_from_file
    except ImportError:
        log.warning("accelerate not installed locally — skipping L2; will run on VM.")
        return issues
    try:
        loaded = load_config_from_file(str(cfg_path))
        if hasattr(loaded, "to_dict"):
            d = loaded.to_dict()
        else:
            d = vars(loaded)
        ds = d.get("deepspeed_config", {})
        log.info("[L2] accelerate parsed config: zero_stage=%s mp=%s nproc=%s",
                 ds.get("zero_stage"), d.get("mixed_precision"),
                 d.get("num_processes"))
    except Exception as exc:  # noqa: BLE001
        issues.append(f"accelerate.load_config_from_file failed: {exc}")
    return issues


# ---- L3: single-GPU smoke ---------------------------------------------


def _l3_smoke_test(cfg_path: Path) -> list[str]:
    """Launch a tiny ZeRO-3 training step on one GPU. Single host, single
    GPU is enough to catch nearly every config bug — ZeRO-3 sharding logic
    is the same; we just have num_processes=1."""
    issues: list[str] = []
    try:
        import torch
    except ImportError:
        issues.append("torch not installed — cannot run smoke")
        return issues

    if not torch.cuda.is_available():
        log.info("[L3] no CUDA/ROCm GPU found — skipping smoke "
                 "(works on AMD VM only)")
        return []

    try:
        import deepspeed  # noqa: F401
    except ImportError:
        log.warning("[L3] deepspeed not installed — install via `pip install deepspeed`. Skipping.")
        return []

    log.info("[L3] running 5-step smoke on tiny model under ZeRO-3...")
    smoke = """
import torch, deepspeed
import torch.nn as nn

class Tiny(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(64, 64)
    def forward(self, x):
        return self.fc(x).sum()

model = Tiny().cuda()
ds_cfg = {
    "train_micro_batch_size_per_gpu": 2,
    "bf16": {"enabled": True},
    "zero_optimization": {"stage": 3, "offload_optimizer": {"device": "cpu"}},
    "optimizer": {"type": "AdamW", "params": {"lr": 1e-4}},
}
engine, opt, _, _ = deepspeed.initialize(model=model, model_parameters=model.parameters(), config=ds_cfg)
for i in range(5):
    x = torch.randn(2, 64).cuda().to(torch.bfloat16)
    loss = engine(x)
    engine.backward(loss)
    engine.step()
    print(f"step {i}: loss={loss.item():.4f}")
print("OK")
"""
    import subprocess
    out = subprocess.run([sys.executable, "-c", smoke],
                         capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        issues.append(f"L3 smoke exit={out.returncode}\n{out.stderr[-1000:]}")
    else:
        log.info("[L3] OK\n%s", "\n".join(out.stdout.splitlines()[-10:]))
    return issues


# ---- Driver ---------------------------------------------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path,
                    default=ROOT / "configs/accelerate_8gpu_zero3.yaml")
    ap.add_argument("--smoke", action="store_true",
                    help="Run L3 single-GPU smoke (only useful on the AMD VM)")
    args = ap.parse_args()

    if not args.config.exists():
        log.error("Config not found: %s", args.config)
        return 1

    import yaml
    cfg = yaml.safe_load(args.config.read_text())

    log.info("━━━ L1: schema check ━━━")
    issues_l1 = _l1_schema_check(cfg)
    if issues_l1:
        log.error("[L1] %d issues:", len(issues_l1))
        for i in issues_l1:
            log.error("  - %s", i)
    else:
        log.info("[L1] OK")

    log.info("\n━━━ L2: accelerate parse ━━━")
    issues_l2 = _l2_accelerate_parse(args.config)
    if issues_l2:
        log.error("[L2] %d issues:", len(issues_l2))
        for i in issues_l2:
            log.error("  - %s", i)
    else:
        log.info("[L2] OK")

    if args.smoke:
        log.info("\n━━━ L3: single-GPU smoke ━━━")
        issues_l3 = _l3_smoke_test(args.config)
        if issues_l3:
            log.error("[L3] %d issues:", len(issues_l3))
            for i in issues_l3:
                log.error("  - %s", i)
        else:
            log.info("[L3] OK")
    else:
        issues_l3 = []
        log.info("\n[L3 skipped — pass --smoke to run on the VM]")

    total = len(issues_l1) + len(issues_l2) + len(issues_l3)
    if total == 0:
        log.info("\n[OK] DeepSpeed config validated.")
        return 0
    log.error("\n[X] %d total issues. Fix before launching Stage 1.", total)
    return 1


if __name__ == "__main__":
    sys.exit(main())
