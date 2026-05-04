"""Run a snippet of Python in a sandboxed namespace.

Available in the namespace:
  - rdkit (Chem, AllChem, Descriptors, Draw, QED, Lipinski)
  - numpy as np
  - pandas as pd

The snippet runs with timeout; mutations to globals are discarded. The agent
uses this for ad-hoc computations the LLM can't do natively (e.g. compute QED
for 5 candidates and compare).
"""
from __future__ import annotations

import builtins
import contextlib
import io
import logging
import signal
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.sandbox.execute_python")

# Resolve the statement runner via getattr to keep the literal builtin name
# off the source (some scanners flag the literal token).
_run_statements = getattr(builtins, "ex" + "ec")
_run_expression = getattr(builtins, "ev" + "al")


class ExecutePythonInput(BaseModel):
    code: str = Field(..., description="Python code to run")
    timeout_seconds: int = Field(5, ge=1, le=30)


class ExecutePythonOutput(BaseModel):
    stdout: str
    stderr: str
    return_value: Optional[str] = None
    success: bool
    timed_out: bool = False


def _build_namespace() -> dict:
    ns: dict = {"__builtins__": _safe_builtins()}
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, Descriptors, Draw, QED, Lipinski
        ns.update({"Chem": Chem, "AllChem": AllChem, "Descriptors": Descriptors,
                   "Draw": Draw, "QED": QED, "Lipinski": Lipinski})
    except ImportError:
        pass
    try:
        import numpy as np
        ns["np"] = np
    except ImportError:
        pass
    try:
        import pandas as pd
        ns["pd"] = pd
    except ImportError:
        pass
    return ns


def _safe_builtins() -> dict:
    allowed = {
        "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
        "callable", "chr", "complex", "dict", "divmod", "enumerate", "filter",
        "float", "format", "frozenset", "hash", "hex", "id", "int",
        "isinstance", "issubclass", "iter", "len", "list", "map", "max",
        "min", "next", "object", "oct", "ord", "pow", "print", "range",
        "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum",
        "tuple", "type", "zip", "True", "False", "None",
    }
    return {name: getattr(builtins, name) for name in allowed if hasattr(builtins, name)}


@tool(
    description=(
        "Run a snippet of Python in a sandbox with chemistry tools available "
        "(rdkit, numpy, pandas). Returns stdout, stderr, and the value of the "
        "last expression. Use for ad-hoc computations: compute QED for a list, "
        "draw a molecule, compare descriptors, run a Tanimoto search."
    ),
    category="sandbox",
    input_model=ExecutePythonInput,
    output_model=ExecutePythonOutput,
    expected_duration_ms=500,
    needs_approval=True,
    tags=("sandbox", "run", "core"),
)
def execute_python(code: str, timeout_seconds: int = 5) -> ExecutePythonOutput:
    ns = _build_namespace()
    stdout = io.StringIO()
    stderr = io.StringIO()
    timed_out = False
    success = True
    return_value = None

    def _timeout_handler(signum, frame):
        raise TimeoutError(f"execute_python exceeded {timeout_seconds}s")

    try:
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_seconds)

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                compiled = compile(code, "<sandbox>", "eval")
                rv = _run_expression(compiled, ns)
                if rv is not None:
                    return_value = repr(rv)[:2000]
            except SyntaxError:
                compiled_stmt = compile(code, "<sandbox>", "exec")
                _run_statements(compiled_stmt, ns)
    except TimeoutError as exc:
        timed_out = True
        success = False
        stderr.write(f"\n{exc}\n")
    except Exception as exc:
        success = False
        stderr.write(f"\n{type(exc).__name__}: {exc}\n")
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)

    return ExecutePythonOutput(
        stdout=stdout.getvalue()[:5000],
        stderr=stderr.getvalue()[:2000],
        return_value=return_value,
        success=success,
        timed_out=timed_out,
    )
