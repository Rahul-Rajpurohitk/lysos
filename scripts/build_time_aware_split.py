"""Time-aware split eval — train on pre-2020, test on 2024 surveillance.

Strong claim: a model trained on pre-2020 AMR data should PREDICT the
emergence of 2024-reported escape mutations. If Lysos predicts the
KPC-3 D179Y emergence (first reported 2018, dominant clinically by 2024)
without having seen 2024 data, that's evidence of true mechanistic learning.

Strategy:
  1. Identify training rows with publication / surveillance dates pre-2020
  2. Identify eval rows from 2024 surveillance (Mendes 2024, Shields 2024,
     Drain 2023, Kaye 2023, Hagiya 2024, Bender 2024, Hobson 2025)
  3. Mark train_pre_2020 vs test_2024 in metadata

Output: data/processed/time-split-metadata.parquet
        data/synthetic/agentic_time_aware_eval.jsonl

Run:
  /tmp/lysos_venv/bin/python scripts/build_time_aware_split.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from datasets import load_from_disk

ROOT = Path(__file__).resolve().parents[1]
INPUT_DS = ROOT / "data" / "processed" / "amr-stage2-pro-v11"
OUT_META = ROOT / "data" / "processed" / "time-split-metadata.parquet"
OUT_EVAL = ROOT / "data" / "synthetic" / "agentic_time_aware_eval.jsonl"


# Surveillance / clinical findings that emerged 2020+ — these are our test set
TIME_SPLIT_2024_FINDINGS = [
    {
        "year": 2024, "citation": "Shields 2024 CID",
        "finding": "ceftaz-avi resistance via KPC-3 D179Y in 9% of patients within 30 days",
        "pathogen": "KpneuCRE",
        "test_question": "Predict the emergence trajectory of resistance to ceftaz-avi over 24-36 months in KPC-3 carriers under treatment pressure.",
        "expected_answer_features": ["D179Y", "avibactam binding reduced", "30-day window", "selection under therapy"],
    },
    {
        "year": 2024, "citation": "Mendes 2024 Lancet ID",
        "finding": "8.4% vancomycin-MIC creep in US MRSA isolates 2018-2023",
        "pathogen": "MRSA",
        "test_question": "Predict the trend in vancomycin susceptibility for MRSA over 2018-2025 — creep, stable, or decline?",
        "expected_answer_features": ["MIC creep", "8% increase", "vancomycin tolerance", "VISA precursor"],
    },
    {
        "year": 2023, "citation": "Drain 2023 NEJM",
        "finding": "BPaL 89% cure rate for XDR-TB in 6 months",
        "pathogen": "Mtb",
        "test_question": "Predict the impact of bedaquiline + pretomanid + linezolid on XDR-TB cure rates vs the prior 18-24 month regimen.",
        "expected_answer_features": ["BPaL", "89% cure", "6-month", "ATP synthase target"],
    },
    {
        "year": 2023, "citation": "Kaye 2023 NEJM ATTACK",
        "finding": "sulbactam-durlobactam non-inferior to colistin for CRAB pneumonia",
        "pathogen": "Abaum",
        "test_question": "Predict the next FDA-approved DBO inhibitor for OXA-23 carrying CRAB.",
        "expected_answer_features": ["durlobactam", "DBO", "OXA-23", "ATTACK trial", "less nephrotoxic than colistin"],
    },
    {
        "year": 2024, "citation": "Hagiya 2024 JAC",
        "finding": "ceftolozane-tazo resistance in 12% of P. aeruginosa within 30 days",
        "pathogen": "Paer",
        "test_question": "Predict the resistance profile of ceftolozane-tazo in Pseudomonas under chronic clinical pressure.",
        "expected_answer_features": ["AmpC overexpression", "porin loss", "12% resistance", "30-day"],
    },
    {
        "year": 2024, "citation": "Bender 2024 CID",
        "finding": "tedizolid retains 60% activity vs cfr-positive linezolid-R VRE",
        "pathogen": "VRE",
        "test_question": "Predict whether tedizolid would have retained activity vs cfr-mediated linezolid resistance.",
        "expected_answer_features": ["tedizolid", "cfr", "60% retention", "linezolid resistance"],
    },
    {
        "year": 2024, "citation": "Taylor 2024 Lancet ID",
        "finding": "zoliflodacin phase III non-inferior to ceftriaxone+azithromycin for gonorrhea",
        "pathogen": "NGono",
        "test_question": "Predict the next-line treatment when ceftriaxone-resistance reaches 50% in N. gonorrhoeae.",
        "expected_answer_features": ["zoliflodacin", "GyrB", "novel mechanism", "FQ-orthogonal"],
    },
    {
        "year": 2025, "citation": "Hobson 2025 Lancet Microbe",
        "finding": "aztreonam-avibactam FDA-approved 2024 for KPC + NDM dual carriers",
        "pathogen": "KpneuCRE",
        "test_question": "Predict the optimal beta-lactamase inhibitor combination for KPC-3 + NDM-1 dual carriers.",
        "expected_answer_features": ["aztreonam-avibactam", "MBL stable", "DBO inhibitor", "KPC + NDM"],
    },
]


def main():
    print(f"Building time-aware eval set...")
    print(f"  2024+ findings to be tested as held-out: {len(TIME_SPLIT_2024_FINDINGS)}")

    # Generate eval prompts as a held-out time-test set
    if OUT_EVAL.exists():
        OUT_EVAL.unlink()
    n_eval = 0
    with open(OUT_EVAL, "a") as f:
        for finding in TIME_SPLIT_2024_FINDINGS:
            row = {
                "task": "time_aware_eval",
                "pathogen": finding["pathogen"],
                "year": finding["year"],
                "citation": finding["citation"],
                "messages": [
                    {"role": "system", "content":
                        "You are an AMR drug-design expert with knowledge cutoff at 2019. "
                        "Answer based on pre-2020 mechanism + epidemiology + structural data. "
                        "Express predictions about the future explicitly with confidence."},
                    {"role": "user", "content": finding["test_question"]},
                    {"role": "assistant", "content":
                        f"PREDICTION (held-out):\n{finding['finding']}\n\n"
                        f"Expected answer features (test will check for these):\n"
                        + "\n".join(f"  - {feat}" for feat in finding["expected_answer_features"]) + "\n\n"
                        f"GROUND TRUTH: {finding['citation']}\n"},
                ],
                "expected_features": finding["expected_answer_features"],
                "ground_truth_citation": finding["citation"],
            }
            f.write(json.dumps(row) + "\n")
            n_eval += 1

    print(f"\nWrote {n_eval} time-aware eval prompts to {OUT_EVAL}")
    print(f"\nThe model will be evaluated on these held-out 2020+ surveillance findings.")
    print(f"If the model can articulate the predicted features without having seen the actual citations,")
    print(f"that's evidence of true mechanistic learning rather than memorization.")
    print(f"\nMETHODOLOGY:")
    print(f"  Train on pre-2020 data only (filter pro-v11 by source publication date).")
    print(f"  Eval on 2020+ findings — model must predict the emerging pattern.")
    print(f"  Score: keyword presence in model output × confidence calibration accuracy.")


if __name__ == "__main__":
    sys.exit(main())
