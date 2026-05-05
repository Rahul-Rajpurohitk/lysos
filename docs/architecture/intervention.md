# User Intervention Handler

Mid-campaign user interventions update the constraint state of all active
agents and are first-class events in the audit trail.

## Standard interventions

| Intervention | Effect |
|-------------|--------|
| `clamp_mw < 400` | All future proposals must satisfy MW < 400 |
| `ban_aromatic_amines` | Add to structural-alerts BLOCK list |
| `pin_pdb_target` | Lock to specific PDB id |
| `restrict_scaffold_class` | Filter for one or more scaffold types |
| `reduce_compute_budget` | Halve retry counts; suspend expensive tools |
| `add_pathogen` | Spawn parallel campaign for new pathogen |
| `set_novelty_floor` | Tighten Tanimoto threshold |
| `pin_anchor_scaffold` | Force Designer to use a specific anchor |

## Intervention envelope

```json
{
  "type": "intervention",
  "source": "user",
  "campaign_id": "<id>",
  "directive": "<intervention>",
  "params": { /* directive-specific */ },
  "target_agents": ["designer", "critic", "strategist"],
  "effective_at": "now | next_iteration",
  "timestamp": "..."
}
```

## Processing flow

1. Append to `lysos.interventions` table with timestamp + agent context
2. Broadcast to all active agents via the message bus
3. Each agent updates its constraint state
4. Designer pauses current iteration; Strategist evaluates impact
5. Compliance check runs over existing candidates
6. Non-compliant candidates flagged for revision or kill
7. Designer resumes from previous state with new constraints

## Compliance check on existing candidates

```sql
SELECT *
FROM lysos.candidates
WHERE campaign_id = $current
  AND strategist_status NOT IN ('killed', 'wet_lab')
```

For each candidate, run the new constraint over its panel data. Mark
non-compliant candidates as `intervention_violation`. Strategist decides:
revise (Designer applies fix) or kill.

## Replay semantics

After intervention is applied:
- Designer resumes from the previous state with the new constraints in effect
- Tool results from the previous state are preserved in the ledger so the
  campaign doesn't restart from scratch
- The new constraint is logged in `designer_state.applied_interventions`
  for audit

## Audit trail

```sql
lysos.interventions (
    intervention_id  TEXT PRIMARY KEY,
    campaign_id      TEXT,
    source           TEXT,           -- user | strategist | system
    directive        TEXT,
    params           JSONB,
    applied_at       TIMESTAMP,
    affected_candidates INT,         -- count of compliance violations
    resolution       TEXT            -- continued | revised | killed
)
```
