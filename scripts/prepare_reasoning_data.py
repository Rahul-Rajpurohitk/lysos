"""Stage 2 reasoning-task slice — chain-of-thought / explanation training.

Transforms three text sources into SFT examples that teach the model HOW
to reason about chemistry, not just lookup tables:

  Wikipedia (data/raw/wikipedia_amr.csv)
    → drug_mechanism, drug_indication, drug_resistance, drug_history,
      pathogen_brief, amr_concept tasks
  PubMed     (data/raw/pubmed_amr.csv)
    → abstract_qa, abstract_summarize tasks
  CARD       (data/raw/card_resistance.json)
    → resistance_gene_explain, drug_class_resistance tasks

Output: HF Dataset at data/processed/amr-stage2-reasoning/
        ready to be merged with the main Stage 2 dataset.

Usage:

    python scripts/prepare_reasoning_data.py
    python scripts/prepare_reasoning_data.py \\
        --push-to-hub rahul24raj/lysos-amr-stage2-reasoning
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] reasoning | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("reasoning")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _msg(user: str, assistant: str, task: str) -> dict:
    return {
        "task": task,
        "split": "train",
        "prompt": user,
        "response": assistant,
        "messages": json.dumps([
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]),
    }


# ---------------------------------------------------------------------------
# WIKIPEDIA → reasoning tasks
# ---------------------------------------------------------------------------


def _truncate(text: str, max_chars: int = 1200) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(". ", 1)[0]
    return cut + "."


def build_wikipedia_examples(path: Path) -> list[dict]:
    if not path.exists():
        log.warning("Wikipedia source missing: %s", path)
        return []
    import pandas as pd
    df = pd.read_csv(path)
    log.info("Wikipedia: %d articles", len(df))

    out: list[dict] = []
    for _, row in df.iterrows():
        title = str(row.get("title", "")).strip()
        if not title:
            continue

        # 1. Mechanism Q&A
        mech = _truncate(str(row.get("mechanism", "")), 1200)
        if mech and len(mech) > 80:
            user = (
                "Instructions: Explain the mechanism of action of the named drug.\n"
                f"Question: How does {title} kill or inhibit bacteria?"
            )
            out.append(_msg(user, mech, task="drug_mechanism"))

        # 2. Indication
        ind = _truncate(str(row.get("indication", "")), 800)
        if ind and len(ind) > 80:
            user = (
                "Instructions: Describe the medical uses of the named drug.\n"
                f"Question: What is {title} used to treat?"
            )
            out.append(_msg(user, ind, task="drug_indication"))

        # 3. Resistance
        resist = _truncate(str(row.get("resistance", "")), 1200)
        if resist and len(resist) > 80:
            user = (
                "Instructions: Explain how bacteria can become resistant to the named drug.\n"
                f"Question: By what mechanisms do bacteria resist {title}?"
            )
            out.append(_msg(user, resist, task="drug_resistance"))

        # 4. History
        hist = _truncate(str(row.get("history", "")), 800)
        if hist and len(hist) > 80:
            user = (
                "Instructions: Briefly summarize the discovery / development "
                "history of the named drug.\n"
                f"Question: When and how was {title} discovered?"
            )
            out.append(_msg(user, hist, task="drug_history"))

        # 5. General brief — first ~1200 chars of full extract
        full = _truncate(str(row.get("extract", "")), 1500)
        if full and len(full) > 200:
            # Decide which task this is based on title
            tlow = title.lower()
            if any(p.lower() in tlow for p in
                   ["staphylococcus", "tuberculosis", "escherichia",
                    "klebsiella", "acinetobacter", "pseudomonas",
                    "enterococcus", "neisseria"]):
                task = "pathogen_brief"
                user = (
                    "Instructions: Provide a clinically-relevant overview of "
                    "the named pathogen, including its drug-resistance profile.\n"
                    f"Question: Tell me about {title}."
                )
            elif any(c in tlow for c in
                     ["resistance", "lactamase", "efflux", "ribosom",
                      "peptidoglycan", "outer membrane", "gyrase",
                      "topoisomer", "plasmid", "transposon", "integron",
                      "horizontal gene"]):
                task = "amr_concept"
                user = (
                    "Instructions: Define the AMR concept clearly, with "
                    "biological context and examples.\n"
                    f"Question: What is {title}?"
                )
            else:
                task = "drug_overview"
                user = (
                    "Instructions: Give a concise but complete overview of the named "
                    "antibiotic — class, indications, mechanism, key resistance issues.\n"
                    f"Question: Summarize what's important about {title}."
                )
            out.append(_msg(user, full, task=task))

    log.info("  → %d Wikipedia-derived examples", len(out))
    return out


# ---------------------------------------------------------------------------
# PUBMED → abstract Q&A
# ---------------------------------------------------------------------------


def build_pubmed_examples(path: Path) -> list[dict]:
    if not path.exists():
        log.warning("PubMed source missing: %s", path)
        return []
    import pandas as pd
    df = pd.read_csv(path)
    log.info("PubMed: %d abstracts", len(df))

    out: list[dict] = []
    for _, row in df.iterrows():
        title = str(row.get("title", "")).strip()
        abstract = str(row.get("abstract", "")).strip()
        if not title or not abstract or len(abstract) < 200:
            continue

        # 1. Title → abstract summarization (article summarization)
        user = (
            "Instructions: Given the title of a research article, summarize what "
            "the article would conclude about its topic, in 3-6 sentences. Be "
            "specific about mechanism / outcome / implication.\n"
            f"Article title: {title}"
        )
        # Keep just first ~1200 chars of the abstract
        out.append(_msg(user, _truncate(abstract, 1200),
                        task="abstract_summarize"))

        # 2. Single-question Q&A: pose a generic "what does this paper find?"
        user2 = (
            "Instructions: Read the research abstract and identify the key "
            "antibacterial / AMR-related finding in 2-3 sentences.\n"
            f"Abstract: {_truncate(abstract, 2000)}"
        )
        # Take first 1-2 sentences as the gold answer (the punchline)
        sents = re.split(r"(?<=[.!?])\s+", abstract)
        if sents:
            answer = " ".join(sents[: max(1, min(2, len(sents) // 4))])
            if len(answer) > 80:
                out.append(_msg(user2, _truncate(answer, 600),
                                task="abstract_qa"))

    log.info("  → %d PubMed-derived examples", len(out))
    return out


# ---------------------------------------------------------------------------
# CARD → resistance-gene explanations
# ---------------------------------------------------------------------------


def build_card_examples(path: Path) -> list[dict]:
    if not path.exists():
        log.warning("CARD source missing: %s", path)
        return []
    import pandas as pd
    df = pd.read_csv(path) if path.suffix == ".csv" else None
    if df is None:
        try:
            with open(path) as f:
                data = json.load(f)
            # CARD's processed JSON is a list of resistance entries
            if isinstance(data, list):
                df = pd.DataFrame(data)
            elif isinstance(data, dict):
                df = pd.DataFrame(list(data.values()))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not parse CARD: %s", exc)
            return []
    if df is None or df.empty:
        return []
    log.info("CARD: %d resistance entries", len(df))

    out: list[dict] = []
    # CARD column names vary — try a few common ones
    name_cols = ["aro_name", "gene_name", "name", "ARO_name"]
    desc_cols = ["aro_description", "description", "ARO_description"]
    drug_cols = ["drug_class", "drugs", "drug"]
    pathogen_cols = ["pathogen", "ncbi_taxonomy_name", "organism", "pathogen_short"]

    def _first_col(row, candidates):
        for c in candidates:
            if c in row and row[c] and str(row[c]) != "nan":
                return str(row[c])
        return ""

    for _, row in df.iterrows():
        gene = _first_col(row, name_cols)
        desc = _first_col(row, desc_cols)
        drug_cls = _first_col(row, drug_cols)
        pathogen = _first_col(row, pathogen_cols)
        if not gene:
            continue

        if desc and len(desc) > 60:
            user = (
                "Instructions: Explain how the named bacterial gene confers "
                "antibiotic resistance.\n"
                f"Question: What is the resistance mechanism of {gene}?"
            )
            out.append(_msg(user, _truncate(desc, 800),
                            task="resistance_gene_explain"))

        if drug_cls and pathogen:
            user = (
                "Instructions: Identify which drug class is targeted by the "
                "named resistance gene in the named pathogen.\n"
                f"Question: In {pathogen}, the gene {gene} confers resistance "
                f"to which drug class?"
            )
            answer = _truncate(drug_cls, 200)
            out.append(_msg(user, answer, task="drug_class_resistance"))

    log.info("  → %d CARD-derived examples", len(out))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, default=Path("data/raw"))
    p.add_argument("--output", type=Path,
                   default=Path("data/processed/amr-stage2-reasoning"))
    p.add_argument("--push-to-hub", type=str, default=None)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    examples = []
    examples += build_wikipedia_examples(args.data_root / "wikipedia_amr.csv")
    examples += build_pubmed_examples(args.data_root / "pubmed_amr.csv")
    examples += build_card_examples(args.data_root / "card_resistance.json")

    if not examples:
        log.error("No examples produced. Run the source loaders first:")
        log.error("  python -m src.data.wikipedia")
        log.error("  python -m src.data.pubmed --max-per-query 100")
        return 1

    rnd = random.Random(args.seed)
    rnd.shuffle(examples)
    n_eval = max(50, len(examples) // 25)
    eval_set = examples[:n_eval]
    train_set = examples[n_eval:]
    for r in eval_set:
        r["split"] = "valid"

    from collections import Counter
    log.info("=" * 60)
    log.info("Total reasoning examples: %d", len(examples))
    for task, n in Counter(e["task"] for e in examples).most_common():
        log.info("  %-30s %d", task, n)
    log.info("Train: %d, Eval: %d", len(train_set), len(eval_set))

    try:
        import pandas as pd
        from datasets import Dataset, DatasetDict
    except ImportError as exc:
        log.error("Missing deps: %s", exc)
        return 2

    ds = DatasetDict({
        "train": Dataset.from_pandas(pd.DataFrame(train_set), preserve_index=False),
        "valid": Dataset.from_pandas(pd.DataFrame(eval_set), preserve_index=False),
    })
    args.output.mkdir(parents=True, exist_ok=True)
    ds.save_to_disk(str(args.output))
    log.info("Wrote %s", args.output)

    if args.push_to_hub:
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        if not token:
            log.error("--push-to-hub needs HF_TOKEN")
            return 3
        ds.push_to_hub(args.push_to_hub, token=token, private=False)
        log.info("✓ pushed to %s", args.push_to_hub)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
