"""wandb_monitor.py — read-only window into a running Lysos training run.

Lets the operator (or me, from this conversation) peek at a remote training
run without SSHing into the VM. Uses the wandb public API so it works
from anywhere with WANDB_API_KEY.

Subcommands:
  list                  — list all runs in the lysos project
  status [RUN_ID]       — current step / loss / reward / cost / GPU util
  tail [RUN_ID] [-n N]  — last N rows of metric history
  alert                 — return non-zero if any active run is in trouble
                          (cost > 80% budget, loss diverging, OOM crash)
  diff RUN_A RUN_B      — compare reward decomposition between two runs

If RUN_ID is omitted, monitor picks the most recent run with the
matching tag (default 'amd-mi300x'). Tag selection avoids accidentally
reporting the bootstrap run.

Examples:
  python scripts/wandb_monitor.py list
  python scripts/wandb_monitor.py status                  # latest stage1 run
  python scripts/wandb_monitor.py status --tag stage3
  python scripts/wandb_monitor.py tail -n 30
  python scripts/wandb_monitor.py alert                   # cron-friendly
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load_env():
    try:
        import verify_keys as vk
        vk._load_dotenv(ROOT / ".env")
        vk._load_wandb_netrc()
    except Exception:
        pass


def _get_api():
    _load_env()
    try:
        import wandb
    except ImportError:
        print("wandb not installed. pip install wandb", file=sys.stderr)
        sys.exit(2)
    return wandb.Api()


def _resolve_entity_project() -> tuple[str, str]:
    """Use env if set & non-empty; otherwise the canonical Lysos project."""
    entity = os.environ.get("WANDB_ENTITY") or "rahulrajpurohit005-lysos"
    project = os.environ.get("WANDB_PROJECT") or "lysos"
    return entity, project


def _select_run(api, run_id: str | None, tag: str | None,
                entity: str, project: str):
    if run_id:
        return api.run(f"{entity}/{project}/{run_id}")
    runs = api.runs(f"{entity}/{project}",
                    filters={"tags": {"$in": [tag]}} if tag else None,
                    order="-created_at")
    runs_list = list(runs)
    if not runs_list:
        print(f"No runs found in {entity}/{project} with tag={tag!r}",
              file=sys.stderr)
        sys.exit(1)
    return runs_list[0]


# ---------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------


def cmd_list(args):
    api = _get_api()
    entity, project = _resolve_entity_project()
    runs = list(api.runs(f"{entity}/{project}", order="-created_at"))
    print(f"{'STATE':<10}{'NAME':<35}{'TAGS':<35}{'CREATED'}")
    print("-" * 110)
    for r in runs[: args.limit]:
        tags = ",".join(r.tags or [])[:33]
        print(f"{r.state:<10}{r.name[:33]:<35}{tags:<35}"
              f"{r.created_at[:19]}")


def cmd_status(args):
    api = _get_api()
    entity, project = _resolve_entity_project()
    run = _select_run(api, args.run_id, args.tag, entity, project)
    s = run.summary._json_dict if hasattr(run.summary, "_json_dict") else dict(run.summary)
    cfg = run.config

    print(f"━━━ run: {run.name} ━━━")
    print(f"  id        : {run.id}")
    print(f"  url       : {run.url}")
    print(f"  state     : {run.state}")
    print(f"  tags      : {','.join(run.tags or [])}")
    print(f"  created   : {run.created_at}")
    runtime = getattr(run, "runtime", None) or run._attrs.get("runtime") or 0
    if runtime:
        print(f"  duration  : {runtime}s ({runtime/3600:.2f}h)")

    print(f"\n━━━ training ━━━")
    for k in ("train/global_step", "train/loss", "train/learning_rate",
              "train/grad_norm", "train/reward", "train/kl",
              "eval/avg_composite", "eval/n_valid"):
        v = s.get(k)
        if v is not None:
            print(f"  {k:<28}  {v}")

    print(f"\n━━━ reward decomposition ━━━")
    rwd_keys = sorted([k for k in s.keys() if k.startswith("reward/")])
    if rwd_keys:
        for k in rwd_keys:
            print(f"  {k:<28}  {s[k]}")
    else:
        print("  (no reward/* metrics yet)")

    print(f"\n━━━ cost ━━━")
    for k in ("cost/hours_elapsed", "cost/per_hour", "cost/spent_usd",
              "cost/projected_total_usd", "cost/budget_pct_used"):
        v = s.get(k)
        if v is not None:
            print(f"  {k:<28}  ${v:.2f}" if "usd" in k or "per_hour" in k
                  else f"  {k:<28}  {v}")

    # Hardware
    print(f"\n━━━ hardware (system/*) ━━━")
    sys_keys = sorted([k for k in s.keys() if k.startswith("system/")])[:6]
    for k in sys_keys:
        print(f"  {k:<28}  {s[k]}")


def cmd_tail(args):
    api = _get_api()
    entity, project = _resolve_entity_project()
    run = _select_run(api, args.run_id, args.tag, entity, project)
    keys = ["_step", "train/loss", "train/reward", "train/kl",
            "eval/avg_composite", "cost/projected_total_usd"]
    history = list(run.scan_history(keys=keys))
    print(f"━━━ tail of {run.name} (last {args.lines} rows) ━━━")
    headers = "  ".join(f"{k:<24}" for k in keys)
    print(headers)
    for row in history[-args.lines:]:
        cells = "  ".join(
            f"{(row.get(k) if row.get(k) is not None else ''):<24}"
            for k in keys
        )
        print(cells)


def cmd_alert(args):
    """Return exit code 0 = healthy, 1 = budget warning, 2 = run failed,
    3 = loss diverging."""
    api = _get_api()
    entity, project = _resolve_entity_project()

    runs = list(api.runs(f"{entity}/{project}",
                         filters={"state": {"$in": ["running", "crashed", "failed"]}},
                         order="-created_at"))
    if not runs:
        print("[OK] No active runs.")
        return 0

    exit_code = 0
    for run in runs:
        s = dict(run.summary)

        if run.state in ("crashed", "failed"):
            print(f"[ERR] {run.name} state={run.state}")
            print(f"      url: {run.url}")
            exit_code = max(exit_code, 2)
            continue

        # Budget alarm
        pct = s.get("cost/budget_pct_used")
        if pct is not None and pct >= 80:
            print(f"[BUDGET] {run.name} at {pct:.0f}% of budget")
            print(f"      url: {run.url}")
            exit_code = max(exit_code, 1)

        # Loss divergence
        loss = s.get("train/loss")
        if loss is not None and loss > 100:
            print(f"[LOSS] {run.name} loss={loss:.1f} (diverging)")
            exit_code = max(exit_code, 3)

        # Reward stuck at 0
        reward = s.get("train/reward")
        step = s.get("train/global_step", 0)
        if reward is not None and reward < 0.05 and step > 200:
            print(f"[REWARD] {run.name} reward={reward:.3f} at step {step} "
                  f"— policy may be collapsed")
            exit_code = max(exit_code, 1)

    if exit_code == 0:
        print(f"[OK] {len(runs)} active runs, all healthy")
    return exit_code


def cmd_diff(args):
    """Compare two runs side-by-side."""
    api = _get_api()
    entity, project = _resolve_entity_project()
    a = _select_run(api, args.run_a, None, entity, project)
    b = _select_run(api, args.run_b, None, entity, project)
    sa, sb = dict(a.summary), dict(b.summary)
    keys = sorted(set(sa.keys()) | set(sb.keys()))
    keys = [k for k in keys if k.startswith(("reward/", "eval/", "train/", "cost/"))]
    print(f"{'KEY':<32}  {'A: ' + a.name[:18]:<20}  {'B: ' + b.name[:18]:<20}  DELTA")
    print("-" * 100)
    for k in keys:
        va, vb = sa.get(k), sb.get(k)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            delta = vb - va
            print(f"{k:<32}  {va:<20.4f}  {vb:<20.4f}  {delta:+.4f}")


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    p_status = sub.add_parser("status")
    p_status.add_argument("run_id", nargs="?", default=None)
    p_status.add_argument("--tag", default=None)
    p_status.set_defaults(func=cmd_status)

    p_tail = sub.add_parser("tail")
    p_tail.add_argument("run_id", nargs="?", default=None)
    p_tail.add_argument("--tag", default=None)
    p_tail.add_argument("-n", "--lines", type=int, default=20)
    p_tail.set_defaults(func=cmd_tail)

    p_alert = sub.add_parser("alert")
    p_alert.set_defaults(func=cmd_alert)

    p_diff = sub.add_parser("diff")
    p_diff.add_argument("run_a")
    p_diff.add_argument("run_b")
    p_diff.set_defaults(func=cmd_diff)

    args = ap.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
