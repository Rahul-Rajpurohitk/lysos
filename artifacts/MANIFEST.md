# Lysos artifact manifest

Generated: 2026-05-05 15:46:17
Total bytes: 1.2GB (1,315,162,732)

Everything in this tree is owned locally — independent of HF Hub or GitHub.
Heavy binaries are gitignored; this manifest tracks what's where.

| Category | Path | Size | Source | Note |
|----------|------|------|--------|------|
| embeddings | `embeddings/known-antibiotics-gemini-2.parquet` | 362.7MB | `artifacts/embeddings/known-antibiotics-gemini-2.parquet` | Gemini Embedding 2, 3072-d, RETRIEVAL_DOCUMENT, ~86 tok/row enriched |
| embeddings | `embeddings/known-antibiotics-gemini-2.meta.json` | 323.0B | `artifacts/embeddings/known-antibiotics-gemini-2.meta.json` | provenance JSON: source SHA, model, timestamp |
| cache | `caches/boltz2_poses_cache.parquet` | 117.5KB | `data/processed/boltz2_poses_cache.parquet` | 30K rows × 8 pathogens, Boltz-2 ipTM proxy |
| cache | `caches/aizynth_calibration_cache.parquet` | 36.7KB | `data/processed/aizynth_calibration_cache.parquet` | 1000 retrosynth routes, overnight USPTO sweep |
| cache | `caches/synth_calibration_cache.parquet` | 1.3MB | `data/processed/synth_calibration_cache.parquet` | SAscore baseline cache |
| cache | `caches/known-antibiotics-canonical.parquet` | 3.6MB | `data/processed/known-antibiotics-canonical.parquet` | 30K canonical antibiotics, deduped + InChI'd |
| cache | `caches/known-antibiotics.smiles` | 3.1MB | `data/processed/known-antibiotics.smiles` | raw SMILES file (39,750 rows) |
| cache | `caches/decoy-actives-pairs.parquet` | 370.1KB | `data/processed/decoy-actives-pairs.parquet` | DUD-E decoy pairs for hard-negative mining |
| cache | `caches/peptide-actives-canonical.parquet` | 1.5MB | `data/processed/peptide-actives-canonical.parquet` | AMP catalog (DBAASP/APD3/DRAMP) |
| predictor | `predictors/mic_predictor.joblib` | 420.4KB | `data/processed/mic_predictor.joblib` | MIC predictor — xgboost on Morgan FP, scaffold-CV MAE 0.62 |
| predictor | `predictors/hemolysis_predictor.joblib` | 180.1KB | `data/processed/hemolysis_predictor.joblib` | Hemolysis predictor — xgboost on 8K hemolysis dataset |
| dataset | `datasets/amr-stage2-pro-v12` | 660.6MB | `data/processed/amr-stage2-pro-v12` | HF arrow snapshot (load_from_disk-compatible) |
| dataset | `datasets/amr-rl-prompts-v3` | 32.0MB | `data/processed/amr-rl-prompts-v3` | HF arrow snapshot (load_from_disk-compatible) |
| dataset | `datasets/tdc-stage1` | 188.3MB | `data/processed/tdc-stage1` | HF arrow snapshot (load_from_disk-compatible) |
