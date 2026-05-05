# Confidence Reporting Convention

Every Lysos tool that emits a prediction also emits a confidence score in
[0, 1]. Agents must propagate these scores in their outputs and use them in
downstream decision-making.

## Tool-level confidence

| Tool | Confidence source |
|------|------------------|
| `predict_mic_pathogen` | XGBoost + scaffold-CV proximity |
| `predict_admet` | descriptor-domain coverage |
| `predict_hemolysis` | training-distribution match |
| `predict_binding_affinity` | energy-function decomposition |
| `predict_complex_structure` | ipTM (Boltz-2 native) |
| `estimate_synth_cost` | route-finder agreement |
| `predict_resistance_escape` | red_team_verdict mapped to [0.25, 0.5, 0.85] |

## Agent-level decision tiers

| Tier | Range | Action |
|------|-------|--------|
| Tier 1 | ≥ 0.80 | TRUST. Proceed without verification |
| Tier 2 | 0.60-0.80 | CAUTIOUS TRUST. One orthogonal verification required |
| Tier 3 | 0.40-0.60 | LOW TRUST. Two orthogonal verifications + flag for review |
| Tier 4 | < 0.40 | NO TRUST. Wet-lab only |

## Propagation

Composite confidence = geometric mean of per-pillar confidences:

```python
def composite_conf(per_pillar):
    """All pillar confidences must be in (0, 1]."""
    n = len(per_pillar)
    product = 1.0
    for c in per_pillar.values():
        product *= max(c, 0.001)  # avoid log(0)
    return product ** (1.0 / n)
```

Example:
- MIC conf 0.8
- ADMET conf 0.7
- hemolysis conf 0.85
- composite_conf = (0.8 × 0.7 × 0.85)^(1/3) ≈ 0.78 → Tier 2

## Output convention

Every numeric prediction comes with its confidence in the same JSON object:

```json
{
  "log_mic_predicted": -0.42,
  "mic_ug_ml": 0.38,
  "confidence": 0.78
}
```

Composite scores carry their propagated confidence:

```json
{
  "composite": 0.74,
  "confidence": 0.71,
  "weakest": "novelty",
  "weakest_conf": 0.55
}
```

## Agent-output format

When Designer reports a candidate, it includes confidence-aware hedges:

```
PROPOSAL: <SMILES>
EXPECTED MIC: 0.4 ± 0.2 µg/mL (confidence 0.78)
CAVEAT: hemolysis prediction is in Tier 2 confidence; recommend in vitro
confirmation before commit.
```

## Missing-confidence handling

If a tool returns no confidence field, Designer assumes 0.5 (low) and
downgrades the candidate accordingly.

## Evaluation tie-in

The `reasoning_faithfulness` eval metric specifically checks whether
confidence-tier downgrades are correctly applied when predictions are
uncertain. Models that always report Tier 1 regardless of evidence get
penalized.
