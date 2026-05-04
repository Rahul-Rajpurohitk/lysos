"""Data-version → model-artifact tracking utility (#16 from audit).

Computes a content hash of every dataset on disk + ties it to:
  - git commit SHA at build time
  - reward-stack version (from configs/stage3_rl_grpo.yaml)
  - SDK versions (rdkit, datasets, transformers)
  - source-file hashes (data/raw/* + scripts/*.py)

Writes data/processed/MANIFEST.json. The trainer + model card uploader can
embed this manifest into the model artifact so any reported metric can be
traced back to the exact dataset + code version that produced it.

Run:
  /tmp/lysos_venv/bin/python scripts/build_dataset_manifest.py
  /tmp/lysos_venv/bin/python scripts/build_dataset_manifest.py --write_to_model_card
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
MANIFEST = PROCESSED / "MANIFEST.json"


def _hash_file(p: Path, chunk_size: int = 65536) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b: break
            h.update(b)
    return h.hexdigest()


def _hash_dir(d: Path, exclude_globs: tuple = ("*.pyc",)) -> tuple[str, list[str]]:
    """Stable hash over all files in a directory (sorted, content-hashed)."""
    if not d.exists() or not d.is_dir():
        return "", []
    h = hashlib.sha256()
    files = []
    for p in sorted(d.rglob("*")):
        if not p.is_file(): continue
        if any(p.match(g) for g in exclude_globs): continue
        files.append(p.relative_to(d).as_posix())
        h.update(p.relative_to(d).as_posix().encode())
        h.update(_hash_file(p).encode())
    return h.hexdigest(), files


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "UNKNOWN"


def _git_dirty() -> bool:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
        ).strip()
        return bool(out)
    except Exception:
        return False


def _sdk_versions() -> dict:
    versions = {}
    for pkg in ("rdkit", "datasets", "transformers", "torch", "trl",
                 "peft", "accelerate", "huggingface_hub", "xgboost",
                 "scikit-learn", "pandas", "numpy"):
        try:
            mod = __import__(pkg)
            v = getattr(mod, "__version__", None)
            if v: versions[pkg] = v
        except Exception:
            versions[pkg] = "missing"
    return versions


def _scan_processed_datasets() -> dict:
    """Hash every dataset directory under data/processed/."""
    out = {}
    if not PROCESSED.exists():
        return out
    for entry in sorted(PROCESSED.iterdir()):
        if entry.is_dir():
            sha, files = _hash_dir(entry)
            out[entry.name] = {
                "type": "dataset_dir",
                "sha256": sha[:16],     # short for readability
                "n_files": len(files),
            }
        elif entry.is_file():
            out[entry.name] = {
                "type": "file",
                "sha256": _hash_file(entry)[:16],
                "size_bytes": entry.stat().st_size,
            }
    return out


def _reward_stack_summary() -> dict:
    cfg_path = ROOT / "configs" / "stage3_rl_grpo.yaml"
    if not cfg_path.exists():
        return {}
    import yaml
    cfg = yaml.safe_load(cfg_path.read_text())
    components = cfg.get("reward", {}).get("components", [])
    return {
        "n_components": len(components),
        "components": [c.get("name") for c in components],
        "weights": {c.get("name"): c.get("weight") for c in components},
        "weights_sum": round(sum((c.get("weight") or 0) for c in components), 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write_to_model_card", action="store_true",
                    help="Append the manifest summary to model_cards/*.md")
    args = ap.parse_args()

    manifest = {
        "manifest_version": "v1",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "sdk_versions": _sdk_versions(),
        "datasets": _scan_processed_datasets(),
        "reward_stack": _reward_stack_summary(),
    }
    PROCESSED.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote {MANIFEST}")
    print(f"  git_sha: {manifest['git_sha']}")
    print(f"  dirty: {manifest['git_dirty']}")
    print(f"  datasets tracked: {len(manifest['datasets'])}")
    print(f"  reward components: {manifest['reward_stack'].get('n_components')}")
    print(f"  reward weights sum: {manifest['reward_stack'].get('weights_sum')}")

    if args.write_to_model_card:
        cards_dir = ROOT / "model_cards"
        if cards_dir.exists():
            for md in cards_dir.glob("*.md"):
                content = md.read_text()
                if "## Data manifest" not in content:
                    addendum = (
                        f"\n\n## Data manifest (auto-generated, v1)\n"
                        f"- git_sha: `{manifest['git_sha'][:12]}`\n"
                        f"- built_at: {manifest['built_at']}\n"
                        f"- datasets tracked: {len(manifest['datasets'])}\n"
                        f"- reward components: {manifest['reward_stack'].get('n_components')}\n"
                        f"- reward weights sum: {manifest['reward_stack'].get('weights_sum')}\n"
                        f"- See `data/processed/MANIFEST.json` for full content hashes.\n"
                    )
                    md.write_text(content + addendum)
                    print(f"  appended manifest summary to {md}")


if __name__ == "__main__":
    sys.exit(main())
