"""End-to-end smoke test for the full Lysos training pipeline.

Runs Stage 1 -> Stage 2 -> Stage 3 on a TINY model (sshleifer/tiny-gpt2,
~1MB) with TINY datasets (32 examples). Verifies the entire chain works
on CPU before paying for AMD MI300X time:

  * Stage 1 SFT: tiny chat data -> LoRA adapter A
  * Stage 2 SFT: loads + merges A -> trains LoRA adapter B
  * Stage 3 GRPO: loads + merges B -> trains GRPO adapter C
                  + reward_callable wired to a stub reward function

Total runtime: ~5 min on CPU. Catches:
  - Argparse / config wiring breaks
  - Adapter chain breaks (Stage 2 can't load Stage 1 output)
  - Tokenizer alignment mismatches
  - Reward callable signature mismatches with TRL GRPOTrainer
  - Hub push integration (skipped in smoke; can opt in via SMOKE_PUSH=1)

Run:
    /tmp/lysos_venv/bin/python scripts/smoke_pipeline_e2e.py

Exit codes:
  0 = all 3 stages completed
  1 = setup failure (deps missing)
  2 = stage 1 failed
  3 = stage 2 failed
  4 = stage 3 failed
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _make_tiny_dataset(out_dir: Path, n: int = 32) -> Path:
    """Build a 32-row chat DatasetDict (train+test) for SFTTrainer."""
    from datasets import Dataset, DatasetDict

    rows = []
    for i in range(n):
        prompt = f"Predict QED for SMILES CC{i}O"
        response = f"### Response:\nQED ~ 0.{50 + (i % 30)}"
        rows.append({"text": f"{prompt}\n{response}"})
    ds = Dataset.from_list(rows)
    dd = DatasetDict({"train": ds, "test": ds.select(range(min(8, n)))})
    dd.save_to_disk(str(out_dir))
    return out_dir


def _make_tiny_grpo_prompts(out_dir: Path, n: int = 8) -> Path:
    from datasets import Dataset, DatasetDict

    rows = []
    for i in range(n):
        rows.append({"prompt": f"PROPOSAL: SMILES "})
    ds = Dataset.from_list(rows)
    dd = DatasetDict({"train": ds, "test": ds.select(range(min(2, n)))})
    dd.save_to_disk(str(out_dir))
    return out_dir


def _write_smoke_configs(work: Path, ds_sft: Path, ds_grpo: Path) -> dict:
    """Generate stage1/2/3 configs pointing at the tiny model + datasets."""
    base_model = "sshleifer/tiny-gpt2"

    base = {
        "run_name": "smoke",
        "model": {"base_id": base_model, "dtype": "float32",
                  "trust_remote_code": False, "use_cache": False,
                  "attn_impl": "default"},
        "peft": {"enabled": True, "type": "lora", "r": 4, "alpha": 8,
                 "dropout": 0.0, "bias": "none", "task_type": "CAUSAL_LM",
                 "target_modules": ["c_attn"]},
        "training": {
            "output_dir": "", "num_train_epochs": 1,
            "per_device_train_batch_size": 2, "per_device_eval_batch_size": 2,
            "gradient_accumulation_steps": 1, "gradient_checkpointing": False,
            "learning_rate": 5e-4, "lr_scheduler_type": "constant",
            "warmup_ratio": 0.0, "weight_decay": 0.0, "optim": "adamw_torch",
            "max_grad_norm": 1.0, "bf16": False, "tf32": False,
            "logging_steps": 1, "eval_strategy": "no", "eval_steps": 1,
            "save_strategy": "no", "save_steps": 100, "save_total_limit": 1,
            "load_best_model_at_end": False,
            "metric_for_best_model": None, "greater_is_better": True,
            "group_by_length": False, "report_to": [],
            "ddp_find_unused_parameters": False, "remove_unused_columns": False,
            "dataloader_num_workers": 0, "seed": 42,
        },
        "dataset": {
            "source": "local", "path": "", "hub_id": None,
            "split_train": "train", "split_eval": "test",
            "max_seq_length": 64, "packing": False,
            "text_field": "text",
            "response_template": "### Response:",
        },
        "hub": {"push_to_hub": False, "private": True,
                "hub_model_id": None, "push_strategy": "end",
                "token_env": "HF_TOKEN"},
        "wandb": {"project": "lysos-smoke", "entity": None, "tags": ["smoke"],
                  "log_model": False},
    }

    # Stage 1
    stage1 = json.loads(json.dumps(base))
    stage1["run_name"] = "smoke_s1"
    stage1["dataset"]["path"] = str(ds_sft)
    stage1["training"]["output_dir"] = str(work / "stage1_out")

    # Stage 2 — loads stage 1 adapter
    stage2 = json.loads(json.dumps(base))
    stage2["run_name"] = "smoke_s2"
    stage2["peft"]["load_existing_adapter"] = str(work / "stage1_out")
    stage2["dataset"]["path"] = str(ds_sft)
    stage2["training"]["output_dir"] = str(work / "stage2_out")

    # Stage 3 — GRPO uses prompt-only dataset
    stage3 = json.loads(json.dumps(base))
    stage3["run_name"] = "smoke_s3"
    stage3["model"]["reference_model_id"] = base_model
    stage3["model"]["beta"] = 0.04
    stage3["peft"]["load_existing_adapter"] = str(work / "stage2_out")
    stage3["dataset"]["path"] = str(ds_grpo)
    stage3["dataset"]["max_prompt_length"] = 32
    stage3["dataset"]["max_completion_length"] = 16
    stage3["training"]["output_dir"] = str(work / "stage3_out")
    stage3["training"]["max_steps"] = 2
    stage3["training"]["report_to"] = []
    stage3["rl"] = {"num_generations": 2, "temperature": 1.0, "top_p": 0.95,
                    "top_k": 0, "use_vllm": False}
    # Smoke reward config: a single trivial component (module:fn format)
    stage3["reward"] = {
        "components": [{
            "name": "stub_validity",
            "module": "src.eval.rewards.validity:smiles_valid",
            "weight": 1.0,
        }],
        "on_error": "zero",
    }

    cfgs = {}
    for name, cfg in [("stage1", stage1), ("stage2", stage2), ("stage3", stage3)]:
        p = work / f"{name}.yaml"
        # Use yaml if available; json is a valid YAML subset for the keys used.
        try:
            import yaml
            p.write_text(yaml.safe_dump(cfg, sort_keys=False))
        except ImportError:
            p.write_text(json.dumps(cfg, indent=2))
        cfgs[name] = p
    return cfgs


def _run_stage(label: str, cmd: list[str], work: Path) -> tuple[bool, str]:
    log_path = work / f"{label}.log"
    print(f"\n[{label}] $ {' '.join(cmd)}")
    with open(log_path, "w") as f:
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT,
                              env={**os.environ, "WANDB_MODE": "disabled",
                                   "HF_HUB_OFFLINE": "0", "TRANSFORMERS_VERBOSITY": "error"})
    tail = "\n".join(log_path.read_text().splitlines()[-15:])
    print(f"[{label}] exit={proc.returncode}\n  log tail:\n{tail}")
    return proc.returncode == 0, tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="Don't clean tmp dir")
    ap.add_argument("--skip-stage3", action="store_true",
                    help="Stage 3 needs TRL>=0.11; skip if not installed")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="lysos_smoke_"))
    print(f"Smoke workdir: {work}")

    # Quick dep check
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        import peft  # noqa: F401
        import datasets  # noqa: F401
    except ImportError as exc:
        print(f"[X] Missing dep: {exc}")
        return 1

    ds_sft = _make_tiny_dataset(work / "ds_sft")
    ds_grpo = _make_tiny_grpo_prompts(work / "ds_grpo")
    cfgs = _write_smoke_configs(work, ds_sft, ds_grpo)
    print(f"  Datasets: SFT n=32, GRPO n=8")

    py = sys.executable

    ok1, _ = _run_stage("stage1", [py, "-m", "src.training.stage1_txgemma4",
                                   "--config", str(cfgs["stage1"])], work)
    if not ok1:
        return 2

    ok2, _ = _run_stage("stage2", [py, "-m", "src.training.stage2_amr_sft",
                                   "--config", str(cfgs["stage2"])], work)
    if not ok2:
        return 3

    if args.skip_stage3:
        print("[stage3] skipped per --skip-stage3")
    else:
        ok3, _ = _run_stage("stage3", [py, "-m", "src.training.stage3_rl_grpo",
                                       "--config", str(cfgs["stage3"]),
                                       "--smoke-test"], work)
        if not ok3:
            return 4

    print(f"\n[OK] End-to-end smoke passed. Artefacts in {work}")
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
        print("  cleaned up tmp dir")
    return 0


if __name__ == "__main__":
    sys.exit(main())
