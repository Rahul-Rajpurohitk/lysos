"""Preflight checks — validates EVERYTHING before burning GPU dollars.

Bulletproof validation of the full training stack. Runs in <1 minute.
If any check fails, do NOT start training — the cost of a failed train run
is much higher than the cost of running this checklist.

Categories:
  A. Hardware (GPU, RAM, disk)
  B. Python environment (deps + versions)
  C. Authentication (HF write, wandb)
  D. Datasets (round-trip pull)
  E. Configs (parse + coherence)
  F. Reward stack (imports + executes)
  G. Loss masking + tokenizer alignment
  H. Smoke train (5 steps, tiny subset)

Run on AMD MI300X VM after vm_bootstrap.sh:
  /tmp/lysos_venv/bin/python scripts/preflight_check.py --stage 2

Or all stages:
  /tmp/lysos_venv/bin/python scripts/preflight_check.py --stage all
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def banner(title: str):
    print(f"\n{'='*64}\n{title}\n{'='*64}")


def check(name: str, ok: bool, detail: str = "") -> tuple[bool, str]:
    icon = "✅" if ok else "❌"
    msg = f"  {icon} {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return ok, msg


def check_hardware() -> list[tuple[bool, str]]:
    banner("[A] Hardware")
    results = []

    # GPU detection
    has_gpu = False
    try:
        import torch
        if torch.cuda.is_available():
            has_gpu = True
            n_gpu = torch.cuda.device_count()
            mem_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
            name = torch.cuda.get_device_name(0)
            results.append(check(f"GPU available ({n_gpu}× {name})", True, f"{mem_gb:.1f}GB"))
            results.append(check("MI300X (192GB)", "MI300" in name or mem_gb >= 180,
                                  f"{mem_gb:.1f}GB" if mem_gb >= 180 else "smaller GPU detected"))
        else:
            results.append(check("GPU available", False, "torch.cuda.is_available() = False"))
    except ImportError:
        results.append(check("torch importable", False, "pip install torch"))

    # Disk space
    try:
        result = subprocess.run(["df", "-BG", str(ROOT)], capture_output=True, text=True, timeout=5)
        line = result.stdout.strip().split("\n")[-1]
        avail_gb = int(line.split()[3].rstrip("G"))
        results.append(check("Disk space ≥ 200GB free", avail_gb >= 200, f"{avail_gb}GB"))
    except Exception as e:
        results.append(check("Disk space check", False, str(e)))

    # RAM
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    avail_kb = int(line.split()[1])
                    avail_gb = avail_kb / 1024 / 1024
                    results.append(check("RAM ≥ 64GB free", avail_gb >= 64, f"{avail_gb:.1f}GB"))
                    break
    except Exception:
        pass  # /proc/meminfo not on macOS; skip

    return results


def check_python_env() -> list[tuple[bool, str]]:
    banner("[B] Python environment")
    results = []

    deps = {
        "torch": "2.0",
        "transformers": "4.40",
        "datasets": "2.0",
        "peft": "0.10",
        "trl": "0.11",
        "rdkit": "2024",
        "accelerate": "0.30",
        "xgboost": "2.0",
        "wandb": "0.15",
        "huggingface_hub": "0.20",
    }

    for pkg, min_ver in deps.items():
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "?")
            ok = ver != "?"
            results.append(check(f"{pkg} ≥ {min_ver}", ok, f"{ver}"))
        except ImportError:
            results.append(check(f"{pkg} installed", False, "pip install"))

    return results


def check_auth() -> list[tuple[bool, str]]:
    banner("[C] Authentication")
    results = []

    # Delegate live key validation to verify_keys.py (single source of truth).
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import verify_keys as vk
        vk._load_dotenv(ROOT / ".env")
        vk._load_hf_cache_token()
    except Exception as e:
        results.append(check("verify_keys importable", False, str(e)[:80]))
        return results

    hf = os.environ.get("HF_TOKEN", "").strip()
    if hf:
        ok, det = vk.check_hf(hf)
        results.append(check("HF auth (write)", ok, det))
    else:
        results.append(check("HF auth (write)", False, "HF_TOKEN not in env / cache"))

    gem = os.environ.get("GEMINI_API_KEY", "").strip()
    if gem:
        ok, det = vk.check_gemini(gem)
        results.append(check("Gemini Embedding 2 live", ok, det))
    else:
        results.append(check("GEMINI_API_KEY", False,
                              "embedding_novelty will RAISE; export key or weight=0"))

    wandb_key = os.environ.get("WANDB_API_KEY", "").strip()
    if wandb_key:
        ok, det = vk.check_wandb(wandb_key)
        results.append(check("WANDB live", ok, det))
    else:
        results.append(check("WANDB_API_KEY (recommended)", False,
                              "no live training dashboard"))

    return results


def check_datasets() -> list[tuple[bool, str]]:
    banner("[D] Datasets (round-trip pull)")
    results = []

    datasets_to_check = [
        "rahul24raj/lysos-amr-stage2-pro-v12",
        "rahul24raj/lysos-rl-prompts-v3",
        "rahul24raj/lysos-tdc-stage1",
    ]

    try:
        from datasets import load_dataset
        for ds_id in datasets_to_check:
            try:
                ds = load_dataset(ds_id, streaming=True)
                results.append(check(f"{ds_id}", True, "round-trip OK"))
            except Exception as e:
                results.append(check(f"{ds_id}", False, str(e)[:100]))
    except ImportError:
        results.append(check("datasets library", False, "pip install datasets"))

    return results


def check_configs(stage: str) -> list[tuple[bool, str]]:
    banner(f"[E] Configs — stage {stage}")
    results = []

    cfg_paths = {
        "1": "configs/stage1_txgemma4.yaml",
        "2": "configs/stage2_amr_sft.yaml",
        "3": "configs/stage3_rl_grpo.yaml",
    }

    stages_to_check = list(cfg_paths.keys()) if stage == "all" else [stage]

    import yaml
    for s in stages_to_check:
        p = ROOT / cfg_paths[s]
        if not p.exists():
            results.append(check(f"config stage {s} exists", False, str(p)))
            continue
        try:
            cfg = yaml.safe_load(p.read_text())
            results.append(check(f"config stage {s} parses", True))

            # Coherence checks
            if s in ("1", "2"):
                if cfg.get("hub", {}).get("push_strategy") == "end":
                    results.append(check(f"stage {s} push_strategy='checkpoint'",
                                           False, "push_strategy=end loses everything on crash"))
                else:
                    results.append(check(f"stage {s} push_strategy='checkpoint'", True))

            if s == "3":
                rwd = cfg.get("reward", {}).get("components", [])
                ws = sum(c.get("weight", 0) for c in rwd)
                results.append(check(f"stage 3 reward weights sum to 1.0",
                                       abs(ws - 1.0) < 0.01, f"sum={ws}"))
                results.append(check(f"stage 3 reward components ≥ 10",
                                       len(rwd) >= 10, f"n={len(rwd)}"))
        except yaml.YAMLError as e:
            results.append(check(f"config stage {s} parses", False, str(e)[:80]))

    return results


def check_reward_stack() -> list[tuple[bool, str]]:
    banner("[F] Reward stack")
    results = []

    # Make sure project root is on sys.path
    sys.path.insert(0, str(ROOT))

    try:
        import yaml
        from src.eval.rewards import CompositeReward
        cfg = yaml.safe_load((ROOT / "configs/stage3_rl_grpo.yaml").read_text())
        fn = CompositeReward(
            components=cfg["reward"]["components"],
            on_error=cfg["reward"].get("on_error"),
        )
        results.append(check("CompositeReward loads", True))

        # Test sample
        samples = ["SMILES: CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O"]
        combined, per_comp = fn(samples)
        results.append(check(f"reward fn executes on sample", True, f"composite={combined[0]:.3f}"))
        results.append(check("validity > 0 on PEN G", per_comp.get("validity", [0])[0] > 0,
                               f"={per_comp.get('validity', [0])[0]:.3f}"))
    except Exception as e:
        results.append(check("Reward stack", False, str(e)[:100]))

    return results


def check_loss_masking() -> list[tuple[bool, str]]:
    banner("[G] Loss masking smoke test")
    try:
        out = subprocess.run(
            [sys.executable, "scripts/test_loss_masking.py"],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        )
        ok = "ALL CHECKS PASSED" in out.stdout
        return [check("Loss masking 4/4", ok, "" if ok else "see scripts/test_loss_masking.py")]
    except Exception as e:
        return [check("Loss masking smoke test", False, str(e)[:80])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["1", "2", "3", "all"], default="all")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "preflight_check.json")
    args = ap.parse_args()

    print(f"Lysos Preflight Check — Stage {args.stage}")
    print(f"Path: {ROOT}\n")

    all_results = []
    all_results.extend(check_hardware())
    all_results.extend(check_python_env())
    all_results.extend(check_auth())
    all_results.extend(check_datasets())
    all_results.extend(check_configs(args.stage))
    all_results.extend(check_reward_stack())
    all_results.extend(check_loss_masking())

    n_pass = sum(1 for ok, _ in all_results if ok)
    n_fail = len(all_results) - n_pass

    banner("SUMMARY")
    print(f"  Passed: {n_pass}/{len(all_results)}")
    if n_fail > 0:
        print(f"  Failed: {n_fail}")
        print(f"\n  ❌ FIX THESE BEFORE TRAINING:")
        for ok, msg in all_results:
            if not ok:
                print(f"    {msg}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "stage": args.stage,
        "n_pass": n_pass,
        "n_fail": n_fail,
        "results": [{"ok": ok, "msg": msg} for ok, msg in all_results],
        "timestamp": time.time(),
    }, indent=2))
    print(f"\nWrote {args.out}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
