# Lysos Workbench Architecture

This directory is the canonical reference for the Lysos system. Every file
here describes a stable contract that the model is trained on (via
teacher distillation) and that the codebase must respect.

## Documents

| File | Topic |
|------|-------|
| [agents.md](agents.md) | Designer / Critic / Strategist / Editor agent specs |
| [tools.md](tools.md) | 25-tool registry + decision tree |
| [ledger.md](ledger.md) | Candidate ledger schema (Postgres) |
| [state-machine.md](state-machine.md) | Designer state transitions |
| [handoff-protocol.md](handoff-protocol.md) | Inter-agent handoff envelope format |
| [error-escalation.md](error-escalation.md) | Error escalation chain |
| [api-contracts.md](api-contracts.md) | Tool request/response envelopes |
| [pipeline.md](pipeline.md) | End-to-end pipeline (Stage 0 → 6) |
| [stage-gates.md](stage-gates.md) | Candidate stage advancement criteria |
| [intervention.md](intervention.md) | User intervention handling |
| [branch-merge.md](branch-merge.md) | Campaign branching strategy |
| [subagent-dispatch.md](subagent-dispatch.md) | Scoped sub-agent dispatcher |
| [confidence.md](confidence.md) | Confidence reporting convention |
| [sprint-workflow.md](sprint-workflow.md) | 2-week sprint cadence |

## Why these docs exist

The Lysos training data includes ~10K teacher-distillation traces that
describe this architecture in exhaustive detail. The model learns from those
traces to operate inside this system. **For the trained model and the
implemented system to stay aligned, these docs must be kept in sync with
both the training data AND the actual code.**

When you change an agent's role, a tool's interface, the ledger schema,
or any contract: update the corresponding doc here, then regenerate the
matching distillation traces, then rebuild the dataset.

## Reading order for new contributors

1. [pipeline.md](pipeline.md) — what Lysos does end-to-end
2. [agents.md](agents.md) — who the players are
3. [tools.md](tools.md) — what they have at their disposal
4. [handoff-protocol.md](handoff-protocol.md) — how they coordinate
5. [ledger.md](ledger.md) — the shared state
6. Everything else — corner cases and operational details
