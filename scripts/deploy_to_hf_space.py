"""Deploy the Lysos workspace to its HF Space.

The Dockerfile in `workspace/` references files at the repo root
(`pyproject.toml`, `src/`) so it builds with the *repo root* as docker
context. HF Spaces only ship what's in the Space repo, so this script
assembles a minimal self-contained tree at `.deploy/` and pushes it to
the Space's git remote.

Usage:
    python scripts/deploy_to_hf_space.py

Env vars:
    HF_TOKEN       — HF write token
    HF_SPACE_REPO  — defaults to https://huggingface.co/spaces/lablab-ai-amd-developer-hackathon/lysos
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = REPO_ROOT / ".deploy"
HF_SPACE_REPO = os.environ.get(
    "HF_SPACE_REPO",
    "https://huggingface.co/spaces/lablab-ai-amd-developer-hackathon/lysos",
)


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    if not (REPO_ROOT / "workspace" / "Dockerfile").exists():
        print("workspace/Dockerfile not found", file=sys.stderr)
        return 1

    if DEPLOY_DIR.exists():
        shutil.rmtree(DEPLOY_DIR)
    DEPLOY_DIR.mkdir(parents=True)

    print("[1/5] copy workspace/ → .deploy/ ...")
    shutil.copytree(REPO_ROOT / "workspace", DEPLOY_DIR, dirs_exist_ok=True)

    print("[2/5] copy pyproject.toml + src/ + thumbnail ...")
    shutil.copy2(REPO_ROOT / "pyproject.toml", DEPLOY_DIR / "pyproject.toml")
    shutil.copytree(REPO_ROOT / "src", DEPLOY_DIR / "src")
    thumb = REPO_ROOT / "docs" / "assets" / "thumbnail-square.png"
    if thumb.exists():
        shutil.copy2(thumb, DEPLOY_DIR / "thumbnail.png")

    print("[3/5] write README.md (HF Space card) ...")
    (DEPLOY_DIR / "README.md").write_text(
        """---
title: Lysos
emoji: 🧪
colorFrom: green
colorTo: indigo
sdk: docker
app_port: 7860
pinned: true
license: apache-2.0
short_description: Generative drug designer for antimicrobial resistance
thumbnail: thumbnail.png
---

# Lysos — generative drug designer for AMR

Built on Gemma 4 31B + EmbeddingGemma 300m, RL-tuned on AMD Instinct MI300X.

[Repo](https://github.com/Rahul-Rajpurohitk/lysos) ·
[Stage 2 dataset](https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2) ·
[Stage 3 RL prompts](https://huggingface.co/datasets/rahul24raj/lysos-rl-prompts)
""",
        encoding="utf-8",
    )

    print("[4/5] init git, commit ...")
    run(["git", "init", "--initial-branch=main"], cwd=DEPLOY_DIR)
    run(
        ["git", "config", "user.email", "rahulrajpurohitk@gmail.com"],
        cwd=DEPLOY_DIR,
    )
    run(
        ["git", "config", "user.name", "Rahul Rajpurohit"],
        cwd=DEPLOY_DIR,
    )
    run(["git", "add", "-A"], cwd=DEPLOY_DIR)
    run(
        ["git", "commit", "-m", "deploy: lysos workspace"],
        cwd=DEPLOY_DIR,
    )

    print(f"[5/5] push to HF Space at {HF_SPACE_REPO} ...")
    token = os.environ.get("HF_TOKEN")
    if not token:
        print(
            "  HF_TOKEN not set; aborting before push.\n"
            f"  set HF_TOKEN and re-run, or push manually:\n"
            f"    cd {DEPLOY_DIR}\n"
            f"    git remote add space {HF_SPACE_REPO}\n"
            f"    git push --force space main",
            file=sys.stderr,
        )
        return 2
    auth_url = HF_SPACE_REPO.replace(
        "https://", f"https://rahul24raj:{token}@"
    )
    run(["git", "remote", "add", "space", auth_url], cwd=DEPLOY_DIR)
    run(["git", "push", "--force", "space", "main"], cwd=DEPLOY_DIR)
    print("\n✓ deployed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
