"""setup_wandb_dashboard.py — programmatic wandb workspace for Lysos training.

Creates a reproducible dashboard in the `lysos` project with:
  * Training core (loss, lr, grad_norm)
  * GRPO-specific (KL, advantage, policy loss, reward) — Stage 3
  * Reward decomposition (12 components) — Stage 3
  * Eval callback metrics (mid-training composite reward, n_valid)
  * Hardware (GPU util, GPU mem)
  * Cost protection (alert when $250 spend projected)

Run AFTER `wandb login` so this user is the dashboard owner:
    python scripts/setup_wandb_dashboard.py

Idempotent — re-running updates the workspace in place.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


REWARD_COMPONENTS = [
    "validity", "structural_alerts", "predicted_mic", "drug_likeness_qed",
    "synthesizability", "hemolysis_safety", "novelty", "embedding_novelty",
    "boltz2_pose_conf", "spectrum_breadth", "resistance_robustness", "pareto_entry",
]


def build_workspace(project: str = "lysos", entity: str | None = None):
    try:
        import wandb_workspaces.workspaces as ws
        import wandb_workspaces.reports.v2 as wr
    except ImportError:
        print("[!] wandb-workspaces not installed.")
        print("    pip install wandb-workspaces")
        return None

    sections = []

    # 1. Training core
    sections.append(ws.Section(
        name="Training core",
        panels=[
            wr.LinePlot(title="train/loss", x="train/global_step", y=["train/loss"]),
            wr.LinePlot(title="train/learning_rate", x="train/global_step",
                        y=["train/learning_rate"]),
            wr.LinePlot(title="train/grad_norm", x="train/global_step",
                        y=["train/grad_norm"]),
            wr.LinePlot(title="eval/loss", x="eval/global_step", y=["eval/loss"]),
        ],
    ))

    # 2. GRPO-specific
    sections.append(ws.Section(
        name="GRPO (Stage 3)",
        panels=[
            wr.LinePlot(title="train/reward (composite)",
                        x="train/global_step", y=["train/reward"]),
            wr.LinePlot(title="train/kl", x="train/global_step", y=["train/kl"]),
            wr.LinePlot(title="train/policy_loss", x="train/global_step",
                        y=["train/policy_loss"]),
            wr.LinePlot(title="train/advantage_mean", x="train/global_step",
                        y=["train/advantage_mean"]),
        ],
    ))

    # 3. Reward decomposition (one big plot with all 12 components)
    sections.append(ws.Section(
        name="Reward decomposition",
        panels=[
            wr.LinePlot(
                title="reward components (mean per step)",
                x="train/global_step",
                y=[f"reward/{c}" for c in REWARD_COMPONENTS],
            ),
            wr.BarPlot(
                title="reward weights × current value",
                metrics=[f"reward/{c}_weighted" for c in REWARD_COMPONENTS],
            ),
        ],
    ))

    # 4. Eval callback
    sections.append(ws.Section(
        name="Mid-training eval",
        panels=[
            wr.LinePlot(title="eval/avg_composite", x="eval/global_step",
                        y=["eval/avg_composite"]),
            wr.LinePlot(title="eval/n_valid (out of 50)",
                        x="eval/global_step", y=["eval/n_valid"]),
            wr.LinePlot(title="eval/avg_qed", x="eval/global_step",
                        y=["eval/avg_qed"]),
            wr.LinePlot(title="eval/avg_novelty", x="eval/global_step",
                        y=["eval/avg_novelty"]),
        ],
    ))

    # 5. Hardware
    sections.append(ws.Section(
        name="Hardware (MI300X)",
        panels=[
            wr.LinePlot(title="GPU utilization %", x="_step",
                        y=["system/gpu.0.gpu", "system/gpu.0.memory"]),
            wr.LinePlot(title="GPU memory (GB)", x="_step",
                        y=["system/gpu.0.memoryAllocated"]),
            wr.LinePlot(title="System RAM (GB)", x="_step",
                        y=["system/memory"]),
            wr.LinePlot(title="Disk used (GB)", x="_step", y=["system/disk"]),
        ],
    ))

    # 6. Cost protection
    sections.append(ws.Section(
        name="Cost protection",
        panels=[
            wr.LinePlot(title="hours elapsed", x="_step",
                        y=["cost/hours_elapsed"]),
            wr.LinePlot(title="$/hour rate", x="_step", y=["cost/per_hour"]),
            wr.LinePlot(title="projected total $", x="_step",
                        y=["cost/projected_total_usd"]),
        ],
    ))

    workspace = ws.Workspace(
        name="Lysos training",
        entity=entity or os.environ.get("WANDB_ENTITY") or _default_entity(),
        project=project,
        sections=sections,
    )
    return workspace


def _default_entity() -> str:
    """Best-effort: use logged-in wandb user."""
    try:
        import wandb
        api = wandb.Api()
        return api.default_entity or ""
    except Exception:
        return ""


def main():
    if not os.environ.get("WANDB_API_KEY"):
        print("[X] WANDB_API_KEY not set in env.")
        print("    Run `wandb login <key>` first, then re-run this script.")
        return 1

    ws_obj = build_workspace()
    if ws_obj is None:
        return 1

    try:
        url = ws_obj.save()
        print(f"[OK] Workspace saved: {url}")
    except Exception as e:  # noqa: BLE001
        print(f"[!] Save failed: {e}")
        print("    The first wandb run from training will auto-create the project.")
        print("    Re-run after the first run starts.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
