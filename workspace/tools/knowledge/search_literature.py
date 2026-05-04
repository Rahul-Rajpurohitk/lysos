"""Search PubMed via E-utilities for relevant literature.

Used by the Designer agent at session start (e.g. "what's known about
AMR drug design for {pathogen}?") and by the Critic for citation grounding.
Pre-MI300X uses live PubMed; on MI300X swap to a cached embedding index.
"""
from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from typing import Optional

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.knowledge.search_literature")

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class LitSearchInput(BaseModel):
    query: str = Field(..., description="PubMed query string")
    year_min: Optional[int] = Field(None, description="Earliest publication year")
    year_max: Optional[int] = Field(None, description="Latest publication year")
    max_results: int = Field(8, ge=1, le=30)


class Paper(BaseModel):
    pmid: str
    title: str
    year: Optional[int] = None
    journal: Optional[str] = None
    authors: list[str] = []


class LitSearchOutput(BaseModel):
    query: str
    papers: list[Paper]
    backend: str
    interpretation: str


def _esearch(query: str, max_results: int) -> list[str]:
    url = f"{EUTILS_BASE}/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": str(max_results),
        "retmode": "json",
    }
    full = url + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(full, timeout=4.0) as r:
            import json as _j
            j = _j.loads(r.read().decode())
            return j.get("esearchresult", {}).get("idlist", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("esearch failed: %s", exc)
        return []


def _esummary(pmids: list[str]) -> list[Paper]:
    if not pmids:
        return []
    url = f"{EUTILS_BASE}/esummary.fcgi"
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
    full = url + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(full, timeout=4.0) as r:
            import json as _j
            j = _j.loads(r.read().decode())
        result = j.get("result", {})
        out: list[Paper] = []
        for pmid in pmids:
            entry = result.get(pmid, {})
            year = None
            try:
                year = int((entry.get("pubdate") or "")[:4])
            except Exception:
                pass
            out.append(Paper(
                pmid=pmid,
                title=entry.get("title", "?"),
                year=year,
                journal=entry.get("source"),
                authors=[a.get("name") for a in entry.get("authors", [])][:5],
            ))
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("esummary failed: %s", exc)
        return []


@tool(
    description=(
        "Search PubMed for relevant literature via E-utilities. Returns "
        "papers with PMID, title, journal, year, and top authors."
    ),
    category="knowledge",
    input_model=LitSearchInput,
    output_model=LitSearchOutput,
    expected_duration_ms=3000,
    tags=("knowledge", "rag", "pubmed"),
)
def search_literature(
    query: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    max_results: int = 8,
) -> LitSearchOutput:
    refined = query
    if year_min and year_max:
        refined += f" AND {year_min}:{year_max}[dp]"
    elif year_min:
        refined += f" AND {year_min}:3000[dp]"

    pmids = _esearch(refined, max_results)
    papers = _esummary(pmids)

    if papers:
        interp = f"Found {len(papers)} papers on PubMed for '{query}'. Top: {papers[0].title[:80]}."
    else:
        interp = f"No PubMed results for '{query}'. Try broadening the query."

    return LitSearchOutput(
        query=query,
        papers=papers,
        backend="pubmed_eutils",
        interpretation=interp,
    )
