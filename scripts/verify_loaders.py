"""Smoke-verify every loader module is importable + has the expected entrypoint.

Doesn't make network calls — just confirms the modules compile cleanly + each
exposes its documented public callable. Run this in CI / after every loader
edit to catch broken imports before kicking off the long fetch run.

Usage:

    python scripts/verify_loaders.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure src is importable
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("verify")

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"

# (module path, expected callable name)
LOADERS = [
    ("src.data.chembl", "fetch_amr_activities"),
    ("src.data.dbaasp", "fetch_amps"),
    ("src.data.dramp", "fetch_amps"),
    ("src.data.card", "fetch_resistance"),
    ("src.data.bindingdb", "fetch_bindingdb"),
    ("src.data.pubchem", "fetch_pubchem_antibacterial"),
    ("src.data.zinc", "fetch_zinc_subsets"),
    ("src.data.apd3", "fetch_apd3_amps"),
    ("src.data.drugbank", "fetch_drugbank_open"),
    ("src.data.pdb", "fetch_pdb_targets"),
]

# Reward modules
REWARDS = [
    ("src.eval.rewards.validity", "smiles_valid"),
    ("src.eval.rewards.drug_likeness", "qed_score"),
    ("src.eval.rewards.synth", "sa_score"),
    ("src.eval.rewards.novelty", "tanimoto_distance_to_known"),
    ("src.eval.rewards.embedding_novelty", "embedding_novelty"),
    ("src.eval.rewards.safety", "hemolysis_inverse"),
    ("src.eval.rewards.activity", "predict_mic"),
]

# Training scripts
TRAINING = [
    ("src.training.sft_runner", "run_sft"),
    ("src.training.stage1_txgemma4", "main"),
    ("src.training.stage2_amr_sft", "main"),
    ("src.training.stage3_rl_grpo", "main"),
]

# Inference
INFERENCE = [
    ("src.inference.generate", "LysosGenerator"),
]

# Config loader
CONFIG = [
    ("src.config", "load_config"),
    ("src.config", "apply_cli_overrides"),
]


def verify(group_name: str, items: list[tuple[str, str]]) -> tuple[int, int]:
    print(f"\n=== {group_name} ===")
    n_pass = 0
    for mod_path, attr in items:
        try:
            mod = __import__(mod_path, fromlist=[attr])
            obj = getattr(mod, attr, None)
            if obj is None:
                print(f"  {FAIL} {mod_path}.{attr}  — attribute missing")
                continue
            if not callable(obj) and not isinstance(obj, type):
                print(f"  {FAIL} {mod_path}.{attr}  — not callable")
                continue
            print(f"  {PASS} {mod_path}.{attr}")
            n_pass += 1
        except Exception as exc:
            print(f"  {FAIL} {mod_path}.{attr}  — {type(exc).__name__}: {exc}")
    return n_pass, len(items)


def main() -> int:
    total_pass = 0
    total = 0
    for name, items in [
        ("Config", CONFIG),
        ("Data loaders", LOADERS),
        ("Reward functions", REWARDS),
        ("Training", TRAINING),
        ("Inference", INFERENCE),
    ]:
        n, t = verify(name, items)
        total_pass += n
        total += t

    print(f"\n{'-' * 50}")
    print(f"  {total_pass} / {total} passed")
    return 0 if total_pass == total else 1


if __name__ == "__main__":
    sys.exit(main())
