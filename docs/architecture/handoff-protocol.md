# Handoff Protocol

Every inter-agent message is a structured JSON envelope. The receiving agent
either acts on it or rejects with a typed error. Free-text handoffs are
rejected by the message router.

## Designer → Critic envelope

```json
{
  "type": "handoff",
  "from": "designer",
  "to": "critic",
  "candidate_id": "L42-3",
  "smiles": "OC(=O)[C@H]1N2C(=O)...",
  "score_panel": {"mic_ug_ml": 0.4, "composite": 0.78, "weakest": "novelty"},
  "design_rationale": "5GC anchor with extended thiopyridyl tail",
  "specific_concerns": ["novelty Tanimoto 0.62 vs ceftaroline"],
  "ask": "verify cross-resistance to vancomycin via novelty + escape panels",
  "timestamp_ms": 1714824930000
}
```

## Critic → Designer (verdict CONDITIONAL)

```json
{
  "type": "handoff",
  "from": "critic",
  "to": "designer",
  "candidate_id": "L42-3",
  "verdict": "CONDITIONAL",
  "per_dim_scores": {
    "chemistry": "PASS",
    "drug_likeness": "PASS",
    "PAINS": "PASS",
    "novelty": "WARN",
    "escape": "WARN",
    "manufacturability": "PASS",
    "clinical": "PASS",
    "cross_resistance": "PASS"
  },
  "required_revisions": [
    {"dim": "novelty", "action": "scaffold_hop on heteroaryl tail to reduce Tanimoto < 0.5"},
    {"dim": "escape", "action": "widen pocket interactions to evade mecA-N146K"}
  ]
}
```

## Critic → Strategist (verdict PASS)

```json
{
  "type": "handoff",
  "from": "critic",
  "to": "strategist",
  "candidate_id": "L42-3",
  "verdict": "PASS",
  "all_dims_pass": true,
  "recommended_action": "advance_to_wet_lab",
  "summary": "All 8 review dimensions PASS. Composite 0.84, low escape risk, manufacturable at $480/g."
}
```

## Strategist → Designer (PIVOT decision)

```json
{
  "type": "handoff",
  "from": "strategist",
  "to": "designer",
  "action": "pivot_scaffold",
  "new_anchor": "oxadiazine-cephalosporin (away from current 5GC plateau)",
  "rationale": "5 iterations on 5GC scaffold without composite > 0.7. Time to switch class.",
  "compute_remaining_min": 12
}
```

## Error envelope (any agent)

```json
{
  "type": "error",
  "from": "<agent>",
  "error_code": "INVALID_SMILES | TOOL_TIMEOUT | LEDGER_LOCK | AMBIGUOUS_CONSTRAINT",
  "recovery": "retry | escalate | abort",
  "detail": "..."
}
```

## Validation

Every envelope is validated against a JSON schema before the recipient
processes it. Invalid envelopes return a structured rejection:

```json
{
  "type": "envelope_rejection",
  "reason": "missing_required_field",
  "field": "candidate_id",
  "received": {...}
}
```

## Routing

The message router (lightweight Python service) dispatches envelopes:
- `handoff` envelopes → recipient agent's inbox
- `error` envelopes → escalation chain (see error-escalation.md)
- `dispatch` envelopes → scoped sub-agent (see subagent-dispatch.md)
- `intervention` envelopes → all active agents (see intervention.md)
