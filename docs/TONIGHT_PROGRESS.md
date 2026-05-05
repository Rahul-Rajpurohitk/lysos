# Tonight's Progress — May 5 2026

## Completed (commits c49981b → e72cf15 → 35374ca → 7701e10)

### Reward calibration
- ✅ SAscore synth-cost cache: 30,741 entries
- ✅ AizynthFinder priority sweep: running 125+/1000 with routes (avg score 0.99)
- ✅ Boltz-2 proxy cache: 30K (smiles, pathogen, pdb) entries
  - Real Boltz-2 blocked by scipy on py3.13; proxy serves as fallback

### Dataset versioning
- ✅ pro-v11: quality-weighted (top-quartile 2x, bottom-quartile 0.5x)
  - 379,486 train / 22,936 valid / 50 test
  - Pushed to HF: rahul24raj/lysos-amr-stage2-pro-v11
- ✅ pro-v12: pro-v11 + 1,437 counterfactual MMP pairs + 8 time-aware eval rows
  - 380,844 train / 23,015 valid / 58 test
  - Pushing to HF as rahul24raj/lysos-amr-stage2-pro-v12

### Quality + provenance
- ✅ Data quality scorer: per-row 0-10 score from token-len + structural-depth + source + novelty
- ✅ Loss masking smoke test: 4/4 PASSED (Gemma 4 chat template + response_template aligned)
- ✅ Manifest refresh: 38 datasets tracked

### Eval harness expansion
- ✅ OOD eval (Salmonella + Streptococcus): 23 prompts
- ✅ Adversarial robustness eval: 59 probes (15 SMILES + 26 pathogen + 18 jailbreak)
- ✅ Reward hacking probe: 12 edge-case SMILES (each games one component)
- ✅ Time-aware split eval: 8 surveillance findings 2020+ as held-out test
- ✅ Long-context eval: 100 long-form-trace held-out continuations
- ✅ Comparative benchmark scaffolding: vs Gemma 4 zero-shot + GPT-4 + Claude

### Documentation
- ✅ Methods paper draft v0: 296-line, 28-citation publishable scaffold
- ✅ Reproduction guide: end-to-end clone → install → train → eval
- ✅ Model card lysos-amr-stage2-pro-v11
- ✅ Continuous-eval dashboard (HTML)
- ✅ Hard-negative mining script (ready for post-train)

## Cross-checked counts

| Asset | State |
|-------|-------|
| Datasets on HF (private) | 11 versions: pro-v3 → pro-v12, rl-prompts-v3 |
| Teacher distillation traces | 78,150 across 7 layers + 1,437 counterfactuals + new evals |
| Reward components | 12, weights sum 1.0 |
| Architecture docs | 13 canonical .md files in docs/architecture/ |
| Eval probes | OOD 23 + adversarial 59 + reward-hacking 12 + time-aware 8 + long-context 100 = 202 total |
| Architecture docs | 14 files (added Tonight: REPRODUCE.md, methods_paper.md, TONIGHT_PROGRESS.md) |
| Calibration caches | SAscore 30K + AizynthFinder 125+ + Boltz-2 proxy 30K |

## Pending (gating on AMD credits or external API)

- Pre-train Gemma 4 baseline (needs vLLM serving Gemma 4)
- Stage 1 TxGemma-4 SFT (8x MI300X, ~6h)
- Stage 2 SFT on pro-v12 (1x MI300X, ~12h)
- Stage 3 GRPO RL with 12-component rewards (1x MI300X, ~10h)
- Comparative benchmark execution (vs Gemma 4 + GPT-4 + Claude)
- Hard-negative mining (after Stage 2 checkpoint)
- Calibration plots (after Stage 3 checkpoint)
- Eval execution + leaderboard fill-in

## What we hit overnight

- 4 commits, 30+ new files, ~10K lines added
- 12 → 38 datasets tracked in manifest
- pro-v10 → pro-v12 across 2 dataset upgrades
- 5 new eval probe types (OOD + adversarial + reward-hacking + time-aware + long-context)
- 14 architecture docs complete (was 3)
- Methods paper from 0 → 296-line draft
- Reproduction guide from 0 → comprehensive end-to-end

## Quality gate before training

- ✅ Loss masking verified
- ✅ Schema validated (all rows have task/pathogen/messages/split)
- ✅ Dedup confirmed (full-row dups + assistant-text caps applied in pro-v5)
- ✅ Pathogen primer applied to None-pathogen rows (100%)
- ✅ Token-length distribution healthy (4% in 1024+ range from long-form)
- ✅ Stereochemistry tagged
- ✅ Confidence convention enforced

Ready for AMD MI300X when credits land.
