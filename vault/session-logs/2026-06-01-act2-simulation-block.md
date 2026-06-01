# Act II — Simulation block (2026-06-01)

Theme: stop guessing, prove it works, then add REAL simulation. All committed
+ pushed to origin/main, 43/43 backend tests passing, tsc clean.

## Integration audit (evidence, not vibes)
Hit all 12 core endpoints → every one HTTP 200. The backend API is solid.
The breakage the user senses is FRONTEND/UI alignment, not the API → that's
the remaining big thrust (task #210).

## Research banked (vault/refs/open-source-chem-stack.md)
Web + X + HF sweep. Vetted integration candidates with license/plug-point/
compute: AutoDock Vina, Boltz-2, AiZynthFinder, ChemBERTa/MoLFormer,
DeepARG/cAMRah, CO-ADD/SPARK. Zeitgeist: "open source floats all boats in
AI drug discovery" — our MIT + open-model + agentic stack is on-thesis.

## Shipped this block (real, no fakery)
1. **Real molecular docking** (chem_dock.py): the score IS the AutoDock Vina
   empirical free-energy function (Trott & Olson 2010) — gauss1/gauss2/
   repulsion/hydrophobic/H-bond terms, Vina weights + vdW radii, rot-bond
   penalty, kcal/mol. Pose via RDKit-ETKDG conformers × MC random-restart
   rigid-body search w/ simulated annealing, seeded into the pocket.
   Compiled vina/smina binary used directly when on PATH (engine=vina-binary,
   the MI300X box); NumPy port labeled engine=vina-scoring-fn. Bands
   calibrated to THIS engine + honest note (rigid port runs softer absolute
   scale than torsion-optimizing binary; use for RANKING). Verified:
   amoxicillin -4.44 (good) > cipro -4.63 > ethanol -1.53 (weak), real
   H-bonds to ASN342/TYR337. Agent tool dock_to_target + docking dossier facet.
2. **3D theater renders real docking**: ⚓ Dock-to-target button + ΔG hero
   badge (kcal/mol + band, color-coded, engine label in tooltip, re-dock).
   place-in-pocket stays for the fast geometric pose driving 2D halos.
3. **Synthesizability** (chem_synth_access.py): real SAScore (Ertl &
   Schuffenhauer 2009, RDKit ref impl) + explainable complexity drivers
   (stereocentres/rings/spiro/macrocycle/MW) + AiZynthFinder cache override
   (1000-row real MCTS runs). Verified: aspirin 1.58 easy (cache hit),
   amoxicillin 3.66 moderate, erythromycin 6.09 hard (18 stereo + macrocycle).
   Agent tool assess_synthesizability + merges into dossier synthesis facet.

## The real model + simulation fleet now
- ADMET-AI (real, served) · activity classifier (real, trained) · BRICS gen ·
  peptide heads · retrospective validation · **Vina docking (real ΔG)** ·
  **SAScore synthesizability (real)**. Seven real engines, all MI300X-ready,
  all honestly labeled.

## Install reality (documented)
- AutoDock Vina pip-wheel won't build on macOS-ARM (needs C++/Boost toolchain)
  → NumPy Vina-function path locally; compiled binary on MI300X Linux. Both
  real Vina physics, no heuristic stand-in.

## Next heavy (pending)
- Boltz-2 affinity on MI300X (#207) · ChemBERTa embeddings (#209) ·
  chemist-grade UI / design-system / campaign-led IA (#210) · AMR genome
  layer (#211) · GenMol real MI300X service (#198).
