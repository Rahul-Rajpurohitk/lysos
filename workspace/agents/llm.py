"""LLM endpoint abstraction — Claude (placeholder) → vLLM Gemma 4 31B (Day 4).

Three backends, picked by env:
  - LYSOS_LLM_BACKEND=claude   (default, pre-Day-4)
  - LYSOS_LLM_BACKEND=vllm     (post-Day-4, Gemma 4 31B-it on MI300X)
  - LYSOS_LLM_BACKEND=mock     (no API calls, deterministic outputs for tests)

All three speak the same JSON tool-calling protocol so swapping is a config flip.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator, Optional

log = logging.getLogger("workbench.agents.llm")


class LLMEndpoint:
    """Abstract LLM endpoint with Anthropic-style messages + tool calling."""

    def __init__(self, model: str, max_tokens: int = 2048, temperature: float = 0.7):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def acomplete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
    ) -> dict:
        """Async completion. Returns {content, tool_calls, finish_reason}."""
        raise NotImplementedError

    async def astream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """Async streaming. Yields delta events."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Claude (Anthropic) backend — placeholder pre-Day-4
# ---------------------------------------------------------------------------

class ClaudeEndpoint(LLMEndpoint):
    def __init__(self, model: str = "claude-sonnet-4-5-20250929", **kwargs):
        super().__init__(model=model, **kwargs)
        try:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic()
        except ImportError:
            log.warning("anthropic SDK not installed — install with `pip install anthropic`")
            self._client = None

    async def acomplete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
    ) -> dict:
        if self._client is None:
            return {"content": "[anthropic SDK not installed]",
                    "tool_calls": [], "finish_reason": "error"}

        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if system:
            kwargs["system"] = system

        resp = await self._client.messages.create(**kwargs)

        content_text = ""
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "args": block.input,
                })

        return {
            "content": content_text,
            "tool_calls": tool_calls,
            "finish_reason": resp.stop_reason,
            "usage": {
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
        }

    async def astream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        if self._client is None:
            yield {"type": "error", "data": "anthropic SDK not installed"}
            return

        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if system:
            kwargs["system"] = system

        async with self._client.messages.stream(**kwargs) as stream:
            async for ev in stream:
                # Simplify event types into a uniform protocol
                if hasattr(ev, "type"):
                    if ev.type == "content_block_delta":
                        delta = getattr(ev, "delta", None)
                        if delta and hasattr(delta, "text"):
                            yield {"type": "text_delta", "data": delta.text}
                        elif delta and hasattr(delta, "partial_json"):
                            yield {"type": "tool_args_delta", "data": delta.partial_json}
                    elif ev.type == "content_block_start":
                        block = getattr(ev, "content_block", None)
                        if block and block.type == "tool_use":
                            yield {"type": "tool_call_start",
                                   "data": {"name": block.name, "id": block.id}}
                    elif ev.type == "message_stop":
                        yield {"type": "done", "data": None}


# ---------------------------------------------------------------------------
# vLLM (Gemma 4 31B-it on MI300X) — Day 4 swap target
# ---------------------------------------------------------------------------

class VLLMEndpoint(LLMEndpoint):
    def __init__(
        self,
        model: str = "google/gemma-4-31B-it",
        base_url: str = "http://localhost:8000/v1",
        api_key: str = "EMPTY",
        **kwargs,
    ):
        super().__init__(model=model, **kwargs)
        self.base_url = base_url
        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        except ImportError:
            log.warning("openai SDK not installed — needed for vLLM client")
            self._client = None

    async def acomplete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
    ) -> dict:
        if self._client is None:
            return {"content": "[openai SDK not installed]",
                    "tool_calls": [], "finish_reason": "error"}

        oai_messages = list(messages)
        if system:
            oai_messages = [{"role": "system", "content": system}] + oai_messages

        oai_tools = None
        if tools:
            oai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]

        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=oai_messages,
            tools=oai_tools,
            tool_choice="auto" if oai_tools else None,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        choice = resp.choices[0]

        tool_calls = []
        for tc in (choice.message.tool_calls or []):
            tool_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "args": json.loads(tc.function.arguments) if tc.function.arguments else {},
            })

        return {
            "content": choice.message.content or "",
            "tool_calls": tool_calls,
            "finish_reason": choice.finish_reason,
            "usage": {
                "input_tokens": resp.usage.prompt_tokens,
                "output_tokens": resp.usage.completion_tokens,
            },
        }


# ---------------------------------------------------------------------------
# Mock (deterministic, for unit tests + offline dev)
# ---------------------------------------------------------------------------

class MockEndpoint(LLMEndpoint):
    """Deterministic mock LLM that exercises the full agent loop:

    - Designer first turn → calls one grounding tool (find_similar_drugs or
      check_resistance_genes), then turn 2 → emits a PROPOSAL.
    - Critic → returns a parseable WEAKNESS/TRANSFORMATION block, escalating
      to VERDICT: ACCEPT once composite is high enough.

    No randomness — fully reproducible across test runs.
    """

    def __init__(self, model: str = "mock-llm", **kwargs):
        super().__init__(model=model, **kwargs)
        self._counter = 0
        self._designer_turn_in_iter = 0  # tracks tool-vs-proposal turn

    async def acomplete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
    ) -> dict:
        sys_lower = (system or "").lower()
        is_critic = "critic" in sys_lower and "designer" not in sys_lower
        is_designer = "designer" in sys_lower or sys_lower.startswith("you are the **designer**")

        if is_critic:
            self._counter += 1
            ops = ["add_hydroxyl", "add_fluorine", "add_methyl", "add_amine"]
            op = ops[self._counter % len(ops)]
            # Once we have several iterations, Critic accepts so loop terminates
            if self._counter >= 4:
                return {
                    "content": (
                        "VERDICT: ACCEPT\n"
                        "RATIONALE: [mock] Composite plateau reached and core "
                        "scaffold satisfies constraints. Final answer."
                    ),
                    "tool_calls": [],
                    "finish_reason": "end_turn",
                }
            return {
                "content": (
                    f"WEAKNESS: drug_likeness_qed (current=0.45, target=0.70)\n"
                    f"TRANSFORMATION: {op}\n"
                    f"RATIONALE: [mock] Adding polarity should improve QED.\n"
                    f"EXPECTED_DELTA: +0.15 on drug_likeness_qed"
                ),
                "tool_calls": [],
                "finish_reason": "end_turn",
            }

        # Designer path
        # Detect whether this is a fresh iteration (first user message) or a
        # tool-result follow-up — by counting prior assistant turns in `messages`
        n_assistant = sum(1 for m in messages if m.get("role") == "assistant")
        last_msg = messages[-1] if messages else {}
        last_user_block = last_msg.get("content") if last_msg.get("role") == "user" else None
        already_used_tools = isinstance(last_user_block, list) and any(
            (b.get("type") == "tool_result" if isinstance(b, dict) else False)
            for b in last_user_block
        )

        # Turn 1 of an iteration → call a grounding tool first (only if tools
        # are provided AND we haven't already received tool results).
        if tools and n_assistant == 0 and not already_used_tools:
            self._counter += 1
            # Pick the first useful tool from what's offered
            preferred = ["check_resistance_genes", "find_similar_drugs",
                         "find_active_against_mdr", "predict_admet"]
            chosen = None
            for name in preferred:
                for t in tools:
                    if t.get("name") == name:
                        chosen = t
                        break
                if chosen:
                    break
            if chosen is None:
                chosen = tools[0]

            args = _mock_args_for(chosen)
            return {
                "content": (
                    f"[mock-designer turn 1] Grounding via {chosen['name']} "
                    f"to anticipate resistance + nearest known drugs."
                ),
                "tool_calls": [{
                    "id": f"toolu_mock_{self._counter}",
                    "name": chosen["name"],
                    "args": args,
                }],
                "finish_reason": "tool_use",
            }

        # Turn 2+: emit the SMILES PROPOSAL
        smiles_panel = [
            "CC(=O)NC[C@H]1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1",       # linezolid
            "CC1(C)S[C@@H]2[C@H](NC(=O)[C@@H](N)c3ccc(O)cc3)C(=O)N2[C@H]1C(=O)O",  # amoxicillin
            "O=C(O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O",            # ciprofloxacin
            "CC1[C@@H]2CC(=C(N2C1=O)C(=O)O)S[C@H]3CN[C@@H](C3)C(=O)N(C)C",  # meropenem
        ]
        proposal = smiles_panel[(self._counter - 1) % len(smiles_panel)]
        return {
            "content": (
                f"[mock-designer turn 2] Iteration {self._counter}.\n\n"
                f"PROPOSAL: {proposal}\n"
                f"RATIONALE: Mock proposal grounded in resistome briefing + "
                f"nearest-neighbour scan. Real Designer (Gemma 4 31B-it) will "
                f"emit novel chemistry on Day 4."
            ),
            "tool_calls": [],
            "finish_reason": "end_turn",
        }


def _mock_args_for(tool: dict) -> dict:
    """Generate plausible mock args based on the tool's input schema."""
    schema = tool.get("input_schema", {})
    props = schema.get("properties", {})
    args = {}
    for k, v in props.items():
        if "smiles" in k.lower():
            args[k] = "CC(=O)NCC1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1"  # linezolid
        elif "pathogen" in k.lower():
            args[k] = "MRSA"
        elif v.get("type") == "integer":
            args[k] = v.get("default", 5)
        elif v.get("type") == "number":
            args[k] = v.get("default", 0.5)
        elif v.get("type") == "string":
            args[k] = v.get("default", "")
    return args


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_llm(backend: Optional[str] = None) -> LLMEndpoint:
    """Pick backend by env LYSOS_LLM_BACKEND or explicit arg.

    Critical SaaS-readiness behaviour: if the chosen backend can't
    actually initialize (SDK missing, API key missing, vLLM server down),
    we fall back to MockEndpoint so the demo flow always works
    end-to-end. Operators see a one-time WARNING in the log.
    """
    backend = backend or os.environ.get("LYSOS_LLM_BACKEND", "claude")
    if backend == "mock":
        return MockEndpoint()
    if backend == "claude":
        ep = ClaudeEndpoint(
            model=os.environ.get("LYSOS_CLAUDE_MODEL", "claude-sonnet-4-5-20250929"),
        )
        if ep._client is None or not os.environ.get("ANTHROPIC_API_KEY"):
            log.warning(
                "Claude backend not usable (SDK missing or ANTHROPIC_API_KEY "
                "not set). Falling back to MockEndpoint so the demo still "
                "completes end-to-end. Set ANTHROPIC_API_KEY + install "
                "`anthropic` for real Designer output."
            )
            return MockEndpoint()
        return ep
    if backend == "vllm":
        ep = VLLMEndpoint(
            model=os.environ.get("LYSOS_VLLM_MODEL", "google/gemma-4-31B-it"),
            base_url=os.environ.get("LYSOS_VLLM_URL", "http://localhost:8000/v1"),
        )
        if ep._client is None:
            log.warning("vLLM client not initialised — falling back to MockEndpoint.")
            return MockEndpoint()
        return ep
    raise ValueError(f"Unknown LLM backend: {backend}")
