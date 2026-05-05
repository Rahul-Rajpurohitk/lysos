# Tool API Contracts

All tool calls are typed JSON envelopes with idempotency, caching, auth, and
observability.

## Request shape

```json
{
  "tool_name": "<name>",
  "input": { /* per-tool schema */ },
  "request_id": "<uuid v4>",
  "timeout_ms": <int>,                    // typically expected_duration × 3
  "trace_context": {
    "campaign_id": "...",
    "candidate_id": "...",
    "agent": "designer | critic | strategist | editor"
  }
}
```

## Response shape (success)

```json
{
  "request_id": "<echoed>",
  "tool_name": "<name>",
  "status": "ok",
  "output": { /* per-tool schema */ },
  "backend": "<implementation backend name>",
  "wall_clock_ms": <int>,
  "cached": <bool>
}
```

## Response shape (error)

```json
{
  "request_id": "<echoed>",
  "tool_name": "<name>",
  "status": "error",
  "error_code": "INVALID_INPUT | TIMEOUT | SERVICE_UNAVAILABLE | MODEL_UNCERTAIN | ...",
  "error_detail": "...",
  "retry_after_ms": <int>
}
```

## Idempotency

All Lysos tools are read-only / idempotent. Same input → same output (modulo
non-deterministic samplers, which are seeded). Safe to retry without side
effects.

## Caching

Inputs are content-hashed (SHA-256 of input JSON). Cached outputs in Redis
with TTL = 24h. Designer can pass `force_recompute: true` to bypass cache.

## Auth

All tool calls require an agent JWT (signed by Strategist) with allowed-tools
claim:
- **Designer**: all `amr` + `scoring` + `generative` + most `knowledge`
- **Critic**: all `scoring` + most `knowledge` + `compare_molecules`
- **Editor**: only `transform_structure` + `compare_molecules`
- **Strategist**: only `search_literature` (read-only orchestration)

## Observability

Every call emits an OpenTelemetry span with:
- `tool_name`, `input_hash`, `output_hash`
- `wall_clock_ms`, `agent`, `campaign_id`, `candidate_id`
- `cached` flag, `error_code` if applicable

Aggregated in the Workbench analytics dashboard.

## Per-tool schemas

See [tools.md](tools.md) for the full registry with input/output specs.
Per-tool error vocabulary in [error-escalation.md](error-escalation.md).

## Versioning

Tools are versioned semantically: `predict_mic_pathogen.v2` indicates a
breaking change in either input or output schema. The router dispatches by
explicit version when the caller requests it; defaults to latest stable
otherwise.
