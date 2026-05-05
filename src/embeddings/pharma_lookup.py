"""pharma_lookup.py — clinical pharmacology lookup for named antibiotics.

Loads `artifacts/embeddings/named-drugs-gemini-enrichment.parquet` (produced
by `scripts/enrich_named_drugs_with_gemini.py` via Gemini 2.5 Pro) and
exposes a fast in-memory lookup by drug name.

Why this is *not* in `enrichment.py`:
  `enrichment.py` defines the embedding text used to compute the 3072-d
  Gemini Embedding 2 vectors for the 30K reference catalog. That parquet
  is already computed and frozen — changing the template would invalidate
  the cosine space.

  This module is for *downstream* consumers — Stage-2 SFT data builders,
  evaluation harnesses, agentic tool calls — that want to inject
  pharmacology grounding text into LLM prompts. It does not affect the
  embedding space.

Output schema (from the parquet):
  name, smiles, mechanism, spectrum, indications, resistance_escape,
  thinking (full reasoning trace ~2000 chars/row — gold for SFT),
  raw_response, tokens_in, tokens_out, tokens_think, finish_reason

Usage:
    from src.embeddings.pharma_lookup import lookup, format_card

    info = lookup("amoxicillin")
    if info:
        print(format_card(info))
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Mapping

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARQUET = ROOT / "artifacts/embeddings/named-drugs-gemini-enrichment.parquet"

_CACHE: dict[str, dict[str, str]] = {}
_LOCK = threading.Lock()
_LOADED = False
_LOADED_FROM: Path | None = None


def _normalize(name: str) -> str:
    return (name or "").strip().lower()


def _load(parquet: Path) -> None:
    """Load the enrichment parquet into the in-memory cache (idempotent)."""
    global _LOADED, _LOADED_FROM
    with _LOCK:
        if _LOADED and _LOADED_FROM == parquet:
            return
        if not parquet.exists():
            log.info("pharma_lookup: %s does not exist; lookup will return None.",
                     parquet)
            _LOADED = True
            _LOADED_FROM = parquet
            return
        try:
            import pandas as pd
            df = pd.read_parquet(parquet)
        except Exception as exc:  # noqa: BLE001
            log.warning("pharma_lookup: could not read %s: %s", parquet, exc)
            _LOADED = True
            _LOADED_FROM = parquet
            return

        cache: dict[str, dict[str, str]] = {}
        has_thinking = "thinking" in df.columns
        for _, row in df.iterrows():
            mech = str(row.get("mechanism") or "")
            if not mech:
                continue  # skip empty rows (failed enrichments)
            entry = {
                "name": str(row.get("name", "")),
                "smiles": str(row.get("smiles", "")),
                "mechanism": mech,
                "spectrum": str(row.get("spectrum") or ""),
                "indications": str(row.get("indications") or ""),
                "resistance_escape": str(row.get("resistance_escape") or ""),
            }
            if has_thinking:
                entry["thinking"] = str(row.get("thinking") or "")
            cache[_normalize(entry["name"])] = entry
        _CACHE.clear()
        _CACHE.update(cache)
        _LOADED = True
        _LOADED_FROM = parquet
        log.info("pharma_lookup: loaded %d enriched drugs from %s",
                 len(cache), parquet.name)


def lookup(name: str, *, parquet: Path = DEFAULT_PARQUET) -> dict[str, str] | None:
    """Return the pharmacology card for `name`, or None if not enriched.

    Case-insensitive on the drug name. Returns a dict with keys:
      name, smiles, mechanism, spectrum, indications, resistance_escape.
    """
    _load(parquet)
    return _CACHE.get(_normalize(name))


def lookup_many(names: list[str], *,
                parquet: Path = DEFAULT_PARQUET) -> dict[str, dict[str, str]]:
    """Bulk lookup. Returns {name: card} for whichever names are enriched."""
    _load(parquet)
    out: dict[str, dict[str, str]] = {}
    for n in names:
        card = _CACHE.get(_normalize(n))
        if card is not None:
            out[n] = card
    return out


def format_card(card: Mapping[str, Any], *, max_chars: int = 600) -> str:
    """Render a compact one-paragraph briefing suitable for LLM prompt context."""
    parts = []
    name = card.get("name", "drug")
    if mech := card.get("mechanism"):
        parts.append(f"{name} — mechanism: {mech}")
    if spec := card.get("spectrum"):
        parts.append(f"Spectrum: {spec}")
    if ind := card.get("indications"):
        parts.append(f"Indications: {ind}")
    if res := card.get("resistance_escape"):
        parts.append(f"Resistance escape: {res}")
    text = " ".join(parts)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def all_drugs(*, parquet: Path = DEFAULT_PARQUET) -> list[str]:
    """Return canonical drug names that have enrichment data."""
    _load(parquet)
    return sorted(c["name"] for c in _CACHE.values())


def stats(*, parquet: Path = DEFAULT_PARQUET) -> dict[str, int]:
    """Return summary metrics after loading."""
    _load(parquet)
    n_with_thinking = sum(1 for c in _CACHE.values() if c.get("thinking"))
    total_thinking_chars = sum(len(c.get("thinking", "")) for c in _CACHE.values())
    return {
        "n_drugs": len(_CACHE),
        "n_with_thinking": n_with_thinking,
        "total_thinking_chars": total_thinking_chars,
    }


def get_thinking(name: str, *, parquet: Path = DEFAULT_PARQUET) -> str | None:
    """Return the full reasoning trace for `name`, or None if not enriched.

    Trace is ~2000 chars of step-by-step pharmacology thinking — useful
    as gold-standard reasoning for Stage-2 SFT data builders that want
    chain-of-thought training targets.
    """
    card = lookup(name, parquet=parquet)
    if not card:
        return None
    t = card.get("thinking")
    return t if t else None


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "amoxicillin"
    s = stats()
    print(f"loaded {s['n_drugs']} drugs from {_LOADED_FROM}")
    card = lookup(name)
    if card:
        print()
        print(format_card(card))
    else:
        print(f"\n[no enrichment for {name!r}]")
        print(f"available: {', '.join(all_drugs()[:20])}…")
