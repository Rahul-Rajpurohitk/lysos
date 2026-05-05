# Sprint Workflow

Lysos sprints are 2-week design + eval cycles producing a discrete
deliverable (new dataset version, reward-stack change, model checkpoint,
eval result).

## Sprint structure

| Day | Phase |
|-----|-------|
| 1 | Sprint planning meeting (decide deliverables, allocate compute) |
| 2-3 | Data prep (CPU work) |
| 4-9 | Training + iteration (GPU work) |
| 10-12 | Eval + analysis |
| 13-14 | Retrospective + write-up |

## Planning artifacts

- `vault/plans/active/YYYY-MM-DD-<topic>.md` (Obsidian-tracked)
  - Sprint goals
  - Design decisions
  - Tool choices
  - Success criteria
- `vault/implementation-logs/YYYY-MM-DD-session-log.md`
  - Live log of every session, every commit, every decision
- `vault/plans/completed/<topic>.md` after sprint ends
  - Retrospective
  - What worked, what didn't
  - Lessons for next sprint

## Sprint types + deliverables

| Type | Deliverable |
|------|-------------|
| DATA | new dataset version (pro-vN+1) + smoke tests + push to HF |
| REWARD | new reward components + calibration sweeps + config update |
| TRAIN | new model checkpoint + eval baseline + comparison to prior |
| EVAL | new eval metric + locked config + leaderboard update |
| DEPLOY | new vLLM container + Workbench wire-up + HF Space update |
| INFRA | tool registry update + agent role refinement |

## Go/no-go criteria

At day 10 (eval phase start), the sprint either:
- **Advances to write-up** (deliverable hits its success criterion), OR
- **Rolls back and re-plans** (failure → retrospective explaining why)

## Continuous commits

- Every meaningful unit of work gets committed + pushed to GitHub
- No batched commits
- NO `Co-Authored-By` attribution (per project standing rule)

## Memory discipline

- Plans are NEVER deleted (persistent context)
- Session logs append-only
- Retrospectives capture what was tried and what worked
- Distillation traces, when changed, must be regenerated to match new
  architecture docs

## Parallel sprint tracks

Multiple sprints can run in parallel:
- DATA sprint preparing pro-vN+1 while...
- TRAIN sprint training pro-vN+0 to base
- EVAL sprint scoring pro-vN-1 results

Coordination via the campaign manifest + shared compute pool.

## Standup pattern (daily)

- What I did yesterday
- What I'm doing today
- Blockers
- Distillation gaps spotted
- Eval-metric movement

Logged in `vault/implementation-logs/<day>.md`.
