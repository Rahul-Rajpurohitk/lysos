# Open-Source Chemistry/Bio Stack — integration candidates (researched 2026-06-01)

Vetted from web + HF + X research. Each row: what it is, license, how it
plugs into Lysos, compute. Priority = build order for the 40-day window.

## SIMULATION (the credibility leap — Thrust A)

### AutoDock Vina — real molecular docking  ★ PRIORITY 1
- `pip install vina` (1.2.7), Apache-2.0, Python bindings, CPU, seconds/pose.
- Needs PDBQT receptor + ligand prep (Meeko for ligands; receptor from PDB).
- Lysos: `chem_dock.py` — candidate + target PDB → docked pose + binding ΔG
  (kcal/mol) + per-residue contacts. REPLACES the heuristic "place-in-pocket"
  with a real score. The 3D theater renders the real docked pose.
- Risk: macOS-ARM wheel can be finicky → ship with an RDKit shape/score
  fallback, label which engine ran. On MI300X Linux it installs clean.
- Refs: vina.scripps.edu, github.com/ccsb-scripps/AutoDock-Vina

### Boltz-2 — structure + binding AFFINITY (near-FEP)  ★ PRIORITY 2 (MI300X)
- Open license (Jun 2025, MIT). GPU. The AMD GPU story: real affinity
  workload on MI300X. First open model approaching FEP accuracy on
  small-molecule–protein affinity.
- Lysos: affinity service — candidate + target → predicted binding affinity
  + confidence. The 3D theater + dossier show a REAL affinity number.
- Refs: biorxiv 2025.06.14.659707, jeremywohlwend.com/assets/boltz2.pdf

### DiffDock-L — ML docking (complements Vina)
- Open, GPU. Corso et al. 2024. Use as a second docking opinion.

## GENERATION + RETROSYNTHESIS (Thrust C)

### AiZynthFinder — real retrosynthesis  ★ PRIORITY 3
- Open, Python, MCTS + template-NN policy, purchasable-precursor backed,
  <1 min/molecule, CPU. Lysos already references aizynth_calibration_cache.parquet!
- Lysos: swap into chem_synthesis.py to REPLACE Gemini-hallucinated routes
  with real template-grounded ones. Gemini becomes the narrator, not the source.
- Refs: github AiZynthFinder, J Cheminformatics 2020

### ASKCOS — synthesis planning suite (heavier alternative)
- Open (arxiv 2501.01835). Tree Builder + condition rec + outcome prediction.
  Heavier than AiZynth; consider only if AiZynth insufficient.

### GenMol (NVIDIA) — discrete-diffusion de-novo (already in the plan)
- Our BRICS generator is the stand-in; GenMol on MI300X is the upgrade.

## REPRESENTATION / PROPERTY (Thrust C)

### ChemBERTa / MoLFormer-XL — molecular transformers  ★ PRIORITY 4
- HF, open. ChemBERTa: 77M PubChem SMILES. MoLFormer-XL: >1B ZINC+PubChem.
- Lysos: embedding service → better similarity (vs Morgan) + stronger
  property/activity heads. GPU (MI300X). HF ids: katielink/MoLFormer-XL,
  jonghyunlee/ChemBERT_ChEMBL_pretrained, DeepChem/ChemBERTa-77M-MLM.

## RESISTANCE / GENOME (Thrust C — deepen resistance service)

### DeepARG / cAMRah — AMR gene + resistance prediction
- Open, CPU. DeepARG precision >0.97. cAMRah (Jan 2026) = 6-tool consensus.
- Lysos: genome → resistance-gene layer feeding the resistance-escape map.

### Open AMR datasets
- CO-ADD / SPARK (open antibacterial screening) — real MIC data where
  licensing permits → upgrade validation from similarity to measured activity.

## Notable AI-agent drug systems (positioning context, not integration)
- FutureHouse **Robin** (200x research speedup), DeepMind **Co-Scientist**
  (drug repurposing in hours). OpenBind released first open AI-ready
  drug-discovery dataset (2026). "Open source floats all boats" is the
  zeitgeist — our MIT + open-model stack is on-thesis.

## Build order (next blocks)
1. AutoDock Vina docking service + 3D theater rebuild (real poses + ΔG)
2. Boltz-2 affinity on MI300X
3. AiZynthFinder retrosynthesis swap
4. ChemBERTa embedding service
5. UI/design-system pass (chemist-grade alignment)
6. AMR genome layer
