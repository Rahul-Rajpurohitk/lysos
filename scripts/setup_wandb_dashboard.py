"""setup_wandb_dashboard.py — wandb dashboard initialization for Lysos.

Two-mode behavior:
  1. PRIMARY: Bootstrap the `lysos` project + register `define_metric` calls
     for every metric our training emits, so wandb auto-organizes panels
     into groups (train/, eval/, reward/, cost/, system/) the moment the
     first real run starts. Free-tier compatible.

  2. OPTIONAL: If wandb-workspaces SDK + paid-tier permissions allow,
     also save a 6-section Workspace view with custom panel layouts.
     Fails gracefully on free tier (the auto-organized default panels
     are already excellent).

Run AFTER `wandb login` so the user is the project owner:
    python scripts/setup_wandb_dashboard.py
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
    # Reuse verify_keys' fallbacks (env -> .env -> ~/.netrc) so the script
    # works whether the user did `wandb login`, set the env var, or put it
    # in .env.
    try:
        import verify_keys as vk
        vk._load_dotenv(ROOT / ".env")
        vk._load_wandb_netrc()
    except Exception:
        pass

    if not os.environ.get("WANDB_API_KEY"):
        print("[X] WANDB_API_KEY not set in env / .env / ~/.netrc.")
        print("    Run `wandb login <key>` first, then re-run this script.")
        return 1

    # ---- PRIMARY: bootstrap project + register metric definitions ----
    project = "lysos"
    entity = os.environ.get("WANDB_ENTITY") or _default_entity()
    try:
        import wandb
        api = wandb.Api()
        try:
            api.project(name=project, entity=entity)
            print(f"[OK] Project {entity}/{project} exists.")
        except Exception:
            print(f"[..] Project {entity}/{project} not found; creating with metric defs...")
        # Always emit a bootstrap run so define_metric calls register
        run = wandb.init(
            project=project, entity=entity, name="dashboard-bootstrap",
            tags=["bootstrap", "metric-schema"], reinit=True,
            config={"purpose": "register metric schema for auto-organized panels"},
        )
        # Define metric groups: wandb's default workspace will group by these
        # patterns so reward/* lands in one section, cost/* another, etc.
        wandb.define_metric("train/global_step")
        wandb.define_metric("train/*", step_metric="train/global_step")
        wandb.define_metric("eval/global_step")
        wandb.define_metric("eval/*", step_metric="eval/global_step")
        wandb.define_metric("reward/*", step_metric="train/global_step")
        wandb.define_metric("cost/*", step_metric="train/global_step")
        wandb.define_metric("grpo/*", step_metric="train/global_step")

        # Log placeholder values so the metrics show up in autogen panels
        for c in REWARD_COMPONENTS:
            wandb.log({f"reward/{c}": 0.0})
        wandb.log({
            "train/loss": 0.0, "train/learning_rate": 0.0, "train/grad_norm": 0.0,
            "eval/avg_composite": 0.0, "eval/n_valid": 0,
            "cost/hours_elapsed": 0.0, "cost/per_hour": 0.0,
            "cost/projected_total_usd": 0.0, "cost/budget_pct_used": 0.0,
            "grpo/kl": 0.0, "grpo/policy_loss": 0.0, "grpo/advantage_mean": 0.0,
        })
        run.finish()
        print(f"[OK] Bootstrap run finished; metric schema registered.")
        print(f"     URL: https://wandb.ai/{entity}/{project}")
    except Exception as e:  # noqa: BLE001
        print(f"[!] Bootstrap failed: {e}")
        return 1

    # ---- OPTIONAL: try to save a custom Workspace view ----
    ws_obj = build_workspace(project=project, entity=entity)
    if ws_obj is None:
        print("    (wandb-workspaces SDK not installed; skipping custom view)")
        return 0

    try:
        ws_obj.save()
        print(f"[OK] Custom Workspace view saved.")
    except Exception as e:  # noqa: BLE001
        # Free tier or older wandb server may not allow programmatic
        # workspace creation. Auto-organized panels still work fine.
        print(f"[!] Custom Workspace save not available ({type(e).__name__}); auto-organized panels are sufficient.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
