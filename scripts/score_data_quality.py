"""Per-row data quality scorer for pro-v10.

Scores every row 0-10 based on:
  - token length (longer = more reasoning depth)
  - structural depth (number of tool calls, citations, structured sections)
  - source signal (teacher distillation > template synthesis > raw lookup)
  - novelty signal (unique content vs duplicate-y boilerplate)

Output: data/processed/pro-v10-quality-scores.parquet
  per-row score + reason flags

Used by build_stage2_pro_v11.py to do quality-weighted sampling.

Run:
  /tmp/lysos_venv/bin/python scripts/score_data_quality.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
from datasets import load_from_disk

ROOT = Path(__file__).resolve().parents[1]
INPUT_DS = ROOT / "data" / "processed" / "amr-stage2-pro-v10"
OUT = ROOT / "data" / "processed" / "pro-v10-quality-scores.parquet"


def score_row(idx: int, row: dict) -> dict:
    """Returns score [0, 10] + per-feature breakdown."""
    msgs_str = row.get("messages", "[]")
    if isinstance(msgs_str, str):
        try:
            msgs = json.loads(msgs_str)
        except Exception:
            msgs = []
    else:
        msgs = msgs_str
    task = row.get("task", "unknown")

    # Feature 1: token length proxy (chars / 4)
    full_text = " ".join(
        m.get("content", "") if isinstance(m.get("content"), str) else json.dumps(m.get("content", ""))
        for m in msgs
    )
    char_len = len(full_text)
    tok_proxy = char_len / 4
    if tok_proxy < 100:
        len_score = 0.5
    elif tok_proxy < 300:
        len_score = 1.5
    elif tok_proxy < 800:
        len_score = 2.5
    elif tok_proxy < 2000:
        len_score = 3.0
    else:
        len_score = 3.5

    # Feature 2: structural depth — number of <tool_call> blocks + DECISION blocks + CITATIONS
    n_tool_calls = full_text.count("<tool_call>") + full_text.count("[Tool]:")
    n_decision = full_text.count("DECISION:") + full_text.count("VERDICT:")
    n_citations = len(re.findall(r"\b\d{4}\b\s*(NEJM|Lancet|CID|AAC|JAC|EID|Cell|Science|Nature|JBC|JMC|PNAS|JCI|JID|JAMA|MMWR|WHO)", full_text))
    n_pdb = len(re.findall(r"\bPDB[\s:]+[0-9][A-Z0-9]{3}\b", full_text)) + len(re.findall(r"\b[0-9][A-Z0-9]{3}\b", full_text)) // 4
    depth = n_tool_calls + n_decision * 0.5 + n_citations * 1.0 + n_pdb * 0.3
    if depth < 1:
        depth_score = 0.3
    elif depth < 5:
        depth_score = 1.5
    elif depth < 15:
        depth_score = 2.5
    else:
        depth_score = 3.0

    # Feature 3: source signal (task name)
    if task.startswith("teacher_arch_"):
        source_score = 2.5  # architecture is high-leverage
    elif task.startswith("teacher_eval_"):
        source_score = 3.0  # eval-aligned is highest leverage
    elif task.startswith("teacher_pdb_pocket") or task.startswith("teacher_mutation"):
        source_score = 3.0  # niche structural depth
    elif task.startswith("teacher_three_way") or task.startswith("teacher_chemistry_self"):
        source_score = 2.5
    elif task.startswith("teacher_") or task in ("long_form_designer_loop", "tool_call_with_result"):
        source_score = 2.0  # other teacher distillation
    elif task in ("activity_cliff", "decoy_negative", "pk_panel"):
        source_score = 2.0  # high-quality synthetic
    elif task in ("safety_refusal", "tool_arg_validation", "held_out_eval"):
        source_score = 2.0  # v6 audit-fix data
    elif task in ("name_to_smiles", "name_to_inchi", "name_to_synonyms",
                   "name_to_cas", "cas_to_name", "natural_product_origin"):
        source_score = 0.8  # lookup tasks; lower leverage but cover identification
    elif task in ("coadd_screen", "admet_panel", "tox_panel", "drug_likeness",
                   "mic_prediction", "safety_panel"):
        source_score = 1.2  # bench-data tasks; moderate leverage
    else:
        source_score = 1.0

    # Feature 4: novelty (rough heuristic: short fixed-prefix outputs penalized)
    last_assist = next((m.get("content", "") for m in reversed(msgs) if m.get("role") == "assistant" and isinstance(m.get("content"), str)), "")
    if len(last_assist) < 50:
        novelty_score = 0.0
    elif last_assist.startswith(("Based on CO-ADD", "Per Therapeutics Data Commons", "VALIDATION_OK", "VALIDATION_FAIL")):
        novelty_score = 0.5
    else:
        novelty_score = 1.0

    total = len_score + depth_score + source_score + novelty_score
    return {
        "row_idx": idx,
        "task": task,
        "char_len": char_len,
        "n_tool_calls": n_tool_calls,
        "n_decision_blocks": n_decision,
        "n_citations": n_citations,
        "len_score": len_score,
        "depth_score": depth_score,
        "source_score": source_score,
        "novelty_score": novelty_score,
        "total_score": round(total, 2),
    }


def main():
    print(f"Loading {INPUT_DS}")
    ds = load_from_disk(str(INPUT_DS))
    print(f"  train rows: {len(ds['train']):,}")

    rows = []
    for i, r in enumerate(ds["train"]):
        rows.append(score_row(i, r))
        if i % 50000 == 0 and i > 0:
            print(f"  scored {i:,}")

    df = pd.DataFrame(rows)
    df.to_parquet(OUT, index=False)

    print(f"\nDone. scored={len(df):,}")
    print(f"\nQuality score distribution:")
    print(f"  min:    {df['total_score'].min():.1f}")
    print(f"  p10:    {df['total_score'].quantile(0.10):.1f}")
    print(f"  p50:    {df['total_score'].median():.1f}")
    print(f"  p90:    {df['total_score'].quantile(0.90):.1f}")
    print(f"  max:    {df['total_score'].max():.1f}")
    print(f"\nTop-quality task buckets (mean score):")
    by_task = df.groupby("task")["total_score"].mean().sort_values(ascending=False)
    print(by_task.head(15))
    print(f"\nLowest-quality task buckets (mean score):")
    print(by_task.tail(10))

    # Reweighting recommendation
    print(f"\nReweighting suggestion (oversample top, downsample bottom):")
    top_threshold = df["total_score"].quantile(0.75)
    bot_threshold = df["total_score"].quantile(0.25)
    print(f"  Top quartile threshold: {top_threshold:.1f}")
    print(f"  Bottom quartile threshold: {bot_threshold:.1f}")
    print(f"  Top quartile rows:    {(df['total_score'] >= top_threshold).sum():,}")
    print(f"  Bottom quartile rows: {(df['total_score'] <= bot_threshold).sum():,}")

    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
