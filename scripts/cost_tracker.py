"""Cost tracker — log GPU hours + USD spent per checkpoint.

Reads training_logs/ + extracts step counts + wall-clock time. Maps to
USD via configurable hourly rate per GPU class.

Output: reports/cost_tracker.json + reports/cost_tracker.html dashboard

Usage:
  /tmp/lysos_venv/bin/python scripts/cost_tracker.py
  /tmp/lysos_venv/bin/python scripts/cost_tracker.py --rate-mi300x 4.0  # $4/hr per MI300X
  /tmp/lysos_venv/bin/python scripts/cost_tracker.py --budget 300       # alert at threshold
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]

# Default rates (USD/hr per GPU)
DEFAULT_RATES = {
    "mi300x_small_1gpu": 3.0,    # ~$3/hr per MI300X on AMD Dev Cloud Small
    "mi300x_large_8gpu": 24.0,   # ~$24/hr for 8x MI300X
}


def parse_log(log_path: Path) -> dict:
    """Extract training metrics from a stage log."""
    text = log_path.read_text()
    stats = {
        "log_path": str(log_path),
        "stage": None,
        "n_lines": text.count("\n"),
        "training_started": None,
        "training_completed": None,
        "wall_clock_min": None,
        "n_steps_completed": 0,
        "errors": [],
    }

    # Detect stage from filename
    if "stage1" in log_path.name: stats["stage"] = 1
    elif "stage2" in log_path.name: stats["stage"] = 2
    elif "stage3" in log_path.name: stats["stage"] = 3

    # Find start time
    m = re.search(r"Starting (?:SFT|GRPO):", text)
    if m:
        stats["training_started"] = "from log"

    # Find completion
    m = re.search(r"Training done in (\d+(?:\.\d+)?) minutes", text)
    if m:
        stats["wall_clock_min"] = float(m.group(1))
        stats["training_completed"] = True

    # Step count (last "step X" log line)
    step_matches = re.findall(r"step\s*[:=]?\s*(\d+)", text, re.IGNORECASE)
    if step_matches:
        stats["n_steps_completed"] = max(int(s) for s in step_matches)

    # Errors
    for err in re.findall(r"(?:Error|Traceback|FAILED|OutOfMemoryError).*", text):
        stats["errors"].append(err[:200])

    return stats


def estimate_cost(stats: dict, rates: dict[str, float]) -> dict:
    """Map stage + wall-clock to USD."""
    wall_min = stats.get("wall_clock_min") or 0
    wall_h = wall_min / 60

    if stats.get("stage") == 1:
        rate = rates["mi300x_large_8gpu"]
        gpu_class = "mi300x_large_8gpu"
    else:
        rate = rates["mi300x_small_1gpu"]
        gpu_class = "mi300x_small_1gpu"

    cost = wall_h * rate
    return {
        "stage": stats["stage"],
        "wall_h": wall_h,
        "gpu_class": gpu_class,
        "rate_per_hr": rate,
        "cost_usd": round(cost, 2),
    }


def render_html(summaries: list[dict], total_usd: float, budget: float) -> str:
    """Render HTML dashboard."""
    pct = 100 * total_usd / budget if budget else 0
    color = "#3fb950" if pct < 60 else "#d29922" if pct < 90 else "#f85149"
    rows = "\n".join(
        f"<tr><td>Stage {s.get('stage', '?')}</td><td>{s.get('wall_h', 0):.2f}h</td><td>{s.get('gpu_class', '?')}</td><td>${s.get('rate_per_hr', 0):.2f}</td><td><b>${s.get('cost_usd', 0):.2f}</b></td></tr>"
        for s in summaries
    )
    return f"""<!DOCTYPE html>
<html><head><title>Lysos Cost Tracker</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 2rem; background: #0d1117; color: #c9d1d9; }}
  h1 {{ color: #58a6ff; }}
  .progress {{ background: #21262d; border-radius: 8px; overflow: hidden; height: 32px; margin: 1rem 0; }}
  .bar {{ background: {color}; height: 100%; width: {pct}%; transition: width 0.3s; padding-left: 1rem; line-height: 32px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 0.5rem; border-bottom: 1px solid #30363d; text-align: left; }}
  th {{ color: #58a6ff; }}
</style>
</head><body>
<h1>Lysos Cost Tracker</h1>
<p>Last updated: {datetime.now().isoformat()}</p>
<div class="progress"><div class="bar"><b>${total_usd:.2f}</b> / ${budget} ({pct:.0f}%)</div></div>
<table>
<tr><th>Stage</th><th>Wall hours</th><th>GPU class</th><th>Rate</th><th>Cost</th></tr>
{rows}
</table>
<p><i>Total spent: <b>${total_usd:.2f}</b> | Budget: <b>${budget}</b> | Remaining: <b>${budget - total_usd:.2f}</b></i></p>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log_dir", type=Path, default=ROOT / "training_logs")
    ap.add_argument("--rate-mi300x-small", type=float, default=3.0,
                    help="USD/hr per MI300X (Small 1× class)")
    ap.add_argument("--rate-mi300x-large", type=float, default=24.0,
                    help="USD/hr for 8× MI300X (Large class)")
    ap.add_argument("--budget", type=float, default=300.0,
                    help="Total budget USD")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "cost_tracker")
    args = ap.parse_args()

    rates = {
        "mi300x_small_1gpu": args.rate_mi300x_small,
        "mi300x_large_8gpu": args.rate_mi300x_large,
    }

    if not args.log_dir.exists():
        print(f"No training logs at {args.log_dir} — nothing to track yet.")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        (args.out.with_suffix(".json")).write_text(json.dumps({
            "total_usd": 0,
            "budget": args.budget,
            "stages": [],
        }, indent=2))
        return 0

    summaries = []
    for log_path in sorted(args.log_dir.glob("*.log")):
        stats = parse_log(log_path)
        cost = estimate_cost(stats, rates)
        cost.update({"log_path": str(log_path), "errors": stats.get("errors", [])})
        summaries.append(cost)

    total_usd = sum(s["cost_usd"] for s in summaries)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    (args.out.with_suffix(".json")).write_text(json.dumps({
        "total_usd": total_usd,
        "budget": args.budget,
        "remaining": args.budget - total_usd,
        "pct_used": round(100 * total_usd / args.budget, 1) if args.budget else 0,
        "stages": summaries,
        "rates": rates,
    }, indent=2))

    (args.out.with_suffix(".html")).write_text(render_html(summaries, total_usd, args.budget))

    print(f"\n=== Cost Summary ===")
    for s in summaries:
        print(f"  Stage {s['stage']}: {s['wall_h']:.2f}h × ${s['rate_per_hr']:.2f}/h = ${s['cost_usd']:.2f}")
    print(f"\n  Total: ${total_usd:.2f} / ${args.budget} ({100 * total_usd / args.budget:.0f}%)")
    print(f"  Remaining: ${args.budget - total_usd:.2f}")

    if total_usd >= args.budget * 0.9:
        print(f"\n  ⚠ Budget alert: 90%+ consumed!")

    print(f"\nWrote {args.out}.json + {args.out}.html")


if __name__ == "__main__":
    sys.exit(main())
