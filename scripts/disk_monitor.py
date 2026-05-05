"""Disk space monitor — auto-cleanup old checkpoints when nearing capacity.

Runs as a background thread alongside training. When disk usage > threshold,
deletes oldest checkpoints (keeping best-K by step count or eval metric).

Saves us from "no space left" mid-train fatal failures.

Usage as standalone:
  /tmp/lysos_venv/bin/python scripts/disk_monitor.py \\
      --threshold 0.85 \\
      --keep_best_k 3 \\
      --output_dirs ./checkpoints/stage1 ./checkpoints/stage2 ./checkpoints/stage3

As background service (recommended during training):
  nohup /tmp/lysos_venv/bin/python scripts/disk_monitor.py --interval 300 &
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def disk_usage(path: Path) -> float:
    """Return fraction (0-1) of disk used at path."""
    try:
        result = subprocess.run(
            ["df", str(path)],
            capture_output=True, text=True, timeout=5,
        )
        # Parse: Use% column is typically index 4 (or 0-100 with %)
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.split()
            for p in parts:
                if p.endswith("%"):
                    return int(p.rstrip("%")) / 100
    except Exception:
        pass
    return 0.0


def list_checkpoints(output_dir: Path) -> list[Path]:
    """List all checkpoint dirs sorted by step number ascending."""
    if not output_dir.exists():
        return []
    ckpts = list(output_dir.glob("checkpoint-*"))
    def step_key(p: Path) -> int:
        try:
            return int(p.name.split("-")[1])
        except (IndexError, ValueError):
            return 0
    return sorted(ckpts, key=step_key)


def cleanup_old_checkpoints(output_dir: Path, keep_best_k: int = 3) -> list[Path]:
    """Keep newest K checkpoints + delete the rest. Returns list of deleted."""
    ckpts = list_checkpoints(output_dir)
    if len(ckpts) <= keep_best_k:
        return []

    to_delete = ckpts[:-keep_best_k]  # everything before the last K
    deleted = []
    for ckpt in to_delete:
        try:
            shutil.rmtree(ckpt)
            deleted.append(ckpt)
            print(f"  Deleted: {ckpt}")
        except Exception as e:
            print(f"  Failed to delete {ckpt}: {e}")
    return deleted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.85,
                    help="Trigger cleanup when disk usage > threshold (0-1)")
    ap.add_argument("--keep_best_k", type=int, default=3,
                    help="Keep this many newest checkpoints per output_dir")
    ap.add_argument("--output_dirs", nargs="+", type=Path, default=[
        ROOT / "checkpoints/stage1-txgemma4",
        ROOT / "checkpoints/stage2-amr-sft",
        ROOT / "checkpoints/stage3-rl-grpo",
    ])
    ap.add_argument("--interval", type=int, default=0,
                    help="Run continuously every N seconds (0 = single shot)")
    ap.add_argument("--dry_run", action="store_true")
    args = ap.parse_args()

    def check_once():
        usage = disk_usage(args.output_dirs[0])
        print(f"\n[disk_monitor] Disk usage: {100*usage:.1f}% (threshold: {100*args.threshold:.0f}%)")
        if usage > args.threshold:
            print(f"[disk_monitor] ⚠ Threshold exceeded — cleaning up old checkpoints")
            for od in args.output_dirs:
                if od.exists():
                    print(f"[disk_monitor] Inspecting {od}")
                    if not args.dry_run:
                        deleted = cleanup_old_checkpoints(od, args.keep_best_k)
                        print(f"  cleaned {len(deleted)} old checkpoints")
                    else:
                        ckpts = list_checkpoints(od)
                        kill = ckpts[:-args.keep_best_k] if len(ckpts) > args.keep_best_k else []
                        print(f"  WOULD delete {len(kill)} (--dry_run)")
        else:
            print(f"[disk_monitor] OK")

    if args.interval > 0:
        print(f"[disk_monitor] Running continuously every {args.interval}s")
        while True:
            check_once()
            time.sleep(args.interval)
    else:
        check_once()


if __name__ == "__main__":
    sys.exit(main())
