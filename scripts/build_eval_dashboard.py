"""Continuous-eval dashboard — live HTML status snapshot.

Aggregates dataset stats, manifest hashes, eval metrics, training-curve
placeholder. Enables one-glance status for hackathon judges + maintainers.

Output: reports/dashboard.html

Run:
  /tmp/lysos_venv/bin/python scripts/build_eval_dashboard.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "processed" / "MANIFEST.json"
EVAL_REPORT = ROOT / "reports" / "eval_v3.json"
DASHBOARD = ROOT / "reports" / "dashboard.html"


def main():
    manifest = {}
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())
    eval_data = {}
    if EVAL_REPORT.exists():
        eval_data = json.loads(EVAL_REPORT.read_text())

    n_datasets = len(manifest.get("datasets", {}))
    git_sha = manifest.get("git_sha", "?")[:12]
    sdks = manifest.get("sdk_versions", {})
    reward = manifest.get("reward_stack", {})

    metrics = eval_data.get("metrics", {})

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Lysos — Continuous Eval Dashboard</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 1400px; margin: 2rem auto; padding: 0 2rem;
         background: #0d1117; color: #c9d1d9; line-height: 1.5; }}
  h1, h2, h3 {{ color: #58a6ff; }}
  h1 {{ border-bottom: 2px solid #30363d; padding-bottom: 0.5rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
           gap: 1rem; margin: 1.5rem 0; }}
  .card {{ background: #161b22; padding: 1rem 1.25rem; border-radius: 8px;
           border: 1px solid #30363d; }}
  .metric {{ font-size: 2rem; font-weight: bold; color: #3fb950; }}
  .metric.warning {{ color: #d29922; }}
  .metric.error {{ color: #f85149; }}
  .label {{ font-size: 0.85rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.05em; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; font-size: 0.9rem; }}
  th, td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #30363d; }}
  th {{ color: #58a6ff; font-weight: 600; }}
  code {{ background: #21262d; padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.9em; }}
  .status-pass {{ color: #3fb950; }}
  .status-warn {{ color: #d29922; }}
  .status-fail {{ color: #f85149; }}
  .footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #30363d;
             font-size: 0.85rem; color: #8b949e; }}
</style>
</head>
<body>
  <h1>Lysos — Continuous Eval Dashboard</h1>
  <p>Last updated: {datetime.now(timezone.utc).isoformat()} UTC. Git: <code>{git_sha}</code>.</p>

  <h2>Status</h2>
  <div class="grid">
    <div class="card">
      <div class="label">Datasets tracked</div>
      <div class="metric">{n_datasets}</div>
    </div>
    <div class="card">
      <div class="label">Reward components</div>
      <div class="metric">{reward.get('n_components', '?')}</div>
    </div>
    <div class="card">
      <div class="label">Reward weights sum</div>
      <div class="metric">{reward.get('weights_sum', '?')}</div>
    </div>
    <div class="card">
      <div class="label">Git dirty?</div>
      <div class="metric {'warning' if manifest.get('git_dirty') else ''}">
        {'YES' if manifest.get('git_dirty') else 'NO'}
      </div>
    </div>
  </div>

  <h2>Eval metrics</h2>
  <table>
    <tr><th>Metric</th><th>Pre-train</th><th>Post-train</th><th>Target</th><th>Status</th></tr>
"""

    METRIC_TARGETS = {
        "chem_validity": (">95%", "pct_parse"),
        "novelty_tanimoto": (">60% Tanimoto<0.4", "pct_novel"),
        "mic_rmse_holdout": ("<0.7 log", "rmse_log10_mic"),
        "admet_pass_rate": (">70%", "pct_pass"),
        "tool_call_accuracy": (">85%", "pct_tool"),
        "refusal_robustness": ("100% refused", "pct_refused"),
        "reasoning_faithfulness": ("mean ≥0.85", "mean_score"),
    }
    for metric, (target, key) in METRIC_TARGETS.items():
        m = metrics.get(metric, {})
        val = m.get(key, "—")
        if val != "—" and isinstance(val, (int, float)):
            val_str = f"{val:.2f}"
        else:
            val_str = "TBD"
        html += f"<tr><td><b>{metric}</b></td><td>—</td><td>{val_str}</td><td>{target}</td><td><span class='status-warn'>pending model</span></td></tr>\n"

    html += """
  </table>

  <h2>Reward stack</h2>
  <table>
    <tr><th>Component</th><th>Weight</th></tr>
"""
    for name, weight in (reward.get("weights", {}) or {}).items():
        html += f"<tr><td>{name}</td><td>{weight}</td></tr>\n"

    html += """
  </table>

  <h2>SDK versions</h2>
  <table>
    <tr><th>Package</th><th>Version</th></tr>
"""
    for pkg, version in sorted(sdks.items()):
        html += f"<tr><td>{pkg}</td><td><code>{version}</code></td></tr>\n"

    html += f"""
  </table>

  <h2>Datasets on HF (private)</h2>
  <ul>
    <li><code>rahul24raj/lysos-amr-stage2-pro-v3</code> — 409K train, audit-fix baseline</li>
    <li><code>rahul24raj/lysos-amr-stage2-pro-v4</code> — 545K train, +tool-call-results +long-form +decoys +activity-cliffs</li>
    <li><code>rahul24raj/lysos-amr-stage2-pro-v5</code> — 308K train, deep-audit cleaned</li>
    <li><code>rahul24raj/lysos-amr-stage2-pro-v6</code> — pro-v5 + 3K chem teacher</li>
    <li><code>rahul24raj/lysos-amr-stage2-pro-v7</code> — pro-v5 + 5K chem + 6.5K systems teacher</li>
    <li><code>rahul24raj/lysos-amr-stage2-pro-v8</code> — pro-v5 + 43.5K teacher (5 layers)</li>
    <li><code>rahul24raj/lysos-amr-stage2-pro-v9</code> — pro-v5 + 60.65K teacher (6 layers)</li>
    <li><code>rahul24raj/lysos-amr-stage2-pro-v10</code> — pro-v5 + 78.15K teacher (7 layers)</li>
    <li><code>rahul24raj/lysos-amr-stage2-pro-v11</code> — pro-v10 quality-weighted (DEFAULT)</li>
    <li><code>rahul24raj/lysos-rl-prompts-v3</code> — 12K enriched RL prompts</li>
  </ul>

  <h2>Training pipeline</h2>
  <p>Stage 0 (sprint plan) → Stage 1 (TxGemma-4 SFT, 8x MI300X ~6h) → Stage 2 (Lysos AMR-spec SFT, 1x MI300X ~12h) → Stage 3 (GRPO RL, 1x MI300X ~10h) → Stage 4 (Eval) → Stage 5 (Deploy)</p>
  <p><b>Current state</b>: data prep complete (78K teacher distillation, quality-weighted pro-v11 on HF, manifest tracked, eval harness + adversarial + OOD probes ready). Awaiting AMD MI300X credits for Stage 1-3 training.</p>

  <div class="footer">
    Generated by <code>scripts/build_eval_dashboard.py</code> — refresh by re-running.
  </div>
</body>
</html>
"""

    DASHBOARD.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD.write_text(html)
    print(f"Wrote {DASHBOARD}")
    print(f"Open with: open {DASHBOARD}")


if __name__ == "__main__":
    sys.exit(main())
