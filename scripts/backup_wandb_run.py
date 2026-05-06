"""Read-only backup of a wandb run — full metrics history + metadata + files.

Designed to be safe to run AT ANY TIME, including while training is still
in progress. It only READS from the wandb cloud API; it never calls
`wandb sync` and never touches the live run on the training VM.

Usage:
    # Pull run history + summary (this is the lossless backup)
    python scripts/backup_wandb_run.py --run-id zynunpjr

    # Specify entity/project explicitly if not in env
    python scripts/backup_wandb_run.py --entity rahul24rajpurohit \\
                                       --project lysos-stage1 \\
                                       --run-id zynunpjr

    # Optional: also rsync the on-VM wandb dir as a belt-and-suspenders
    # backup (still read-only — uses rsync's --no-perms to avoid touch).
    # ONLY RUN THIS AFTER TRAINING HAS STOPPED.
    python scripts/backup_wandb_run.py --run-id zynunpjr --vm-rsync

Outputs (under data/training_runs/<run_id>/):
    - history.parquet         : every logged step + every metric column
    - history.csv             : same, csv for sanity-check
    - summary.json            : final scalar summary
    - config.json             : training-time hyperparams
    - metadata.json           : run metadata (host, code, timing)
    - files/                  : artifacts (only if --include-files)
    - vm_rsync/               : copy of the VM wandb dir (only if --vm-rsync)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_BASE = REPO_ROOT / "data" / "training_runs"


def pull_history(entity: str, project: str, run_id: str, out_dir: Path,
                 include_files: bool = False) -> None:
    """Pull run history + summary + config from wandb cloud (read-only)."""
    try:
        import wandb  # type: ignore[import]
    except ImportError:
        print("[error] wandb not installed. Run: pip install wandb pandas pyarrow")
        sys.exit(1)

    api_key = os.getenv("WANDB_API_KEY")
    if not api_key:
        print("[warn] WANDB_API_KEY not set — public runs only. Set it for private runs.")

    out_dir.mkdir(parents=True, exist_ok=True)

    api = wandb.Api()
    full_path = f"{entity}/{project}/{run_id}"
    print(f"[wandb] reading {full_path} from cloud …")
    run = api.run(full_path)

    # Summary (final scalar values)
    (out_dir / "summary.json").write_text(json.dumps(dict(run.summary), indent=2, default=str))
    print(f"[ok] summary.json ({len(run.summary)} keys)")

    # Config (training hyperparams)
    (out_dir / "config.json").write_text(json.dumps(dict(run.config), indent=2, default=str))
    print(f"[ok] config.json ({len(run.config)} keys)")

    # Metadata (host, command, timing)
    md = {
        "id": run.id,
        "name": run.name,
        "state": run.state,
        "created_at": str(run.created_at),
        "tags": list(run.tags),
        "url": run.url,
        "project": run.project,
        "entity": run.entity,
    }
    (out_dir / "metadata.json").write_text(json.dumps(md, indent=2))
    print(f"[ok] metadata.json (state={run.state}, url={run.url})")

    # History — every logged step, every column
    print("[wandb] streaming history (this can take a minute on long runs) …")
    rows = list(run.scan_history())
    print(f"[ok] {len(rows)} history rows")
    if rows:
        try:
            import pandas as pd  # type: ignore[import]
            df = pd.DataFrame(rows)
            df.to_parquet(out_dir / "history.parquet")
            df.to_csv(out_dir / "history.csv", index=False)
            print(f"[ok] history.parquet  ({df.shape[0]} rows × {df.shape[1]} cols)")
            print(f"[ok] history.csv      ({(out_dir / 'history.csv').stat().st_size // 1024} KB)")
        except ImportError:
            (out_dir / "history.json").write_text(json.dumps(rows, default=str))
            print(f"[ok] history.json (pandas not available, fell back to json)")

    # Optional: download artifact files (model checkpoints, etc.)
    if include_files:
        files_dir = out_dir / "files"
        files_dir.mkdir(exist_ok=True)
        for f in run.files():
            try:
                f.download(root=str(files_dir), exist_ok=True)
                print(f"  · {f.name}")
            except Exception as exc:  # noqa: BLE001
                print(f"  [skip] {f.name}: {exc}")


def vm_rsync(remote_host: str, remote_dir: str, out_dir: Path) -> None:
    """Read-only rsync of the on-VM wandb run dir.

    ONLY RUN THIS AFTER TRAINING HAS STOPPED — concurrent writes from the
    training process can corrupt the rsync. Uses --no-perms --no-owner
    so we don't try to recreate root-owned files locally.
    """
    out_sub = out_dir / "vm_rsync"
    out_sub.mkdir(parents=True, exist_ok=True)
    print(f"[rsync] {remote_host}:{remote_dir}/  →  {out_sub}/")
    cmd = [
        "rsync", "-av", "--no-perms", "--no-owner", "--no-group",
        f"{remote_host}:{remote_dir}/",
        f"{out_sub}/",
    ]
    rc = subprocess.call(cmd)
    if rc != 0:
        print(f"[warn] rsync exited {rc}")
    else:
        print("[ok] vm_rsync done")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entity", default=os.getenv("WANDB_ENTITY", "rahul24rajpurohit"))
    ap.add_argument("--project", default=os.getenv("WANDB_PROJECT", "lysos-stage1"))
    ap.add_argument("--run-id", required=True, help="wandb run id (the short hash)")
    ap.add_argument("--include-files", action="store_true",
                    help="Also download artifact files (LARGE for checkpoint runs).")
    ap.add_argument("--vm-rsync", action="store_true",
                    help="Also rsync the on-VM wandb dir. Only safe AFTER training stops.")
    ap.add_argument("--vm-host", default="lysos-vm",
                    help="SSH host for the training VM (default lysos-vm)")
    ap.add_argument("--vm-dir", default=None,
                    help="Remote wandb dir (default auto-resolved by run id)")
    args = ap.parse_args()

    out_dir = OUT_BASE / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[backup] target dir: {out_dir}")

    # Pull cloud-side data (safe at any time)
    pull_history(args.entity, args.project, args.run_id, out_dir,
                 include_files=args.include_files)

    if args.vm_rsync:
        remote_dir = args.vm_dir or f"/shared-docker/lysos/wandb/run-*-{args.run_id}"
        # Resolve glob server-side
        try:
            resolved = subprocess.check_output(
                ["ssh", args.vm_host, f"ls -d {remote_dir}"],
                stderr=subprocess.DEVNULL, text=True,
            ).strip().splitlines()[0]
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] could not resolve VM wandb dir: {exc}")
            return 0
        vm_rsync(args.vm_host, resolved, out_dir)

    print("\n[done] backup complete.")
    print(f"       open: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
