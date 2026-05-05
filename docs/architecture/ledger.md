# Candidate Ledger

The candidate ledger is the single source of truth for the campaign state.
Designer APPENDS new entries; Critic UPDATES verdicts; Strategist UPDATES
strategist_status (advance / kill).

## Schema (Postgres `lysos.candidates`)

```sql
candidate_id          TEXT PRIMARY KEY  -- L42-3 (campaign 42, candidate 3)
campaign_id           TEXT
iteration             INT
parent_candidate_id   TEXT NULL          -- if scaffold-hopped from another
smiles                TEXT NOT NULL      -- canonical SMILES
smiles_hash           TEXT               -- InChI key for dedup (UNIQUE per campaign)
pathogen              TEXT NOT NULL
target_protein        TEXT               -- e.g. PBP2a
target_pdb            TEXT               -- e.g. 1VQQ
scaffold_class        TEXT               -- e.g. '5GC ceftaroline-class'
designer_rationale    TEXT               -- Designer's structural reasoning
panel_scores          JSONB              -- { mic_ug_ml, admet, hemolysis, composite }
panel_confidence      JSONB              -- { tool_name: confidence_score }
critic_verdict        TEXT               -- PASS | CONDITIONAL | BLOCKED | NULL
critic_findings       JSONB              -- per-dimension findings
strategist_status     TEXT               -- proposed | review | approved | killed | wet_lab
resistance_verdict    TEXT               -- low-risk | moderate-risk | high-risk
synth_cost_per_g      INT                -- USD
synth_steps           INT
novelty_tanimoto      REAL               -- vs known-corpus index
created_at            TIMESTAMP
updated_at            TIMESTAMP
```

## Standard read patterns

### Latest candidates in current iteration
```sql
SELECT *
FROM lysos.candidates
WHERE campaign_id = $1
  AND iteration = (SELECT MAX(iteration) FROM lysos.candidates WHERE campaign_id = $1)
ORDER BY (panel_scores->>'composite')::float DESC
LIMIT 5;
```

### All BLOCKED candidates (for KILL decision)
```sql
SELECT *
FROM lysos.candidates
WHERE campaign_id = $1 AND critic_verdict = 'BLOCKED';
```

### Top wet-lab candidates
```sql
SELECT *
FROM lysos.candidates
WHERE strategist_status = 'wet_lab'
ORDER BY (panel_scores->>'composite')::float DESC;
```

## Write patterns

| Agent | Operation | Fields touched |
|-------|-----------|----------------|
| Designer | INSERT | candidate_id, smiles, scaffold_class, designer_rationale, panel_scores, panel_confidence; sets strategist_status='proposed' |
| Critic | UPDATE | critic_verdict, critic_findings |
| Strategist | UPDATE | strategist_status (advance / kill / wet_lab) |
| Editor | UPDATE | smiles (after canonicalization) |

## Deduplication

The `smiles_hash` column has a UNIQUE constraint per campaign. If Designer
tries to insert a candidate whose InChI key already exists, the insert fails
— Designer must scaffold-hop or proceed with the existing candidate.

## Auditability

The ledger is append-mostly:
- Killed candidates are kept (with `strategist_status = 'killed'`) for audit trail
- All updates are logged in `lysos.candidates_audit` with timestamps + agent
- Reconstructing 'how did we get to this candidate' walks `parent_candidate_id` back to root

## Integration with manifest

Ledger schema version is recorded in `data/processed/MANIFEST.json` so
training data + ledger format stay aligned. When schema changes, both
distillation traces and runtime code must be updated.
