# Act II — Scaling + Real Simulation Plan (2026-06-01)

> 40 days to submission. Backend audit: all 12 core endpoints HTTP 200.
> The breakage the user senses is FRONTEND integration + UI alignment, not
> the API. Strategy: (1) add real SIMULATION (the credibility leap), (2) fix
> the UI to chemist-grade, (3) keep folding in open-source models.

## What the research surfaced (real, open, integrable)

| Tool | License | Role in Lysos | Cost |
|---|---|---|---|
| **AutoDock Vina** | Apache-2.0, `pip install vina` + Python bindings | REAL molecular docking → binding ΔG into the target pocket. Turns the 3D theater from "place" into "dock + score". | CPU, seconds/pose |
| **Boltz-2** | MIT-ish open | SOTA structure + **binding affinity** (near-FEP). The headline simulation: does our candidate actually bind PBP2a/etc.? | GPU (MI300X!) |
| **AiZynthFinder** | open, Python, MCTS + template NN | REAL retrosynthesis → replaces Gemini-hallucinated routes in synthesis service. Purchasable-precursor backed. | CPU |
| **ChemBERTa / MoLFormer-XL** | HF, open | Pretrained molecular transformer embeddings → better property heads + similarity than Morgan FPs | GPU |
| **DiffDock-L** | open | ML docking (complements Vina) | GPU |
| **DeepARG / cAMRah** | open | AMR gene/resistance prediction from genome — deepens the resistance service | CPU |

The AMD angle writes itself: **Boltz-2 affinity + ChemBERTa embeddings on MI300X**
= real GPU simulation workload, not a wrapper.

## The 3 thrusts (40 days)

### Thrust A — REAL SIMULATION (the credibility leap, weeks 1-2)
1. **Docking service** (`chem_dock.py`): AutoDock Vina. Input candidate + target
   PDB → real docked pose + binding affinity (kcal/mol) + per-residue contacts.
   Replaces the current "place in pocket" heuristic with a real ΔG. Caches poses.
2. **Boltz-2 on MI300X** (Act II GPU story): affinity prediction service. The
   3D theater shows a REAL predicted binding affinity + confidence.
3. **3D theater rebuild**: render the actual docked pose (not a hand-placed
   mol), color by binding/clashing contacts from the real dock, show ΔG + the
   binding-site residues. This is the "open lab simulation" feel.

### Thrust B — UI / PRODUCTIZATION (chemist-grade, weeks 2-4)
The user: "fixated on molecule diagrams, info all unaligned, looks too bad."
1. **Design system pass**: tokens, consistent spacing/typography, aligned grids.
   Every card on the same rhythm. Kill the unaligned-info problem.
2. **Workbench IA rebuild**: a chemist works in a CAMPAIGN, not loose cards.
   Lead the workbench with the campaign board; cards become campaign facets.
3. **The "dossier" as the hero**: one candidate → its full developability
   picture (activity, ADMET, dock ΔG, synth route, IP, resistance) on ONE
   aligned page a chemist would actually circulate.
4. **Global card states**: skeleton/empty/error everywhere (useArtifact hook).

### Thrust C — SCALE THE SCIENCE (weeks 3-6)
1. **AiZynthFinder** real retrosynthesis → swap into synthesis service.
2. **ChemBERTa/MoLFormer embeddings** → better similarity + property heads.
3. **AMR genome layer** (DeepARG-style) → resistance service depth.
4. **MD-lite / conformer simulation** (RDKit ETKDG + MMFF) → 3D conformer
   ensembles, strain energy, the "chemistry simulation" feel without a HPC MD.
5. **Real MIC data** integration where licensing permits (SPARK/CO-ADD open AMR).

## Build order (start now)
1. ✅ research + plan (this doc)
2. **Docking service (AutoDock Vina)** — START HERE. Biggest credibility-per-day.
3. 3D theater consumes real docked poses + ΔG.
4. AiZynthFinder retrosynthesis swap.
5. ChemBERTa embedding service.
6. UI/design-system pass + campaign-led IA.

## Honesty rails (non-negotiable, judge-facing)
- Docking ΔG labeled as predicted, with the scoring function named.
- Boltz-2 affinity shown with its confidence.
- Every model's provenance badge stays.
- No fabricated units (the ADMET percentile lesson).
