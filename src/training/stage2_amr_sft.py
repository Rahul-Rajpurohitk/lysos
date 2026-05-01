"""Stage 2 — AMR specialization SFT on top of Stage 1 (TxGemma-4).

Loads Stage 1 LoRA adapter, merges into base, then trains a new adapter
on the AMR-specific multi-task corpus (data/processed/amr-stage2/).

Run on the AMD Dev Cloud VM (Small 1x MI300X is fine):

    python -m src.training.stage2_amr_sft --config configs/stage2_amr_sft.yaml

If Stage 1 hasn't been pushed to HF Hub yet (still local), override:

    python -m src.training.stage2_amr_sft \
        --config configs/stage2_amr_sft.yaml \
        --override model.base_id=./checkpoints/stage1-txgemma4 \
        --override peft.load_existing_adapter=./checkpoints/stage1-txgemma4

Outputs:
  - LoRA adapter checkpoints in cfg.training.output_dir
  - Pushed to HF Hub at rahul24raj/lysos-base
  - Wandb run logs Stage 2 metrics under stage2 tag
"""

from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] stage2 | %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> int:
    from src.training.sft_runner import add_sft_args, run_sft

    p = argparse.ArgumentParser(description="Stage 2 — AMR specialization SFT")
    add_sft_args(p)
    args = p.parse_args()
    return run_sft(args)


if __name__ == "__main__":
    sys.exit(main())
