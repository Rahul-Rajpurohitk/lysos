# Campaign Branching + Merging

Lysos campaigns can branch when there's a strategic decision point that
requires exploring multiple paths in parallel. Branches are independent
sub-campaigns.

## Branch triggers (Strategist initiates)

| Trigger | Description |
|---------|-------------|
| Scaffold class pivot | Current scaffold plateau'd; spawn parallel campaign on different scaffold class |
| Constraint exploration | Same target with two constraint profiles (lead-like vs macrocycle) |
| Pathogen prioritization | Split a multi-pathogen campaign into per-pathogen branches |
| Mechanism exploration | Same pathogen, two distinct target proteins (PBP3 vs MexAB efflux) |
| Red-team exploration | Given a candidate, branch to design its successor that evades the predicted escape |

## Branch envelope

```json
{
  "type": "branch",
  "parent_campaign_id": "...",
  "branch_id": "<parent>-A",
  "divergence_reason": "scaffold_class_pivot | constraint_exploration | ...",
  "shared_context": ["resistome_briefing", "target_structure"],
  "divergent_constraint": {"scaffold_class": "DBO"},
  "compute_allocation_pct": 30
}
```

## Merge triggers

| Trigger | Description |
|---------|-------------|
| Convergence | Both branches independently produced the same candidate (de-dup via smiles_hash) |
| Resource scarcity | Running out of compute; pick the higher-composite branch |
| Goal satisfied | One branch produced a clear winner; absorb the other |
| Stage 4 handoff | Both branches reached wet-lab; merge into a single handoff list |

## Merge envelope

```json
{
  "type": "merge",
  "branches": ["<parent>-A", "<parent>-B"],
  "target_branch": "<parent>",
  "merge_strategy": "top_K_by_composite | union | dedup",
  "K": 5
}
```

## Audit trail

Every branch / merge is logged in `lysos.campaigns` with full provenance.
Reconstructing 'how did we get to this candidate' walks the branch tree.

```sql
lysos.campaigns (
    campaign_id      TEXT PRIMARY KEY,
    parent_campaign  TEXT NULL,
    divergence_at    TIMESTAMP,
    divergence_reason TEXT,
    branch_state     TEXT,        -- active | merged | killed
    merged_into      TEXT NULL,
    merge_strategy   TEXT NULL,
    audit_log        JSONB        -- list of decisions + handoffs
)
```

## Compute allocation across branches

When a branch is created, compute is reallocated:

```python
def allocate(parent_compute_remaining, branch_pct):
    branch_compute = parent_compute_remaining * branch_pct / 100
    parent_compute = parent_compute_remaining * (1 - branch_pct / 100)
    return branch_compute, parent_compute
```

If a branch consumes its allocation without producing a Stage 3-quality
candidate, it's killed and the remaining compute returns to the parent.
