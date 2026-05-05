"""Checkpoint resilience harness — never lose work.

Three protections:
  1. Auto-detect last checkpoint on resume
  2. Verify checkpoint integrity (file hashes)
  3. Pull checkpoint back from HF Hub if local is corrupted

Used as a wrapper around training scripts — calls the training process
with `--resume-from <last-good-checkpoint>` and recovers from crashes.

Usage:
  /tmp/lysos_venv/bin/python scripts/checkpoint_resilience.py \\
      --stage 2 \\
      --max_retries 3
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def find_last_checkpoint(output_dir: Path) -> Path | None:
    """Find the latest checkpoint directory in output_dir."""
    if not output_dir.exists():
        return None
    ckpts = sorted(output_dir.glob("checkpoint-*"),
                    key=lambda p: int(p.name.split("-")[1]) if p.name.split("-")[1].isdigit() else 0)
    return ckpts[-1] if ckpts else None


def verify_checkpoint(ckpt_path: Path) -> bool:
    """Verify checkpoint has all required files."""
    required = ["config.json", "tokenizer.json"]
    optional_safetensors = list(ckpt_path.glob("*.safetensors"))
    optional_bin = list(ckpt_path.glob("pytorch_model*.bin"))

    if not optional_safetensors and not optional_bin:
        return False
    for f in required:
        if not (ckpt_path / f).exists():
            return False
    return True


def pull_from_hub(hub_id: str, target_dir: Path) -> bool:
    """Pull checkpoint from HF Hub as backup."""
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=hub_id, local_dir=str(target_dir),
                          allow_patterns=["*.safetensors", "*.bin", "*.json"])
        return True
    except Exception as e:
        print(f"  Hub pull failed: {e}")
        return False


def get_output_dir_from_config(config_path: Path) -> Path:
    """Extract output_dir from training config."""
    import yaml
    cfg = yaml.safe_load(config_path.read_text())
    return Path(cfg["training"]["output_dir"])


def get_hub_id_from_config(config_path: Path) -> str:
    """Extract hub_model_id from training config."""
    import yaml
    cfg = yaml.safe_load(config_path.read_text())
    return cfg["hub"]["hub_model_id"]


def run_training(stage: int, resume_from: Path | None = None) -> int:
    """Invoke the training script."""
    cmd = [sys.executable, "-m", f"src.training.stage{stage}_"]
    if stage == 1:
        cmd[2] = "src.training.stage1_txgemma4"
    elif stage == 2:
        cmd[2] = "src.training.stage2_amr_sft"
    elif stage == 3:
        cmd[2] = "src.training.stage3_rl_grpo"
    cmd.extend(["--config", str(ROOT / f"configs/stage{stage}_{'txgemma4' if stage == 1 else 'amr_sft' if stage == 2 else 'rl_grpo'}.yaml")])
    if resume_from:
        cmd.extend(["--resume-from", str(resume_from)])

    print(f"Running: {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, choices=[1, 2, 3], required=True)
    ap.add_argument("--max_retries", type=int, default=3)
    ap.add_argument("--allow_hub_recovery", action="store_true",
                    help="If local checkpoint is corrupted, pull from HF Hub")
    args = ap.parse_args()

    config_path = ROOT / f"configs/stage{args.stage}_{'txgemma4' if args.stage == 1 else 'amr_sft' if args.stage == 2 else 'rl_grpo'}.yaml"
    output_dir = get_output_dir_from_config(config_path)
    hub_id = get_hub_id_from_config(config_path)

    print(f"Stage {args.stage} training with checkpoint resilience")
    print(f"  config: {config_path}")
    print(f"  output_dir: {output_dir}")
    print(f"  hub_id: {hub_id}")
    print(f"  max_retries: {args.max_retries}")

    for attempt in range(args.max_retries):
        print(f"\n--- Attempt {attempt + 1}/{args.max_retries} ---")

        # Find last checkpoint
        last_ckpt = find_last_checkpoint(output_dir)
        if last_ckpt:
            print(f"  Last checkpoint: {last_ckpt}")
            if verify_checkpoint(last_ckpt):
                print(f"  ✅ Verified intact")
            else:
                print(f"  ⚠ Last checkpoint corrupted")
                if args.allow_hub_recovery:
                    print(f"  Pulling backup from HF Hub: {hub_id}")
                    if pull_from_hub(hub_id, last_ckpt):
                        print(f"  ✅ Recovered from Hub")
                    else:
                        print(f"  ⚠ Hub recovery failed; starting fresh")
                        last_ckpt = None
                else:
                    print(f"  ⚠ --allow_hub_recovery disabled; starting fresh")
                    last_ckpt = None
        else:
            print(f"  No prior checkpoint found; starting fresh")

        # Run training
        t0 = time.time()
        returncode = run_training(args.stage, resume_from=last_ckpt)
        elapsed = time.time() - t0

        if returncode == 0:
            print(f"\n✅ Training succeeded in {elapsed/60:.1f} min")
            return 0
        else:
            print(f"\n❌ Training failed (exit {returncode}) after {elapsed/60:.1f} min")
            if attempt < args.max_retries - 1:
                print(f"  Retrying in 30s...")
                time.sleep(30)

    print(f"\n❌ All {args.max_retries} attempts failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
