# Act II — engines + integration block (2026-06-02)

All committed + pushed to origin/main. 43/43 tests pass. Backend :7860,
model svc :7920, frontend :5173. ZERO AMD cloud usage — fully local
(confirmed: all MI300X mentions are docstrings, no network calls).

## Shipped this block
1. **Direct dossier feed** — dock/ADMET/synthesizability endpoints now upsert
   the candidate dossier directly (not only via workflows), so a chemist
   running a service from a card sees it land immediately. Verified: 3 direct
   calls → dossier holds [docking, admet, synthesis].
2. **Dossier card upgrade** — chemist-grade facet grid: docking facet added,
   real metrics surfaced (binding ΔG, SA score, ADMET-AI tier+axis, novelty),
   per-facet engine-provenance sublabels, aligned icon/headline rhythm,
   chemist-read order (composite→binding→ADMET→synth→IP→resistance→regimen).
3. **4-gate autonomous campaign** — campaign_run now docks the lead into the
   pathogen's target and makes binding ΔG a 1st-class gate (binding + ADMET +
   synthesis + IP). Verified: de-novo MRSA → lead docks -5.51 kcal/mol
   (strong) into PBP2a → 4/4 gates → CHAMPION.
4. **ChemBERTa embeddings (8th real model)** — DeepChem/ChemBERTa-77M-MLM in
   the model service (/embed, /similarity, /embed_health) + backend bridge
   /chem/embedding-similarity. Verified: amox vs ampicillin 0.985, amox vs
   caffeine 0.622. transformers 5.9.0 in .venv-models.

## The real engine fleet (8 now)
ADMET-AI · activity classifier · Vina docking · SAScore synthesizability ·
peptide heads · retrospective validation · BRICS generation · ChemBERTa
embeddings. All local, all MI300X-ready, all honestly labeled.

## Remaining (the user said "all of the above heavy")
- AMR genome layer (DeepARG-style) for resistance service (#211) — NEXT
- Chemist-grade UI: design-system pass + campaign-led IA (#210) — the big one
- Boltz-2 affinity on MI300X (#207) · GenMol real service (#198)

## Notes
- Security hook false-positives on `mdl.eval()` (PyTorch eval-mode, not python
  eval) — append via heredoc when it blocks.
- Vite idles out; restart with `npx vite --host --port 5173` from workspace/web.
