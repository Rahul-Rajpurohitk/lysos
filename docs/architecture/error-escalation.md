# Error Escalation Chain

Errors flow up the agent hierarchy: tool → designer → critic → strategist → user.

## Level 0: Tool

Tool returns a structured error code. Tool retries once internally before
returning error.

| Error code | Meaning |
|------------|---------|
| `INVALID_INPUT` | Input schema validation failed |
| `TIMEOUT` | Exceeded expected_duration_ms × 5 |
| `SERVICE_UNAVAILABLE` | Backend service down |
| `MODEL_UNCERTAIN` | Confidence < 0.4 |
| `OUT_OF_DOMAIN` | Input outside training distribution |
| `NO_ROUTE_FOUND` | AizynthFinder couldn't find a viable retrosynthesis |
| `POSE_NOT_CONVERGED` | Sampling didn't converge (Boltz-2 / dock) |
| `TARGET_NOT_FOUND` | PDB id not in mirror |

## Level 1: Designer

Designer receives error → tries recovery:

| Error | Recovery |
|-------|----------|
| `INVALID_INPUT` | Editor canonicalize SMILES + retry |
| `TIMEOUT` | Retry with smaller batch / shorter context |
| `SERVICE_UNAVAILABLE` | Wait + retry once; if still down, escalate |
| `MODEL_UNCERTAIN` | Run orthogonal tool for cross-check; if both agree, accept; if not, escalate |
| `NO_ROUTE_FOUND` | Try scaffold_hop to a more conventional core; if still no route, escalate |
| `POSE_NOT_CONVERGED` | Increase n_poses; or fall back to predict_binding_affinity |
| `TARGET_NOT_FOUND` | find_target_structure(pathogen) for valid PDB |

After 1 recovery attempt, escalate to Level 3 (Critic doesn't handle errors
directly).

## Level 2: Critic

Critic does NOT handle errors directly — it reviews completed candidates.
But Critic CAN trigger error escalation if it detects a systematic issue
(e.g., 5 consecutive candidates fail predict_resistance_escape — likely a
service issue).

## Level 3: Strategist

Strategist receives error escalation → decides:

| Situation | Decision |
|-----------|----------|
| Dependent tool down | Pause the campaign; resume when the tool is back up |
| Systematic failure | Switch tool family (e.g., dock_against_target instead of predict_complex_structure) |
| Budget exhausted | Kill the campaign + emit summary to user |
| Critical error | Pause + escalate to user |

## Level 4: User

User receives a notification with:
- Campaign id + state at time of error
- Error chain (which tool, which agent, what was tried)
- Suggested actions (continue, pivot, kill)

User can intervene with one of the standard interventions (see
intervention.md).

## Error envelope

```json
{
  "type": "error",
  "campaign_id": "<id>",
  "agent": "designer | critic | strategist",
  "error_code": "INVALID_INPUT | TIMEOUT | SERVICE_UNAVAILABLE | MODEL_UNCERTAIN | NO_ROUTE_FOUND",
  "context": {"tool": "<name>", "smiles": "..."},
  "recovery_attempted": ["<step1>", "<step2>"],
  "escalation_target": "strategist | user"
}
```

## Retry policy

- **Idempotent tools (read-only, all of Lysos)**: retry up to 3 times with exponential backoff
- **Mutating tools (none in current Lysos)**: retry once, then escalate

## Observability

Every error escalation emits an OpenTelemetry span:
- `error_code`, `agent`, `recovery_attempted`, `escalation_target`
- Aggregated in the Workbench analytics for systematic-failure detection
