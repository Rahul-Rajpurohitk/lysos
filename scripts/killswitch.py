"""killswitch.py — pull the cord on a runaway training run.

Reads `WANDB_API_KEY` + the canonical entity/project, finds active runs,
and:
  * `--list`     — show currently-active runs
  * `--soft RUN` — request a clean stop (sets state via wandb mark_done +
                  writes a stop-flag the trainer respects via
                  `STOP_FILE_PATH`)
  * `--hard RUN` — additionally kill the remote process via SSH
                  (requires LYSOS_VM_SSH_TARGET in env)
  * `--wipe-all` — hard-stop EVERY active run in the project
                  (use only for cost runaway)

Pair with `src/training/cost_callback.py` budget hard-stop and
`scripts/wandb_monitor.py alert` for full ops cover.

Examples:
  python scripts/killswitch.py --list
  python scripts/killswitch.py --soft abc123
  LYSOS_VM_SSH_TARGET=root@1.2.3.4 python scripts/killswitch.py --hard abc123
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

STOP_FILE_PATH = "/tmp/lysos_stop"


def _api():
    try:
        import verify_keys as vk
        vk._load_dotenv(ROOT / ".env")
        vk._load_wandb_netrc()
    except Exception:
        pass
    import wandb
    return wandb.Api()


def _entity_project() -> tuple[str, str]:
    return (os.environ.get("WANDB_ENTITY") or "rahulrajpurohit005-lysos",
            os.environ.get("WANDB_PROJECT") or "lysos")


def cmd_list():
    api = _api()
    entity, project = _entity_project()
    runs = list(api.runs(f"{entity}/{project}",
                         filters={"state": {"$in": ["running"]}},
                         order="-created_at"))
    if not runs:
        print("No active runs.")
        return 0
    print(f"{'ID':<14}  {'NAME':<40}  {'STATE':<10}  CREATED")
    for r in runs:
        print(f"{r.id:<14}  {r.name[:38]:<40}  {r.state:<10}  {r.created_at}")
    return 0


def cmd_soft(run_id: str):
    """Soft stop: drop a flag file + tell wandb to stop scheduling."""
    api = _api()
    entity, project = _entity_project()
    try:
        run = api.run(f"{entity}/{project}/{run_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"[X] run {run_id!r} not found: {exc}", file=sys.stderr)
        return 1

    print(f"[..] soft-stopping {run.name} ({run.id})")
    # 1) Try wandb's stop API. May not work on all server versions.
    try:
        run.stop()
        print("[ok] wandb.Run.stop() called")
    except Exception as exc:  # noqa: BLE001
        print(f"[!] run.stop() failed: {exc}; will rely on stop-flag file")

    # 2) Write the stop flag locally; the cost callback also checks for
    #    this and will set control.should_training_stop.
    with open(STOP_FILE_PATH, "w") as f:
        f.write(f"requested by killswitch at {run.id}\n")
    print(f"[ok] wrote stop flag {STOP_FILE_PATH}")

    print("[!] If the run is on a remote VM, also write the stop flag there:")
    target = os.environ.get("LYSOS_VM_SSH_TARGET")
    if target:
        try:
            subprocess.run(
                ["ssh", target, f"echo killswitch > {STOP_FILE_PATH}"],
                check=True, timeout=10,
            )
            print(f"[ok] remote stop flag set on {target}")
        except Exception as exc:  # noqa: BLE001
            print(f"[!] remote ssh failed: {exc}")
    else:
        print("    LYSOS_VM_SSH_TARGET=root@host  ssh root@host \"echo > /tmp/lysos_stop\"")
    return 0


def cmd_hard(run_id: str):
    """Hard stop: soft-stop, then SSH-kill the trainer process by PID file."""
    cmd_soft(run_id)
    target = os.environ.get("LYSOS_VM_SSH_TARGET")
    if not target:
        print("[X] LYSOS_VM_SSH_TARGET not set; cannot SSH-kill", file=sys.stderr)
        return 2
    pid_file = "/tmp/lysos_train.pid"
    cmd = (f"if [ -f {pid_file} ]; then "
           f"kill $(cat {pid_file}) 2>/dev/null && "
           f"sleep 2 && kill -9 $(cat {pid_file}) 2>/dev/null; fi")
    try:
        subprocess.run(["ssh", target, cmd], check=True, timeout=15)
        print(f"[ok] SIGTERM+SIGKILL sent to remote trainer on {target}")
    except Exception as exc:  # noqa: BLE001
        print(f"[X] hard-kill failed: {exc}", file=sys.stderr)
        return 3
    return 0


def cmd_wipe_all():
    api = _api()
    entity, project = _entity_project()
    runs = list(api.runs(f"{entity}/{project}",
                         filters={"state": {"$in": ["running"]}},
                         order="-created_at"))
    if not runs:
        print("No active runs.")
        return 0
    print(f"!!! Wiping {len(runs)} active runs !!!")
    for r in runs:
        print(f"  -> {r.id} ({r.name})")
        cmd_hard(r.id)
    return 0


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--soft", metavar="RUN_ID")
    g.add_argument("--hard", metavar="RUN_ID")
    g.add_argument("--wipe-all", action="store_true")
    args = ap.parse_args()

    if args.list:
        return cmd_list()
    if args.soft:
        return cmd_soft(args.soft)
    if args.hard:
        return cmd_hard(args.hard)
    if args.wipe_all:
        return cmd_wipe_all()
    return 1


if __name__ == "__main__":
    sys.exit(main())
