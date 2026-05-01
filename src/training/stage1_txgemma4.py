"""Stage 1 — TxGemma-4 (chemistry foundation on Gemma 4).

Replicates Google's TxGemma training recipe on a Gemma 4 base, using the
processed Therapeutics Data Commons (TDC) instruction-tuning corpus.

Run on the AMD Dev Cloud VM (Large 8x MI300X recommended):

    python -m src.training.stage1_txgemma4 --config configs/stage1_txgemma4.yaml

With overrides:

    python -m src.training.stage1_txgemma4 \
        --config configs/stage1_txgemma4.yaml \
        --override training.learning_rate=3e-5 \
        --override training.num_train_epochs=1

Smoke test on a tiny subset:

    python -m src.training.stage1_txgemma4 \
        --config configs/stage1_txgemma4.yaml \
        --smoke-test

Outputs:
  - LoRA adapter checkpoints in cfg.training.output_dir
  - Pushed to HF Hub at cfg.hub.hub_model_id (rahul24raj/txgemma-4-31b)
  - Wandb run at cfg.wandb.project (lysos)
"""

from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] stage1 | %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> int:
    from src.training.sft_runner import add_sft_args, run_sft

    p = argparse.ArgumentParser(description="Stage 1 — TxGemma-4 chemistry foundation")
    add_sft_args(p)
    args = p.parse_args()
    return run_sft(args)


if __name__ == "__main__":
    sys.exit(main())
