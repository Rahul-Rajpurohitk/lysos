# Sub-Agent Dispatcher

Lysos uses scoped sub-agents for tasks that need fresh context. The parent
agent (Strategist or Designer) emits a dispatch envelope; the sub-agent runs
in isolation with the scoped task only.

## Why sub-agents

- **Context window discipline** — parent doesn't pollute its context with sub-task details
- **Parallelism** — multiple sub-agents run simultaneously
- **Specialization** — different sub-agents have different system prompts + tool subsets

## Dispatch envelope

```json
{
  "type": "dispatch",
  "parent_agent": "designer | strategist",
  "subagent_role": "editor | critic | red_team | resistance_forecaster | manufacturing_eval",
  "scoped_task": "<one-sentence task description>",
  "scoped_inputs": {"smiles": "...", "pathogen": "..."},
  "allowed_tools": ["predict_resistance_escape", "check_resistance_genes"],
  "timeout_ms": 30000,
  "return_format": "json | structured_text"
}
```

## Return envelope

```json
{
  "type": "dispatch_return",
  "dispatch_id": "<uuid>",
  "subagent_role": "...",
  "result": {"verdict": "low-risk", "summary": "..."},
  "tool_calls_made": ["predict_resistance_escape"],
  "wall_clock_ms": 850
}
```

## Standard sub-agents

| Sub-agent | Role |
|-----------|------|
| Editor | SMILES sanitization + named transforms |
| Critic | 8-dimension review |
| Red-Team | Adversarial mutation + escape prediction |
| Resistance-Forecaster | Predict where resistance emerges in 24-36 mo |
| Manufacturing-Eval | Stereo + scale + cost trade-offs |
| Clinical-Positioning | Indication + dose + route reasoning |
| Literature-Grounding | search_literature + cite recent papers |
| Confidence-Calibrator | When to trust predictors, when to verify |
| Novelty-Checker | Tanimoto + scaffold-distinct comparison |

## Example dispatch (Designer → Novelty-Checker)

```json
{
  "type": "dispatch",
  "parent_agent": "designer",
  "subagent_role": "critic_novelty",
  "scoped_task": "compute Tanimoto of candidate vs known-antibiotic index; report top-3 matches",
  "scoped_inputs": {"smiles": "OC(=O)[C@H]1..."},
  "allowed_tools": ["find_similar_drugs", "compare_molecules"],
  "timeout_ms": 5000
}
```

The Novelty-Checker only has access to the listed tools — limits blast
radius if it misbehaves.

## Allowed-tools enforcement

The router validates `allowed_tools` against the sub-agent's request before
dispatching. If a sub-agent tries to call a tool outside its allowed list,
the call is rejected with `TOOL_NOT_ALLOWED`.

This is enforced via the agent JWT (see api-contracts.md).

## Parallel dispatch

Strategist can dispatch multiple sub-agents simultaneously:

```json
{
  "type": "parallel_dispatch",
  "subagents": [
    {"role": "novelty_checker", "scoped_task": "..."},
    {"role": "resistance_forecaster", "scoped_task": "..."},
    {"role": "manufacturing_eval", "scoped_task": "..."}
  ],
  "wait_strategy": "all | first_complete | majority"
}
```

Parent agent receives a single combined response when the wait strategy is satisfied.
