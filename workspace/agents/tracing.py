"""LangSmith tracing for the Lysos agent harness — graceful no-op fallback.

If LANGCHAIN_API_KEY is set, every agent turn + tool call gets uploaded to
LangSmith as a hierarchical trace tree:

  /design MRSA
    ├─ strategist.init        (root)
    │    └─ tool: get_pathogen_resistome
    ├─ iteration 1
    │    ├─ designer
    │    │    ├─ tool: find_similar_drugs
    │    │    └─ tool: place_in_pocket  ← Service 1
    │    ├─ score_candidate
    │    │    ├─ tool: score_molecule
    │    │    ├─ tool: place_in_pocket  ← auto-fired
    │    │    └─ tool: map_resistance_vulnerability  ← auto-fired (Service 2)
    │    ├─ critic
    │    └─ editor
    ├─ iteration 2 ...

Without an API key the wrappers are no-ops — agent harness behaves
identically. So this is safe to ship without configuration.

Usage:
    from workspace.agents.tracing import traced, trace_tool

    @traced(name="run_designer", run_type="chain")
    async def run_designer(...): ...

    # Inside _dispatch_tool:
    async with trace_tool(tool_name, args) as t:
        result = await dispatch(...)
        t.set_output(result)

Setup (free tier):
    1. https://smith.langchain.com — sign up, free
    2. Create project "lysos"
    3. Copy API key
    4. Add to .env:
         LANGCHAIN_API_KEY=ls__...
         LANGCHAIN_PROJECT=lysos
         LANGCHAIN_TRACING_V2=true
    5. Restart backend; traces appear in dashboard live
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, Callable, Optional

log = logging.getLogger("agents.tracing")

# Initialize lazily so import is cheap when LangSmith isn't configured.
_LS_CLIENT: Optional[Any] = None
_LS_TRACEABLE: Optional[Callable] = None
_INITIALIZED = False


def _init_langsmith() -> None:
    """Lazily initialize the LangSmith client + traceable decorator.
    No-op if LANGCHAIN_API_KEY is missing."""
    global _LS_CLIENT, _LS_TRACEABLE, _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True
    api_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        log.info("LangSmith disabled (no LANGCHAIN_API_KEY in env) — tracing wrappers will no-op")
        return
    try:
        from langsmith import Client, traceable as _traceable
        _LS_CLIENT = Client(api_key=api_key)
        _LS_TRACEABLE = _traceable
        # Set the tracing-v2 flag so any nested LangChain calls also emit
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_PROJECT", os.environ.get("LANGCHAIN_PROJECT", "lysos"))
        log.info("LangSmith enabled · project=%s", os.environ.get("LANGCHAIN_PROJECT", "lysos"))
    except ImportError:
        log.warning("langsmith package not installed — pip install langsmith")
    except Exception as exc:  # noqa: BLE001
        log.warning("LangSmith init failed: %s — tracing wrappers will no-op", exc)


def is_enabled() -> bool:
    _init_langsmith()
    return _LS_TRACEABLE is not None


def traced(name: str, run_type: str = "chain", **extras: Any) -> Callable:
    """Decorator that wraps an async function with a LangSmith run trace.
    No-op if LangSmith isn't configured.

    run_type values: 'llm', 'tool', 'chain', 'retriever', 'embedding'
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            _init_langsmith()
            if _LS_TRACEABLE is None:
                return await fn(*args, **kwargs)
            # langsmith's @traceable handles async funcs automatically
            wrapped = _LS_TRACEABLE(name=name, run_type=run_type, **extras)(fn)
            return await wrapped(*args, **kwargs)
        return wrapper
    return decorator


@asynccontextmanager
async def trace_tool(tool_name: str, args: dict, agent: Optional[str] = None):
    """Context manager that traces a tool call as a child span.

    Usage:
        async with trace_tool("score_molecule", {"smiles": ...}, agent="critic") as span:
            result = await dispatch(...)
            span["result"] = result.get("result")
            span["error"] = result.get("error")
    """
    _init_langsmith()
    span: dict[str, Any] = {"tool": tool_name, "args": args, "agent": agent}
    if _LS_TRACEABLE is None or _LS_CLIENT is None:
        yield span
        return

    # Use the run-tree pattern for a proper child span
    try:
        from langsmith.run_helpers import trace as ls_trace
        with ls_trace(
            name=f"tool: {tool_name}",
            run_type="tool",
            inputs={"args": args, "agent": agent},
            project_name=os.environ.get("LANGCHAIN_PROJECT", "lysos"),
        ) as run:
            t0 = time.perf_counter()
            try:
                yield span
                run.add_outputs({
                    "result": _safe_json(span.get("result")),
                    "error": span.get("error"),
                    "duration_ms": int((time.perf_counter() - t0) * 1000),
                })
            except Exception as exc:  # noqa: BLE001
                run.add_outputs({"error": str(exc)})
                raise
    except Exception as exc:  # noqa: BLE001
        log.debug("trace_tool span failed (%s) — continuing without trace", exc)
        yield span


def _safe_json(obj: Any) -> Any:
    """Make sure we can serialize the result for LangSmith. Trims very large
    payloads so we don't blow past LangSmith's per-run size limits."""
    try:
        import json
        s = json.dumps(obj, default=str)
        if len(s) > 8000:
            return {"_truncated": True, "preview": s[:4000] + "...[truncated]"}
        return obj
    except Exception:
        return {"_repr": str(obj)[:1000]}


def trace_url() -> Optional[str]:
    """Return the LangSmith dashboard URL for the current project, or None."""
    _init_langsmith()
    if _LS_CLIENT is None:
        return None
    project = os.environ.get("LANGCHAIN_PROJECT", "lysos")
    return f"https://smith.langchain.com/o/-/projects/{project}"


# Convenience: identify whether we're in a running trace context (for logging)
def in_trace() -> bool:
    return is_enabled()
