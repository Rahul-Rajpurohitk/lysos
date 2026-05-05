"""Resilient HF Hub push with exponential-backoff retries.

Why this exists:
  Stage 1 takes ~6h on 8x MI300X. Stage 2 takes ~12h. Stage 3 takes ~10h.
  A single network blip during the final `trainer.push_to_hub()` would
  silently lose the model. We retry with backoff and verify the push
  by reading back the model card.

Usage:
    from src.training.hub_push import push_with_retry
    push_with_retry(trainer, repo_id, commit_message,
                    private=True, max_retries=4, backoff_s=30)
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)


def push_with_retry(
    trainer: Any,
    repo_id: str,
    commit_message: str,
    *,
    private: bool = True,
    max_retries: int = 4,
    backoff_s: float = 30.0,
    verify: bool = True,
) -> bool:
    """Push the trainer's model + tokenizer with N exponential-backoff retries.

    Returns True iff the push succeeded AND verification passed.

    On each attempt:
      1. Call trainer.push_to_hub(commit_message=..., private=...)
      2. If verify=True, read the model card via huggingface_hub.HfApi.
      3. On any exception, sleep backoff_s * 2**attempt and retry.

    After max_retries, returns False (caller decides whether to raise).
    The trainer's local checkpoint dir is preserved either way, so a manual
    `huggingface-cli upload` recovers the run.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            log.info("Hub push attempt %d/%d -> %s (private=%s)",
                     attempt + 1, max_retries, repo_id, private)
            trainer.push_to_hub(commit_message=commit_message)
            if verify:
                _verify_pushed(repo_id)
            log.info("Hub push OK: %s", repo_id)
            return True
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            wait = backoff_s * (2 ** attempt)
            log.warning("Hub push failed (attempt %d/%d): %s -- sleeping %.1fs",
                        attempt + 1, max_retries, exc, wait)
            time.sleep(wait)

    log.error(
        "Hub push EXHAUSTED %d retries to %s. Last error: %s. "
        "Local checkpoints preserved at trainer.args.output_dir; recover via "
        "`huggingface-cli upload <repo_id> <local_dir>`.",
        max_retries, repo_id, last_exc,
    )
    return False


def _verify_pushed(repo_id: str) -> None:
    """Read back the README to confirm the push landed.

    HF API can return success on the upload before the commit replicates.
    A read-after-write here adds ~2s and catches partial pushes.
    """
    from huggingface_hub import HfApi

    api = HfApi()
    info = api.model_info(repo_id, files_metadata=False)
    if info is None:
        raise RuntimeError(f"verify failed: model_info({repo_id}) returned None")
    log.info("verify ok: %s @ %s (sha=%s)",
             repo_id, info.last_modified, getattr(info, "sha", "?")[:8])
