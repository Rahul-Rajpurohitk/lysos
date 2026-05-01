"""Evaluation benchmark harness for Lysos.

Compares model outputs across:
  - validity rate
  - mean predicted MIC
  - mean QED (drug-likeness)
  - mean SA score
  - mean hemolysis safety
  - mean novelty (Tanimoto distance from known antibiotics)
  - composite reward

Across:
  - target pathogens (MRSA, Mtb, ESBL+ E. coli, etc.)
  - models (Stage 1 / Stage 2 / Stage 3 / baseline)
  - sampling temperatures

Outputs JSON results + Markdown report for slide deck.

Usage:

    # Eval the latest model on all 8 pathogens
    python -m src.eval.benchmarks \
        --model rahul24raj/lysos-rl \
        --output reports/lysos-rl-bench.json

    # Compare 2 models on one pathogen
    python -m src.eval.benchmarks \
        --models rahul24raj/lysos-base,rahul24raj/lysos-rl \
        --target MRSA \
        --output reports/before-after.json

    # Cross-temperature sweep
    python -m src.eval.benchmarks \
        --model rahul24raj/lysos-rl \
        --temperatures 0.5,0.7,1.0,1.3 \
        --output reports/temperature-sweep.json
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] bench | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bench")

PATHOGEN_CHOICES = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE", "Abaum", "Paer", "VRE", "NGono"]


@dataclass
class BenchmarkRun:
    model: str
    target: str
    temperature: float
    n_samples: int
    candidates: list[dict] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    elapsed_s: float = 0.0


@dataclass
class BenchmarkSuite:
    runs: list[BenchmarkRun] = field(default_factory=list)
    started_at: str = ""
    git_sha: str = ""

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "git_sha": self.git_sha,
            "runs": [
                {
                    "model": r.model,
                    "target": r.target,
                    "temperature": r.temperature,
                    "n_samples": r.n_samples,
                    "elapsed_s": r.elapsed_s,
                    "metrics": r.metrics,
                    # don't include all candidates in summary; write separately
                }
                for r in self.runs
            ],
        }


def aggregate_metrics(candidates: list[Any]) -> dict[str, float]:
    """Compute aggregate metrics from a list of Candidates."""
    if not candidates:
        return {}
    valid = [c for c in candidates if c.combined is not None]
    if not valid:
        return {"validity_rate": 0.0}

    metrics: dict[str, float] = {}
    metrics["n_total"] = len(candidates)
    metrics["n_scored"] = len(valid)
    metrics["validity_rate"] = sum(1 for c in candidates if c.smiles or c.sequence) / len(candidates)

    # Per-component means
    component_keys = list(valid[0].scores.keys())
    for key in component_keys:
        vals = [c.scores[key] for c in valid]
        metrics[f"mean_{key}"] = statistics.fmean(vals)
        metrics[f"std_{key}"] = statistics.pstdev(vals) if len(vals) > 1 else 0.0

    # Composite
    composites = [c.combined for c in valid]
    metrics["mean_composite"] = statistics.fmean(composites)
    metrics["std_composite"] = statistics.pstdev(composites) if len(composites) > 1 else 0.0
    metrics["max_composite"] = max(composites)
    metrics["min_composite"] = min(composites)

    # Top-K means (gives a "best-of-N" view that matters more than mean for design)
    sorted_composites = sorted(composites, reverse=True)
    for k in (1, 5, 10):
        if len(sorted_composites) >= k:
            metrics[f"mean_top{k}_composite"] = statistics.fmean(sorted_composites[:k])

    return metrics


def run_single(
    model_id: str,
    target: str,
    n: int,
    temperature: float,
    modality: str = "smiles",
) -> BenchmarkRun:
    from src.inference.generate import LysosGenerator

    log.info("Bench run: model=%s, target=%s, n=%d, T=%.2f, modality=%s",
             model_id, target, n, temperature, modality)
    t0 = time.perf_counter()

    gen = LysosGenerator(model_id=model_id)
    candidates = gen.design(
        target=target,
        n=n,
        modality=modality,
        temperature=temperature,
        score=True,
    )

    elapsed = time.perf_counter() - t0
    metrics = aggregate_metrics(candidates)

    return BenchmarkRun(
        model=model_id,
        target=target,
        temperature=temperature,
        n_samples=n,
        candidates=[c.to_dict() for c in candidates],
        metrics=metrics,
        elapsed_s=elapsed,
    )


def _git_sha() -> str:
    import subprocess
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def write_markdown_report(suite: BenchmarkSuite, out_path: Path) -> None:
    """Generate a slide-friendly Markdown summary."""
    lines = [
        "# Lysos benchmark report",
        f"_Run: {suite.started_at} · git: `{suite.git_sha}`_",
        "",
        "## Summary",
        "",
        "| Model | Target | T | N | Validity | Composite | Top-1 | Top-10 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in suite.runs:
        m = r.metrics
        lines.append(
            f"| `{r.model}` | {r.target} | {r.temperature:.2f} | {r.n_samples} | "
            f"{m.get('validity_rate', 0):.1%} | "
            f"{m.get('mean_composite', 0):+.3f} ± {m.get('std_composite', 0):.3f} | "
            f"{m.get('mean_top1_composite', 0):+.3f} | "
            f"{m.get('mean_top10_composite', 0):+.3f} |"
        )

    lines.extend(["", "## Per-component breakdown (mean ± std)", ""])
    components = ["validity", "predicted_mic", "drug_likeness_qed", "synthesizability",
                  "hemolysis_safety", "novelty"]
    headers = "| Model | Target | " + " | ".join(components) + " |"
    sep = "|---|" * (len(components) + 2) + "\n"
    lines.append(headers)
    lines.append("|" + "---|" * (len(components) + 2))
    for r in suite.runs:
        m = r.metrics
        cells = [
            f"{m.get(f'mean_{c}', 0):.3f}±{m.get(f'std_{c}', 0):.3f}"
            for c in components
        ]
        lines.append(f"| `{r.model.split('/')[-1]}` | {r.target} | " + " | ".join(cells) + " |")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    log.info("Markdown report → %s", out_path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lysos benchmark harness")
    p.add_argument("--model", type=str, default=None,
                   help="Single model HF ID or path")
    p.add_argument("--models", type=str, default=None,
                   help="Comma-separated list of models to compare")
    p.add_argument("--target", type=str, default=None,
                   choices=PATHOGEN_CHOICES, help="Single pathogen")
    p.add_argument("--targets", type=str, default=None,
                   help=f"Comma-separated subset of {PATHOGEN_CHOICES}")
    p.add_argument("--n-samples", type=int, default=50,
                   help="Number of candidates per (model, target) cell")
    p.add_argument("--temperature", type=float, default=1.0)
    p.add_argument("--temperatures", type=str, default=None,
                   help="Comma-separated list of temperatures (cross-T sweep)")
    p.add_argument("--modality", type=str, default="smiles", choices=["smiles", "peptide"])
    p.add_argument("--output", type=Path, default=Path("reports/bench.json"))
    p.add_argument("--report-md", type=Path, default=None,
                   help="If set, also write a Markdown summary to this path")
    p.add_argument("--save-candidates", action="store_true",
                   help="Save full candidate list (large)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Resolve sets
    models = [args.model] if args.model else (args.models.split(",") if args.models else [])
    if not models:
        log.error("Specify --model or --models")
        return 1

    if args.targets:
        targets = args.targets.split(",")
    elif args.target:
        targets = [args.target]
    else:
        targets = PATHOGEN_CHOICES

    if args.temperatures:
        temps = [float(t) for t in args.temperatures.split(",")]
    else:
        temps = [args.temperature]

    log.info("Cells: %d models × %d targets × %d temps = %d runs",
             len(models), len(targets), len(temps), len(models) * len(targets) * len(temps))

    suite = BenchmarkSuite(
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        git_sha=_git_sha(),
    )

    for model_id in models:
        for target in targets:
            for temperature in temps:
                run = run_single(model_id, target, args.n_samples, temperature, args.modality)
                suite.runs.append(run)
                m = run.metrics
                log.info("  → validity=%.1f%%, composite=%+.3f, top1=%+.3f, %.1fs",
                         m.get("validity_rate", 0) * 100,
                         m.get("mean_composite", 0),
                         m.get("mean_top1_composite", 0),
                         run.elapsed_s)

    # Save
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = suite.to_dict()
    if args.save_candidates:
        payload["candidates_by_run"] = [r.candidates for r in suite.runs]
    with open(args.output, "w") as f:
        json.dump(payload, f, indent=2)
    log.info("Wrote %d run(s) to %s", len(suite.runs), args.output)

    if args.report_md:
        write_markdown_report(suite, args.report_md)

    # Print summary table to stdout
    print("\n=== SUMMARY ===")
    print(f"{'Model':<50} {'Target':<12} {'T':<6} {'Valid%':<8} {'Composite':<12} {'Top-1':<10}")
    for r in suite.runs:
        m = r.metrics
        model_short = r.model.split("/")[-1][:48]
        print(
            f"{model_short:<50} {r.target:<12} {r.temperature:<6.2f} "
            f"{m.get('validity_rate', 0)*100:<8.1f} "
            f"{m.get('mean_composite', 0):<+12.3f} "
            f"{m.get('mean_top1_composite', 0):<+10.3f}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
