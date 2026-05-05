# Stage Gates

Lysos has 4 candidate stages with explicit advancement gates. A candidate
cannot skip stages.

## Stage 1: Initial Proposal

**Entry**: Designer has proposed the SMILES with structural rationale

**Required**:
- SMILES is RDKit-parseable (Editor verified)
- Initial scaffold class identified
- Ledger entry created

**Gate to Stage 2**: SMILES is valid AND scaffold class is in the supported list

## Stage 2: In Silico Panel

**Entry**: All cheap tools called

**Required**:
- `predict_mic_pathogen` returned
- `predict_admet` returned
- `predict_hemolysis` returned
- `score_molecule` returned (composite computed)
- Confidence ≥ 0.5 on activity prediction

**Gate to Stage 3** (ALL must hold):
- composite ≥ 0.65
- mic_ug_ml ≤ 4 (active range)
- hemolysis risk ≤ medium
- lipinski_violations ≤ 2
- confidence ≥ 0.6

## Stage 3: Critic Review + Red-Team

**Entry**: Stage 2 gate passed

**Required**:
- Critic has scored all 8 dimensions
- `predict_resistance_escape` returned a verdict
- `find_similar_drugs` ran for novelty check
- `predict_synthesis_route` ran for synth feasibility

**Gate to Stage 4** (ALL must hold):
- Critic verdict PASS (all 8 dimensions PASS) OR CONDITIONAL after revisions accepted
- resistance verdict ≤ moderate-risk
- novelty Tanimoto < 0.6 vs known corpus
- synthesis cost ≤ $2000/g GMP estimate

## Stage 4: Wet-Lab Handoff

**Entry**: Stage 3 gate passed

**Required**:
- Strategist has approved
- Handoff envelope emitted to medchem team
- Synthesis priority (P0/P1/P2) assigned
- Wet-lab MIC + cytotox ordered

**Gate to Clinical Candidate**: wet-lab MIC matches predicted ±2× AND cytotox cleared

## Fail paths

| Failure | Action |
|---------|--------|
| Stage 2 fails | Designer iterates (scaffold_hop) up to 5 times |
| 5 iterations without Stage 3 advancement | Strategist PIVOTs scaffold class |
| Stage 3 BLOCKED | Designer redesigns or KILL |
| Stage 4 wet-lab fails (MIC > 4× predicted) | Strategist re-evaluates the candidate's whole panel for systematic prediction error |

## Gate enforcement

All gates are checked programmatically at the appropriate transition:

```python
def can_advance_to_stage_3(candidate):
    panel = candidate.panel_scores
    return (
        panel["composite"] >= 0.65
        and panel["mic_ug_ml"] <= 4
        and panel["hemolysis_risk"] in ("low", "medium")
        and panel["lipinski_violations"] <= 2
        and panel["confidence"] >= 0.6
    )
```

Manual override (Strategist can advance a candidate that fails a gate) is
logged in the audit trail for compliance.
