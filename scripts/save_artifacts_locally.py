"""save_artifacts_locally.py — mirror everything we paid for to one tree.

You paid for:
  - Gemini Embedding 2 API calls (the embedding parquet)
  - Overnight CPU on AiZynth retrosynthesis sweep
  - Boltz-2 proxy calibration cache
  - SAscore / known-antibiotic curation
  - xgboost predictor training (MIC + hemolysis)
  - HF dataset push storage
  - Eventually: GPU hours producing the LoRA adapters

This script copies all of those to `artifacts/` so you own them on your
machine, independent of HF Hub / GitHub.

Layout:
  artifacts/
    MANIFEST.md              tracked in git — index + provenance
    embeddings/              Gemini-2 reference embeddings
    caches/                  reward-stack reusable caches
    predictors/              trained xgboost .joblib files
    datasets/                HF parquet snapshots (round-tripped)
    adapters/                LoRA + tokenizer per stage (post-training)
    reports/                 eval JSON + leaderboard HTML

Run:
  python3 scripts/save_artifacts_locally.py             # mirror everything
  python3 scripts/save_artifacts_locally.py --skip-adapters
  python3 scripts/save_artifacts_locally.py --skip-datasets
  python3 scripts/save_artifacts_locally.py --dry-run

Idempotent — re-running just refreshes any artifacts that have moved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"


def _sha16(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _copy(src: Path, dst: Path, dry: bool) -> tuple[bool, int, str]:
    """Copy src→dst if needed. Returns (changed, size_bytes, sha16)."""
    if not src.exists():
        return False, 0, ""
    size = src.stat().st_size
    sha = _sha16(src) if size < 200 * 1024 * 1024 else "(large, skip-hash)"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size == size:
        # Same-size + already there → assume up-to-date, save a copy
        return False, size, sha
    if dry:
        return True, size, sha
    shutil.copy2(src, dst)
    return True, size, sha


def _human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-embeddings", action="store_true")
    ap.add_argument("--skip-caches", action="store_true")
    ap.add_argument("--skip-predictors", action="store_true")
    ap.add_argument("--skip-datasets", action="store_true",
                    help="Skip HF dataset round-trip (saves ~1GB disk)")
    ap.add_argument("--skip-adapters", action="store_true")
    args = ap.parse_args()

    ART.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict] = []
    total_bytes = 0

    def record(category: str, src: Path, dst: Path, note: str = "") -> None:
        nonlocal total_bytes
        changed, size, sha = _copy(src, dst, args.dry_run)
        if size == 0 and not src.exists():
            print(f"  [skip] {src} not found")
            return
        total_bytes += size
        marker = "★" if changed else "·"
        rel_dst = dst.relative_to(ART) if dst.is_relative_to(ART) else dst
        print(f"  {marker} {category:12} {_human(size):>10}  {rel_dst}")
        manifest_rows.append({
            "category": category,
            "path": str(rel_dst),
            "src": str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else str(src),
            "size_bytes": size,
            "sha256_16": sha,
            "note": note,
        })

    # ── 1. Embeddings ──────────────────────────────────────────────────
    if not args.skip_embeddings:
        print("\n── embeddings (Gemini Embedding 2) ──")
        for fname, note in [
            ("known-antibiotics-gemini-2.parquet",
             "Gemini Embedding 2, 3072-d, RETRIEVAL_DOCUMENT, ~86 tok/row enriched"),
            ("known-antibiotics-gemini-2.meta.json",
             "provenance JSON: source SHA, model, timestamp"),
            ("named-drugs-gemini-enrichment.parquet",
             "Gemini 2.5 Pro mechanism/spectrum/indication for top named drugs"),
        ]:
            p = ROOT / "artifacts" / "embeddings" / fname
            if p.exists():
                record("embeddings", p, p, note)
        if not (ROOT / "artifacts/embeddings/known-antibiotics-gemini-2.parquet").exists():
            print("  [pending] run scripts/precompute_embeddings.py first")

    # ── 2. Reward-stack caches ─────────────────────────────────────────
    if not args.skip_caches:
        print("\n── reward caches (boltz / aizynth / synth / known-anti) ──")
        for name, src_rel, note in [
            ("boltz_proxy",   "data/processed/boltz2_poses_cache.parquet",
                              "30K rows × 8 pathogens, Boltz-2 ipTM proxy"),
            ("aizynth",       "data/processed/aizynth_calibration_cache.parquet",
                              "1000 retrosynth routes, overnight USPTO sweep"),
            ("synth_calib",   "data/processed/synth_calibration_cache.parquet",
                              "SAscore baseline cache"),
            ("known_anti",    "data/processed/known-antibiotics-canonical.parquet",
                              "30K canonical antibiotics, deduped + InChI'd"),
            ("known_anti_smi","data/processed/known-antibiotics.smiles",
                              "raw SMILES file (39,750 rows)"),
            ("decoy_pairs",   "data/processed/decoy-actives-pairs.parquet",
                              "DUD-E decoy pairs for hard-negative mining"),
            ("peptide_acts",  "data/processed/peptide-actives-canonical.parquet",
                              "AMP catalog (DBAASP/APD3/DRAMP)"),
        ]:
            record("cache", ROOT / src_rel, ART / "caches" / Path(src_rel).name, note)

    # ── 3. Trained reward predictors ───────────────────────────────────
    if not args.skip_predictors:
        print("\n── trained predictors (xgboost) ──")
        for src_rel, note in [
            ("data/processed/mic_predictor.joblib",
             "MIC predictor — xgboost on Morgan FP, scaffold-CV MAE 0.62"),
            ("data/processed/hemolysis_predictor.joblib",
             "Hemolysis predictor — xgboost on 8K hemolysis dataset"),
        ]:
            record("predictor", ROOT / src_rel,
                   ART / "predictors" / Path(src_rel).name, note)

    # ── 4. HF dataset snapshots (parquet round-trip) ───────────────────
    if not args.skip_datasets:
        print("\n── HF dataset snapshots ──")
        for ds_rel in [
            "data/processed/amr-stage2-pro-v12",
            "data/processed/amr-rl-prompts-v3",
            "data/processed/tdc-stage1",
        ]:
            src = ROOT / ds_rel
            if not src.exists():
                print(f"  [skip] {src} not on disk")
                continue
            dst = ART / "datasets" / src.name
            if not args.dry_run:
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            size = sum(p.stat().st_size for p in src.rglob("*") if p.is_file())
            total_bytes += size
            print(f"  ★ dataset      {_human(size):>10}  datasets/{src.name}/")
            manifest_rows.append({
                "category": "dataset",
                "path": f"datasets/{src.name}",
                "src": ds_rel,
                "size_bytes": size,
                "note": "HF arrow snapshot (load_from_disk-compatible)",
            })

    # ── 5. Trained adapters from HF (post-training) ────────────────────
    if not args.skip_adapters:
        print("\n── LoRA adapters (post-training) ──")
        try:
            from huggingface_hub import HfApi
            api = HfApi()
            for repo, stage in [
                ("rahul24raj/txgemma-4-31b",   "stage1"),
                ("rahul24raj/lysos-base",      "stage2"),
                ("rahul24raj/lysos-base-dpo",  "stage2.5"),
                ("rahul24raj/lysos-rl",        "stage3"),
            ]:
                try:
                    info = api.model_info(repo, files_metadata=True)
                except Exception as e:
                    print(f"  [skip] {repo}: {str(e)[:60]}")
                    continue
                if not info.siblings:
                    print(f"  [pending] {repo} (no files yet — training not done)")
                    continue
                # Don't auto-pull (could be 60+GB); just log presence
                size_b = sum(s.size or 0 for s in info.siblings)
                print(f"  ⊙ adapter      {_human(size_b):>10}  {repo}  ({stage}, on HF Hub)")
                manifest_rows.append({
                    "category": "adapter",
                    "path": f"adapters/{repo.split('/')[-1]}",
                    "src": repo + " (HF Hub)",
                    "size_bytes": size_b,
                    "note": f"{stage}; pull manually with "
                            f"`huggingface-cli download {repo} --local-dir artifacts/adapters/{repo.split('/')[-1]}`",
                })
        except ImportError:
            print("  [skip] huggingface_hub not in venv-cli")

    # ── 6. Manifest ────────────────────────────────────────────────────
    print(f"\n── total: {_human(total_bytes)} across {len(manifest_rows)} artifacts ──")

    if args.dry_run:
        print("(dry-run — nothing written)")
        return 0

    # Write MANIFEST.md (tracked in git)
    manifest_md = ART / "MANIFEST.md"
    lines = [
        "# Lysos artifact manifest",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Total bytes: {_human(total_bytes)} ({total_bytes:,})",
        "",
        "Everything in this tree is owned locally — independent of HF Hub or GitHub.",
        "Heavy binaries are gitignored; this manifest tracks what's where.",
        "",
        "| Category | Path | Size | Source | Note |",
        "|----------|------|------|--------|------|",
    ]
    for row in manifest_rows:
        lines.append(
            f"| {row['category']} | `{row['path']}` | {_human(row['size_bytes'])} "
            f"| `{row['src']}` | {row.get('note', '')} |"
        )
    manifest_md.write_text("\n".join(lines) + "\n")

    # Also write a JSON for tooling
    (ART / "manifest.json").write_text(json.dumps(manifest_rows, indent=2))

    print(f"\n[OK] {manifest_md}")
    print(f"[OK] {ART / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
