"""Smoke test for the AMD MI300X training environment.

Run this as the FIRST thing on a freshly-spun-up AMD Dev Cloud VM.
It verifies the entire training stack works before we burn $$$ on a
real fine-tune that fails halfway through.

Usage on the VM:

    python scripts/smoke_test_rocm.py

Exits with code 0 on success, non-zero on first failure.
Total runtime should be < 5 minutes on a single MI300X.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PASS = "\033[32m[PASS]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"
INFO = "\033[36m[INFO]\033[0m"


def info(msg: str) -> None:
    print(f"{INFO} {msg}", flush=True)


def passed(msg: str) -> None:
    print(f"{PASS} {msg}", flush=True)


def failed(msg: str, err: Exception | str | None = None) -> None:
    print(f"{FAIL} {msg}", flush=True)
    if err is not None:
        print(f"        {err}", flush=True)


def header(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}", flush=True)


def run(cmd: str, *, timeout: int = 60) -> tuple[int, str]:
    """Run a shell command, return (returncode, combined_output)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired as exc:
        return 124, f"timeout after {timeout}s: {exc}"


def check_rocm_smi() -> bool:
    """Verify rocm-smi is available and reports at least one GPU."""
    rc, out = run("rocm-smi --showproductname --csv")
    if rc != 0:
        failed("rocm-smi did not run", out)
        return False
    if "MI300" not in out:
        failed("rocm-smi did not report any MI300-class GPU", out)
        return False
    passed("rocm-smi reports at least one MI300-class GPU")
    print(f"        {out.splitlines()[0] if out else ''}")
    return True


def check_torch_rocm() -> bool:
    """Verify torch is built against ROCm and CUDA-via-HIP works."""
    try:
        import torch
    except ImportError as exc:
        failed("torch not importable", exc)
        return False
    info(f"torch version: {torch.__version__}")
    info(f"torch.version.hip: {getattr(torch.version, 'hip', None)}")
    info(f"torch.cuda.is_available() (via HIP): {torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        failed("torch.cuda.is_available() is False — ROCm/HIP is not wired up")
        return False
    info(f"torch.cuda.device_count(): {torch.cuda.device_count()}")
    for i in range(torch.cuda.device_count()):
        info(f"  device {i}: {torch.cuda.get_device_name(i)}")
    passed("torch + ROCm/HIP working")
    return True


def check_torch_compute() -> bool:
    """Run a tiny matmul on the GPU and verify the result."""
    try:
        import torch

        a = torch.randn(2048, 2048, device="cuda", dtype=torch.bfloat16)
        b = torch.randn(2048, 2048, device="cuda", dtype=torch.bfloat16)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        c = a @ b
        torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        # Sanity: result has the right shape, no NaN
        assert c.shape == (2048, 2048), f"unexpected shape {c.shape}"
        assert not torch.isnan(c).any(), "result contains NaN"
    except Exception as exc:  # noqa: BLE001
        failed("BF16 matmul on GPU failed", exc)
        return False
    passed(f"BF16 2048×2048 matmul on GPU completed in {dt * 1000:.2f} ms")
    return True


def check_transformers() -> bool:
    """Verify transformers + tokenizers import cleanly."""
    try:
        import transformers

        info(f"transformers version: {transformers.__version__}")
    except ImportError as exc:
        failed("transformers not importable", exc)
        return False
    passed("transformers imports cleanly")
    return True


def check_peft_trl() -> bool:
    """Verify PEFT and TRL import (LoRA + RL pipeline)."""
    ok = True
    for name in ("peft", "trl", "accelerate", "datasets"):
        try:
            mod = __import__(name)
            info(f"{name} version: {getattr(mod, '__version__', 'unknown')}")
        except ImportError as exc:
            failed(f"{name} not importable", exc)
            ok = False
    if ok:
        passed("PEFT + TRL + accelerate + datasets all importable")
    return ok


def check_rdkit() -> bool:
    """Verify rdkit (chemistry library) can parse a SMILES."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors

        # Penicillin G SMILES
        m = Chem.MolFromSmiles("CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O")
        if m is None:
            failed("rdkit failed to parse penicillin G SMILES")
            return False
        mw = Descriptors.MolWt(m)
        info(f"penicillin G molecular weight (via rdkit): {mw:.2f}")
    except Exception as exc:  # noqa: BLE001
        failed("rdkit smoke test failed", exc)
        return False
    passed("rdkit parses + computes descriptors")
    return True


def check_pytdc() -> bool:
    """Verify PyTDC (Therapeutics Data Commons) is importable."""
    try:
        import tdc

        info(f"PyTDC version: {tdc.__version__}")
    except ImportError as exc:
        failed("PyTDC not importable", exc)
        return False
    passed("PyTDC importable")
    return True


def check_hf_token() -> bool:
    """Verify HF_TOKEN is set so we can pull gated Gemma 4."""
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        failed("HF_TOKEN not set — needed to pull gated Gemma 4 weights")
        return False
    if not token.startswith("hf_"):
        failed("HF_TOKEN does not look like a real HF token")
        return False
    passed("HF_TOKEN is set")
    return True


def check_gemma_4_loadable() -> bool:
    """Try loading Gemma 4 tokenizer (small, fast download).

    Loading the full model is too expensive for a smoke test —
    we just verify auth + tokenizer for now.
    """
    try:
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained("google/gemma-4-31B-it")
        sample = tok("Lysos generates novel antibiotics.", return_tensors="pt")
        info(f"sample input_ids shape: {tuple(sample['input_ids'].shape)}")
    except Exception as exc:  # noqa: BLE001
        failed("Gemma 4 tokenizer load failed (auth issue?)", exc)
        return False
    passed("Gemma 4 tokenizer loaded")
    return True


def check_optimum_amd() -> bool:
    """Verify optimum-amd is importable for Flash Attention 2 on ROCm."""
    try:
        import optimum  # noqa: F401

        info("optimum imports cleanly")
    except ImportError as exc:
        failed("optimum not importable (Flash Attention 2 will be slow)", exc)
        return False
    passed("optimum importable — Flash Attention 2 path available")
    return True


def main() -> int:
    header("Lysos AMD MI300X smoke test")

    info(f"Python: {sys.version.split()[0]}")
    info(f"CWD: {Path.cwd()}")
    info(f"ROCM_PATH: {os.environ.get('ROCM_PATH', 'not set')}")

    checks = [
        ("ROCm SMI", check_rocm_smi),
        ("Torch + ROCm/HIP", check_torch_rocm),
        ("Torch GPU compute", check_torch_compute),
        ("Transformers", check_transformers),
        ("PEFT + TRL + accelerate + datasets", check_peft_trl),
        ("RDKit", check_rdkit),
        ("PyTDC", check_pytdc),
        ("HF token", check_hf_token),
        ("Optimum-AMD", check_optimum_amd),
        ("Gemma 4 tokenizer load", check_gemma_4_loadable),
    ]

    results: list[tuple[str, bool]] = []
    for name, fn in checks:
        header(name)
        try:
            results.append((name, fn()))
        except Exception as exc:  # noqa: BLE001
            failed(f"{name} raised", exc)
            results.append((name, False))

    header("Summary")
    n_pass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        marker = PASS if ok else FAIL
        print(f"  {marker} {name}")
    print(f"\n{n_pass} / {len(results)} checks passed")

    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
