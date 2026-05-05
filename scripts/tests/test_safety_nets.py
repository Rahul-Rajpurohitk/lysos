"""Tests for the cost / hub / killswitch / generator safety nets.

These are the gates that protect a real training run. If they break,
we'd burn budget or lose a checkpoint — so they're tested even though
they look 'simple'.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------
# CostCallback
# ---------------------------------------------------------------------


def test_cost_callback_hard_stops_when_projected_exceeds_budget():
    from src.training.cost_callback import CostCallback

    cb = CostCallback(gpu_class="mi300x_small_1gpu",
                      budget_usd=10.0, hard_stop=True)
    cb.start_time = time.time() - 3600  # 1 hour ago, $3 spent
    state = SimpleNamespace(global_step=10, max_steps=100)
    control = SimpleNamespace(should_training_stop=False)

    cb.on_step_end(args=None, state=state, control=control)

    # 10 steps in 1h → total projected = 100 * 0.1h * $3 = $30 > $10.5
    assert control.should_training_stop is True, \
        "should hard-stop when projection exceeds 1.05x budget"


def test_cost_callback_does_not_stop_when_under_budget():
    from src.training.cost_callback import CostCallback

    cb = CostCallback(gpu_class="mi300x_small_1gpu",
                      budget_usd=300.0, hard_stop=True)
    cb.start_time = time.time() - 60  # 1 minute ago
    state = SimpleNamespace(global_step=10, max_steps=100)
    control = SimpleNamespace(should_training_stop=False)

    cb.on_step_end(args=None, state=state, control=control)
    assert control.should_training_stop is False


def test_cost_callback_respects_killswitch_stop_flag(tmp_path, monkeypatch):
    """If /tmp/lysos_stop exists, callback sets stop=True regardless of
    cost projection."""
    from src.training import cost_callback as cc

    stop_file = tmp_path / "lysos_stop"
    stop_file.write_text("")
    monkeypatch.setattr("os.path.exists",
                        lambda p: p == "/tmp/lysos_stop" or os.path.isfile(p) if p != "/tmp/lysos_stop" else True)

    cb = cc.CostCallback(budget_usd=1000.0, hard_stop=True)
    cb.start_time = time.time() - 1
    state = SimpleNamespace(global_step=1, max_steps=10)
    control = SimpleNamespace(should_training_stop=False)
    cb.on_step_end(args=None, state=state, control=control)
    assert control.should_training_stop is True


def test_cost_callback_subclasses_trainer_callback():
    """The transformers callback dispatcher requires this — fall through
    on every event we don't override."""
    from src.training.cost_callback import CostCallback
    try:
        from transformers import TrainerCallback
    except ImportError:
        pytest.skip("transformers not installed")
    cb = CostCallback()
    assert isinstance(cb, TrainerCallback)


# ---------------------------------------------------------------------
# hub_push retry logic
# ---------------------------------------------------------------------


def test_hub_push_retries_on_failure():
    from src.training.hub_push import push_with_retry

    trainer = MagicMock()
    # First 2 calls raise, third succeeds.
    trainer.push_to_hub.side_effect = [
        RuntimeError("network blip"),
        RuntimeError("blip again"),
        None,
    ]
    with patch("src.training.hub_push._verify_pushed", return_value=None):
        ok = push_with_retry(trainer, "rahul24raj/test", "msg",
                              max_retries=3, backoff_s=0.001)
    assert ok is True
    assert trainer.push_to_hub.call_count == 3


def test_hub_push_returns_false_after_max_retries():
    from src.training.hub_push import push_with_retry
    trainer = MagicMock()
    trainer.push_to_hub.side_effect = RuntimeError("perma-fail")
    with patch("src.training.hub_push._verify_pushed", return_value=None):
        ok = push_with_retry(trainer, "rahul24raj/test", "msg",
                              max_retries=3, backoff_s=0.001)
    assert ok is False
    assert trainer.push_to_hub.call_count == 3


def test_hub_push_verifies_after_push():
    """Read-after-write: even if push succeeds, fail closed if verify fails."""
    from src.training.hub_push import push_with_retry
    trainer = MagicMock()
    with patch("src.training.hub_push._verify_pushed",
               side_effect=RuntimeError("model_info returned None")):
        ok = push_with_retry(trainer, "rahul24raj/test", "msg",
                              max_retries=2, backoff_s=0.001, verify=True)
    assert ok is False, "verify failure should mark push as not OK"
    assert trainer.push_to_hub.call_count == 2


# ---------------------------------------------------------------------
# Killswitch
# ---------------------------------------------------------------------


def test_killswitch_writes_stop_flag(tmp_path, monkeypatch):
    """Soft-stop should write the stop file the cost callback reads."""
    monkeypatch.setattr(
        "scripts.killswitch.STOP_FILE_PATH",
        str(tmp_path / "stop"),
    )
    from scripts import killswitch

    fake_run = MagicMock()
    fake_run.name = "fake_run"
    fake_run.id = "abc"
    fake_run.stop = MagicMock()

    fake_api = MagicMock()
    fake_api.run.return_value = fake_run

    with patch.object(killswitch, "_api", return_value=fake_api):
        rc = killswitch.cmd_soft("abc")

    assert rc == 0
    assert (tmp_path / "stop").exists() or Path("/tmp/lysos_stop").exists()


# ---------------------------------------------------------------------
# LysosGenerator import smoke
# ---------------------------------------------------------------------


def test_lysos_generator_importable():
    """Even without a model loaded, the class should construct."""
    from src.inference.generate import LysosGenerator
    # Don't actually load — just construct. The lazy `_load()` is the heavy bit.
    gen = LysosGenerator(model_id="sshleifer/tiny-gpt2", adapter_id=None)
    assert gen is not None
    assert hasattr(gen, "design")
    assert hasattr(gen, "_load")


def test_extract_smiles_handles_proposal_prefix():
    from src.eval.rewards import extract_smiles
    assert extract_smiles("PROPOSAL: CCO") == "CCO"
    assert extract_smiles("SMILES: CC(=O)O") == "CC(=O)O"
    assert extract_smiles("```smiles\nCCN\n```") == "CCN"
    assert extract_smiles("garbage no smiles here") is None
