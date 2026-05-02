"""TxGemma-replication benchmark harness for Stage 1.

After Stage 1 fine-tuning, we want to verify that our model has matched or
beaten the published TxGemma-27B numbers on the standard ADMET / Tox tasks.
This script:

  1. Loads our Stage 1 checkpoint (default: rahul24raj/txgemma-4-31b)
  2. Runs TDC's standard test set for each task (held out from training)
  3. Computes per-task metrics (AUROC for classification, MAE for regression)
  4. Compares to the published TxGemma-27B baseline + records to wandb / JSON

Usage on the VM (post-Stage 1):

    python scripts/bench_stage1.py \\
        --model-id rahul24raj/txgemma-4-31b \\
        --output data/audits/stage1_bench.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] bench | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bench")


# Published TxGemma-27B test-set numbers (from Google's tech report).
# Values are AUROC for classification, MAE for regression (lower-is-better).
TXGEMMA_27B_BASELINE = {
    # classification — AUROC
    "BBB_Martins":             {"metric": "auroc", "value": 0.901},
    "HIA_Hou":                 {"metric": "auroc", "value": 0.957},
    "Pgp_Broccatelli":         {"metric": "auroc", "value": 0.918},
    "Bioavailability_Ma":      {"metric": "auroc", "value": 0.703},
    "AMES":                    {"metric": "auroc", "value": 0.870},
    "DILI":                    {"metric": "auroc", "value": 0.887},
    "hERG":                    {"metric": "auroc", "value": 0.798},
    "Skin_Reaction":           {"metric": "auroc", "value": 0.760},
    "Carcinogens_Lagunin":     {"metric": "auroc", "value": 0.793},
    "CYP3A4_Veith":            {"metric": "auroc", "value": 0.923},
    "CYP2D6_Veith":            {"metric": "auroc", "value": 0.892},
    # regression — MAE (lower is better)
    "Lipophilicity_AstraZeneca": {"metric": "mae", "value": 0.464},
    "Solubility_AqSolDB":      {"metric": "mae", "value": 0.823},
    "Caco2_Wang":              {"metric": "mae", "value": 0.281},
    "Half_Life_Obach":         {"metric": "mae", "value": 5.40},
    "PPBR_AZ":                 {"metric": "mae", "value": 7.85},
    "LD50_Zhu":                {"metric": "mae", "value": 0.582},
}

CLASSIFICATION_TASKS = {
    k for k, v in TXGEMMA_27B_BASELINE.items() if v["metric"] == "auroc"
}
REGRESSION_TASKS = {
    k for k, v in TXGEMMA_27B_BASELINE.items() if v["metric"] == "mae"
}

YES_RE = re.compile(r"\b(yes|positive|active|true)\b", re.I)
NO_RE = re.compile(r"\b(no|negative|inactive|false)\b", re.I)
NUM_RE = re.compile(r"-?\d+\.?\d*")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--model-id", required=True,
                   help="HF Hub or local path to Stage 1 checkpoint")
    p.add_argument("--dataset", default="rahul24raj/lysos-tdc-stage1",
                   help="HF Hub dataset of TDC tasks")
    p.add_argument("--tasks", default="",
                   help="Comma-separated task subset (default: all bench-able)")
    p.add_argument("--max-per-task", type=int, default=200,
                   help="Cap test rows per task for speed")
    p.add_argument("--output", type=Path,
                   default=Path("data/audits/stage1_bench.json"))
    p.add_argument("--max-new-tokens", type=int, default=16,
                   help="Generation budget per example")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--device", default="cuda")
    p.add_argument("--temperature", type=float, default=0.0)
    return p.parse_args()


def _parse_classification(text: str) -> int | None:
    """Map free-text response → 0/1."""
    if YES_RE.search(text):
        return 1
    if NO_RE.search(text):
        return 0
    return None


def _parse_regression(text: str) -> float | None:
    m = NUM_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def main() -> int:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    try:
        import torch
        from datasets import load_dataset
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from sklearn.metrics import (
            mean_absolute_error,
            roc_auc_score,
        )
        import numpy as np
    except ImportError as exc:
        log.error("Missing deps: %s. pip install transformers datasets sklearn torch", exc)
        return 2

    log.info("Loading model %s on %s ...", args.model_id, args.device)
    tokenizer = AutoTokenizer.from_pretrained(args.model_id)
    model = AutoModelForCausalLM.from_pretrained(
        args.model_id, torch_dtype=torch.bfloat16, device_map=args.device,
    )
    # Switch to inference mode (PyTorch).
    model.train(False)

    log.info("Loading benchmark dataset %s ...", args.dataset)
    ds = load_dataset(args.dataset, split="test")
    log.info("  %d test rows total", len(ds))

    tasks = (
        [t.strip() for t in args.tasks.split(",") if t.strip()]
        or sorted(set(ds["task"]) & set(TXGEMMA_27B_BASELINE.keys()))
    )
    log.info("Benchmarking %d tasks: %s", len(tasks), tasks)

    results: dict[str, dict] = {}
    for task in tasks:
        sub = ds.filter(lambda r, t=task: r["task"] == t)
        if len(sub) == 0:
            log.warning("  task %s: no test rows", task)
            continue
        if args.max_per_task and len(sub) > args.max_per_task:
            sub = sub.select(range(args.max_per_task))
        log.info("  %-30s n=%d", task, len(sub))

        prompts = [r["prompt"] for r in sub]
        gold = [r["response"] for r in sub]
        preds: list[str] = []
        for i in range(0, len(prompts), args.batch_size):
            batch = prompts[i:i + args.batch_size]
            inputs = tokenizer(
                batch, return_tensors="pt",
                padding=True, truncation=True, max_length=2048,
            ).to(model.device)
            with torch.no_grad():
                gen = model.generate(
                    **inputs,
                    max_new_tokens=args.max_new_tokens,
                    do_sample=args.temperature > 0,
                    temperature=max(args.temperature, 1e-3),
                    pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
                )
            out = tokenizer.batch_decode(
                gen[:, inputs.input_ids.shape[1]:], skip_special_tokens=True,
            )
            preds.extend(o.strip() for o in out)

        is_class = task in CLASSIFICATION_TASKS
        if is_class:
            y_true = [_parse_classification(g) for g in gold]
            y_pred = [_parse_classification(p) for p in preds]
            mask = [a is not None and b is not None for a, b in zip(y_true, y_pred)]
            yt = np.array([t for t, m in zip(y_true, mask) if m])
            yp = np.array([p for p, m in zip(y_pred, mask) if m])
            try:
                auroc = float(roc_auc_score(yt, yp)) if len(set(yt)) > 1 else float("nan")
            except Exception:  # noqa: BLE001
                auroc = float("nan")
            metric = {"metric": "auroc", "value": auroc, "n": int(len(yt))}
        else:
            y_true = [_parse_regression(g) for g in gold]
            y_pred = [_parse_regression(p) for p in preds]
            mask = [a is not None and b is not None for a, b in zip(y_true, y_pred)]
            yt = np.array([t for t, m in zip(y_true, mask) if m])
            yp = np.array([p for p, m in zip(y_pred, mask) if m])
            mae = float(mean_absolute_error(yt, yp)) if len(yt) else float("nan")
            metric = {"metric": "mae", "value": mae, "n": int(len(yt))}

        baseline = TXGEMMA_27B_BASELINE.get(task)
        results[task] = {
            "ours": metric,
            "txgemma_27b_baseline": baseline,
            "delta_vs_baseline": (
                metric["value"] - baseline["value"] if baseline else None
            ),
        }
        log.info("    %s: ours=%.3f  baseline=%.3f  delta=%+.3f",
                 metric["metric"], metric["value"],
                 baseline["value"] if baseline else float("nan"),
                 (metric["value"] - baseline["value"]) if baseline else float("nan"))

    args.output.write_text(json.dumps(results, indent=2))
    log.info("Wrote %s", args.output)

    n_tasks = len(results)
    n_better = sum(
        1 for r in results.values()
        if r.get("delta_vs_baseline") is not None
        and (r["delta_vs_baseline"] > 0 if r["ours"]["metric"] == "auroc"
             else r["delta_vs_baseline"] < 0)
    )
    log.info("=" * 60)
    log.info("Stage 1 vs TxGemma-27B: matched/exceeded on %d / %d tasks",
             n_better, n_tasks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
