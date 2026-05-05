# Lysos artifact manifest

Generated: 2026-05-05 17:22:00
Total bytes: 373.6MB (391,720,193)

Everything in this tree is owned locally — independent of HF Hub or GitHub.
Heavy binaries are gitignored; this manifest tracks what's where.

| Category | Path | Size | Source | Note |
|----------|------|------|--------|------|
| embeddings | `embeddings/known-antibiotics-gemini-2.parquet` | 362.7MB | `artifacts/embeddings/known-antibiotics-gemini-2.parquet` | Gemini Embedding 2, 3072-d, RETRIEVAL_DOCUMENT, ~86 tok/row enriched |
| embeddings | `embeddings/known-antibiotics-gemini-2.meta.json` | 323.0B | `artifacts/embeddings/known-antibiotics-gemini-2.meta.json` | provenance JSON: source SHA, model, timestamp |
| embeddings | `embeddings/named-drugs-gemini-enrichment.parquet` | 266.1KB | `artifacts/embeddings/named-drugs-gemini-enrichment.parquet` | Gemini 2.5 Pro mechanism/spectrum/indication for top named drugs |
| cache | `caches/boltz2_poses_cache.parquet` | 117.5KB | `data/processed/boltz2_poses_cache.parquet` | 30K rows × 8 pathogens, Boltz-2 ipTM proxy |
| cache | `caches/aizynth_calibration_cache.parquet` | 36.7KB | `data/processed/aizynth_calibration_cache.parquet` | 1000 retrosynth routes, overnight USPTO sweep |
| cache | `caches/synth_calibration_cache.parquet` | 1.3MB | `data/processed/synth_calibration_cache.parquet` | SAscore baseline cache |
| cache | `caches/known-antibiotics-canonical.parquet` | 3.6MB | `data/processed/known-antibiotics-canonical.parquet` | 30K canonical antibiotics, deduped + InChI'd |
| cache | `caches/known-antibiotics.smiles` | 3.1MB | `data/processed/known-antibiotics.smiles` | raw SMILES file (39,750 rows) |
| cache | `caches/decoy-actives-pairs.parquet` | 370.1KB | `data/processed/decoy-actives-pairs.parquet` | DUD-E decoy pairs for hard-negative mining |
| cache | `caches/peptide-actives-canonical.parquet` | 1.5MB | `data/processed/peptide-actives-canonical.parquet` | AMP catalog (DBAASP/APD3/DRAMP) |
| predictor | `predictors/mic_predictor.joblib` | 420.4KB | `data/processed/mic_predictor.joblib` | MIC predictor — xgboost on Morgan FP, scaffold-CV MAE 0.62 |
| predictor | `predictors/hemolysis_predictor.joblib` | 180.1KB | `data/processed/hemolysis_predictor.joblib` | Hemolysis predictor — xgboost on 8K hemolysis dataset |
