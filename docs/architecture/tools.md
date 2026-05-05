# Lysos Tool Registry

25 tools across 6 categories. Each tool has a typed input model, typed
output model, expected duration, and tags. Designer/Critic/Editor invoke
tools via structured tool_call envelopes; the router dispatches to the
appropriate backend (local Python, RDKit, ML predictor, ROCm-Boltz2 service).

## Full registry

| Category | Tool | Latency | Input | Output |
|----------|------|---------|-------|--------|
| amr | `predict_mic_pathogen` | 200ms | smiles, pathogen | log_mic_predicted, mic_ug_ml, confidence |
| amr | `get_pathogen_resistome` | 50ms | pathogen | resistome dict + first-line therapy |
| amr | `check_resistance_genes` | 100ms | pathogen, drug_class_or_smiles | relevant_genes list |
| amr | `predict_resistance_escape` | 300ms | smiles, pathogen | escape_mutations + red_team_verdict |
| amr | `find_active_against_mdr` | 150ms | pathogens | drug list with MIC ranges |
| scoring | `predict_admet` | 100ms | smiles | MW/logP/TPSA/Lipinski/F |
| scoring | `predict_hemolysis` | 200ms | smiles | safety_score + risk_class |
| scoring | `predict_synthesis_route` | 800ms | smiles | SA_score, steps, cost, route |
| scoring | `estimate_synth_cost` | 250ms | smiles | cost_class + USD/g estimate |
| scoring | `score_molecule` | 350ms | smiles, target_pathogen | composite + weakest pillar |
| scoring | `find_similar_drugs` | 400ms | query_smiles | matches with Tanimoto |
| structural | `dock_against_target` | 5000ms | smiles, pdb_id | poses + best_score |
| structural | `predict_binding_affinity` | 1500ms | smiles, target | delta_g, pkd_predicted |
| structural | `predict_complex_structure` | 8000ms | smiles, target_pdb_id | ipTM, pTM, ligand_RMSD (Boltz-2) |
| generative | `propose_pocket_aware` | 2000ms | target_pdb, pocket_class | candidate proposals |
| generative | `scaffold_hop` | 1500ms | smiles, n_proposals | bioisosteric alternatives |
| generative | `transform_structure` | 800ms | smiles, op | single-product transform |
| generative | `optimize_iteratively` | 6000ms | seed_smiles, objective, max_iters | optimization trajectory |
| knowledge | `compare_molecules` | 100ms | smiles_a, smiles_b | Tanimoto + delta-properties |
| knowledge | `explain_mechanism` | 200ms | smiles | inferred_class + MoA narrative |
| knowledge | `find_target_structure` | 500ms | pathogen | primary_target + PDB list |
| knowledge | `get_drug_history` | 150ms | drug_name | class, year, MoA, trials |
| knowledge | `search_literature` | 1500ms | query | papers + abstracts |
| sandbox | `execute_python` | 500ms | code | stdout, return_value |
| sandbox | `render_3d_scene` | 200ms | structure, ligand_smiles | 3D viz spec |

## Latency groups (orchestration planning)

- **CHEAP (≤300ms)**: all amr (except `predict_resistance_escape`) + most scoring + `compare_molecules` + `execute_python`
- **MEDIUM (300-2000ms)**: generative + structural-light + knowledge
- **EXPENSIVE (>2000ms)**: `predict_complex_structure` (Boltz-2), `dock_against_target` (Vina), `optimize_iteratively`

## Decision tree (when to use which)

| Question | Tool |
|----------|------|
| Activity vs a pathogen? | `predict_mic_pathogen` |
| ADMET stoplight? | `predict_admet` |
| 3D binding pose? | `predict_complex_structure` (Boltz-2) for review, `dock_against_target` (Vina) for triage |
| Scaffold variants? | `scaffold_hop` |
| Synthesis cost? | `predict_synthesis_route` |
| Novelty validation? | `find_similar_drugs` + `compare_molecules` |
| Resistance verdict? | `predict_resistance_escape` |
| Pathogen briefing? | `get_pathogen_resistome` |
| Find target structure? | `find_target_structure` |
| Drug clinical context? | `get_drug_history` |
| Recent literature? | `search_literature` |
| Custom math? | `execute_python` |

## Orchestration strategy

**Cheap tools first as gates; expensive tools only on survivors.**

Standard panel sequence:
1. `predict_mic_pathogen` (200ms) — primary activity gate
2. `predict_admet` (100ms) — Lipinski filter
3. `predict_hemolysis` (200ms) — safety
4. `score_molecule` (350ms) — composite
5. `predict_resistance_escape` (300ms) — red-team
6. `predict_synthesis_route` (800ms) — feasibility (only on survivors)
7. `predict_complex_structure` (8000ms) — 3D pose (only on top-1)

This pattern processes a 5-candidate batch in ~1-2 seconds for cheap stages,
escalating to ~10s only for the top survivor.
