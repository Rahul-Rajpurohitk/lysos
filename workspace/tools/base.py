"""Tool registry foundation — @tool decorator + ToolRegistry singleton.

A Tool is a Pydantic-typed Python callable that can be invoked by:
  1. Direct function call (Python)
  2. JSON RPC via MCP server endpoint
  3. LLM function calling (the model emits a tool call, we dispatch)

Every Tool exposes a JSON schema (inputs + outputs) compatible with:
  - Anthropic Claude function-calling
  - OpenAI function-calling
  - Google Gemini / Gemma 4 function-calling
  - MCP server protocol
  - K-Dense Scientific Agent Skills format
"""
from __future__ import annotations

import inspect
import logging
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints, Optional

from pydantic import BaseModel, ValidationError

log = logging.getLogger("workbench.tools")


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable
    input_model: type[BaseModel]
    output_model: type[BaseModel] | type | None
    category: str
    expected_duration_ms: int = 100
    needs_approval: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def schema(self) -> dict[str, Any]:
        """JSON schema for LLM function-calling."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self._output_schema(),
            "category": self.category,
            "tags": list(self.tags),
            "expected_duration_ms": self.expected_duration_ms,
            "needs_approval": self.needs_approval,
        }

    def _output_schema(self) -> dict[str, Any]:
        if self.output_model is None:
            return {"type": "null"}
        if inspect.isclass(self.output_model) and issubclass(self.output_model, BaseModel):
            return self.output_model.model_json_schema()
        return {"type": "any"}

    def call(self, args: dict[str, Any]) -> dict[str, Any]:
        """Validate, dispatch, and serialize the tool call. Returns a record."""
        t0 = time.perf_counter()
        record: dict[str, Any] = {
            "tool": self.name,
            "args": args,
            "result": None,
            "error": None,
            "duration_ms": 0,
        }
        try:
            parsed = self.input_model.model_validate(args)
            result = self.fn(**parsed.model_dump())
            if isinstance(result, BaseModel):
                record["result"] = result.model_dump(mode="json")
            else:
                record["result"] = result
        except ValidationError as e:
            record["error"] = f"ValidationError: {e}"
            log.warning("Tool %s validation failed: %s", self.name, e)
        except Exception as e:  # noqa: BLE001
            record["error"] = f"{type(e).__name__}: {e}"
            record["traceback"] = traceback.format_exc()
            log.exception("Tool %s raised", self.name)
        finally:
            record["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return record


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, t: Tool) -> None:
        if t.name in self._tools:
            log.warning("Tool %s overridden", t.name)
        self._tools[t.name] = t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def by_category(self, cat: str) -> list[Tool]:
        return [t for t in self._tools.values() if t.category == cat]

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    def schemas_for_anthropic(self) -> list[dict[str, Any]]:
        """Anthropic function-calling format (input_schema only)."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_model.model_json_schema(),
            }
            for t in self._tools.values()
        ]


registry = ToolRegistry()


def tool(
    *,
    name: Optional[str] = None,
    description: str,
    category: str,
    input_model: type[BaseModel],
    output_model: type[BaseModel] | type | None = None,
    expected_duration_ms: int = 100,
    needs_approval: bool = False,
    tags: tuple[str, ...] = (),
) -> Callable:
    """Decorator: register a function as a Tool."""
    def deco(fn: Callable) -> Callable:
        t = Tool(
            name=name or fn.__name__,
            description=description,
            fn=fn,
            input_model=input_model,
            output_model=output_model,
            category=category,
            expected_duration_ms=expected_duration_ms,
            needs_approval=needs_approval,
            tags=tags,
        )
        registry.register(t)
        fn._tool = t  # type: ignore[attr-defined]
        return fn
    return deco


__all__ = ["Tool", "ToolRegistry", "tool", "registry"]
