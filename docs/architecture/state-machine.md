# Designer State Machine

Designer is a finite state machine with 11 states. State is persisted to the
ledger as `designer_state` column per campaign. On crash, Designer resumes
from the persisted state.

## States

| State | Description |
|-------|-------------|
| `IDLE` | Waiting for user / Strategist invocation |
| `ABSORBING_CONTEXT` | Fetching resistome briefing + target structure |
| `GENERATING` | Proposing candidate SMILES |
| `SCORING` | Panel calls (predict_mic + predict_admet + ...) |
| `ITERATING` | Applying scaffold_hop on weakest candidate |
| `HANDING_OFF_TO_CRITIC` | Emitting handoff envelope to Critic |
| `WAITING_ON_CRITIC` | Paused, awaiting Critic verdict |
| `ADDRESSING_REVISIONS` | Applying Critic's required revisions |
| `HANDING_OFF_TO_STRATEGIST` | Emitting handoff envelope (after Critic PASS) |
| `BLOCKED` | Error or BLOCKED verdict; awaiting recovery |
| `TERMINATED` | Campaign over (success or kill) |

## Transitions

```
IDLE → ABSORBING_CONTEXT       (Strategist 'start_campaign' or user 'design X against Y')
ABSORBING_CONTEXT → GENERATING (after get_pathogen_resistome + find_target_structure return)
GENERATING → SCORING           (after candidate batch proposed)
SCORING → ITERATING            (composite < 0.65, has compute remaining)
SCORING → HANDING_OFF_TO_CRITIC (composite ≥ 0.65, ready for review)
ITERATING → SCORING            (after scaffold_hop returns)
HANDING_OFF_TO_CRITIC → WAITING_ON_CRITIC (envelope sent)
WAITING_ON_CRITIC → ADDRESSING_REVISIONS  (verdict CONDITIONAL)
WAITING_ON_CRITIC → HANDING_OFF_TO_STRATEGIST (verdict PASS)
WAITING_ON_CRITIC → BLOCKED                 (verdict BLOCKED)
ADDRESSING_REVISIONS → SCORING (revisions applied)
BLOCKED → IDLE                 (Strategist resets the campaign)
HANDING_OFF_TO_STRATEGIST → TERMINATED (Strategist accepted handoff)
ANY_STATE → BLOCKED            (on tool error / timeout)
ANY_STATE → TERMINATED         (on Strategist KILL)
```

## Persistence

State + intermediate tool results are written to `lysos.designer_state` on
every transition. On process crash, Designer resumes from the last persisted
state without losing tool-call results from the previous state.

```sql
designer_state (
    campaign_id   TEXT PRIMARY KEY,
    state         TEXT NOT NULL,            -- one of the 11 states above
    last_tool_results JSONB,                -- recent tool returns
    iteration     INT,
    transition_at TIMESTAMP
)
```

## Critic + Strategist state

Critic and Strategist also have state machines but simpler:

**Critic**: `IDLE → REVIEWING → DELIBERATING → EMITTED_VERDICT → IDLE`

**Strategist**: `IDLE → REVIEWING_LEDGER → DECIDING → EMITTED_DECISION → IDLE`

These are tracked similarly per campaign.
