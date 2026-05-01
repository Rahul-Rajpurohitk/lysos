"""PDB (RCSB Protein Data Bank) loader for AMR target structures.

We pull metadata for protein structures from organisms in our priority AMR set:
target name, organism, ligand SMILES (when present), classification. Used to
enrich training prompts with structure-aware context — "design molecule for
PDB structure 1ABC, the MRSA PBP2a..." or "what's the binding pocket of CRE
β-lactamase 4XYZ?"

We DON'T download the full PDB files (3D coordinates) — just metadata via the
RCSB REST + GraphQL APIs.

Site: https://www.rcsb.org/
APIs:
  - Search: https://search.rcsb.org/rcsbsearch/v2/query
  - Data:   https://data.rcsb.org/rest/v1/

Usage:

    python -m src.data.pdb --output data/raw/pdb_amr_targets.csv \\
        --max-per-pathogen 1000
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("pdb")

RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_DATA_URL = "https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
RCSB_GRAPHQL_URL = "https://data.rcsb.org/graphql"

AMR_TO_PDB_ORGANISMS: dict[str, list[str]] = {
    "MRSA": ["Staphylococcus aureus"],
    "Mtb": ["Mycobacterium tuberculosis"],
    "EColi-CRE": ["Escherichia coli"],
    "KpneuCRE": ["Klebsiella pneumoniae"],
    "Abaum": ["Acinetobacter baumannii"],
    "Paer": ["Pseudomonas aeruginosa"],
    "VRE": ["Enterococcus faecium", "Enterococcus faecalis"],
    "NGono": ["Neisseria gonorrhoeae"],
}


def _search_organism(organism: str, max_results: int = 1000) -> list[str]:
    """Use RCSB Search API to find PDB IDs whose source organism matches."""
    query = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "operator": "exact_match",
                "attribute": "rcsb_entity_source_organism.ncbi_scientific_name",
                "value": organism,
            },
        },
        "return_type": "entry",
        "request_options": {
            "paginate": {"start": 0, "rows": max_results},
            "results_content_type": ["experimental"],
            "scoring_strategy": "combined",
        },
    }
    try:
        r = requests.post(RCSB_SEARCH_URL, json=query, timeout=30, headers={
            "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
        })
        r.raise_for_status()
        result = r.json()
        return [hit["identifier"] for hit in result.get("result_set", [])]
    except (requests.RequestException, json.JSONDecodeError) as exc:
        log.warning("RCSB search failed for %s: %s", organism, exc)
        return []


def _batch_metadata(pdb_ids: list[str], batch: int = 50) -> dict[str, dict]:
    """GraphQL batch fetch metadata for a list of PDB entries.

    Returns dict keyed by lowercase PDB ID.
    """
    out: dict[str, dict] = {}
    if not pdb_ids:
        return out

    query_template = """
    query Q($ids: [String!]!) {
      entries(entry_ids: $ids) {
        rcsb_id
        struct {
          title
          pdbx_descriptor
        }
        rcsb_entity_source_organism {
          ncbi_scientific_name
        }
        struct_keywords {
          pdbx_keywords
          text
        }
        nonpolymer_entities {
          rcsb_nonpolymer_entity {
            pdbx_description
          }
          nonpolymer_comp {
            chem_comp {
              id
              name
            }
            rcsb_chem_comp_descriptor {
              SMILES
              SMILES_stereo
            }
          }
        }
      }
    }
    """
    for i in range(0, len(pdb_ids), batch):
        chunk = pdb_ids[i : i + batch]
        try:
            r = requests.post(
                RCSB_GRAPHQL_URL,
                json={"query": query_template, "variables": {"ids": chunk}},
                timeout=60,
                headers={"User-Agent": "lysos/0.1"},
            )
            r.raise_for_status()
            data = r.json()
            entries = data.get("data", {}).get("entries", []) or []
            for e in entries:
                if e and e.get("rcsb_id"):
                    out[e["rcsb_id"].lower()] = e
            time.sleep(0.2)
        except (requests.RequestException, json.JSONDecodeError) as exc:
            log.warning("GraphQL batch %d failed: %s", i, exc)
    return out


def _flatten_entry(entry: dict, *, pathogen_short: str, organism: str) -> list[dict]:
    """Convert a GraphQL entry into one row per ligand (or one row if no ligand)."""
    pdb_id = entry.get("rcsb_id", "").lower()
    title = (entry.get("struct") or {}).get("title", "")
    keywords = (entry.get("struct_keywords") or {}).get("pdbx_keywords", "")

    rows = []
    nonpolymers = entry.get("nonpolymer_entities") or []
    if not nonpolymers:
        rows.append({
            "pdb_id": pdb_id,
            "pathogen_short": pathogen_short,
            "organism": organism,
            "title": title,
            "keywords": keywords,
            "ligand_id": "",
            "ligand_name": "",
            "ligand_smiles": "",
        })
        return rows

    for np_entity in nonpolymers:
        ligand_desc = (np_entity.get("rcsb_nonpolymer_entity") or {}).get("pdbx_description", "")
        comp = np_entity.get("nonpolymer_comp") or {}
        chem_comp = comp.get("chem_comp") or {}
        smi_obj = comp.get("rcsb_chem_comp_descriptor") or {}
        smiles = smi_obj.get("SMILES_stereo") or smi_obj.get("SMILES") or ""
        rows.append({
            "pdb_id": pdb_id,
            "pathogen_short": pathogen_short,
            "organism": organism,
            "title": title,
            "keywords": keywords,
            "ligand_id": chem_comp.get("id", ""),
            "ligand_name": chem_comp.get("name", "") or ligand_desc,
            "ligand_smiles": smiles,
        })
    return rows


def fetch_pdb_targets(
    *,
    out_path: Path | str | None = None,
    pathogens: list[str] | None = None,
    max_per_pathogen: int = 1000,
) -> pd.DataFrame:
    pathogens = pathogens or list(AMR_TO_PDB_ORGANISMS.keys())
    rows: list[dict] = []
    for short in pathogens:
        for org in AMR_TO_PDB_ORGANISMS[short]:
            log.info("Searching RCSB for %s ...", org)
            pdb_ids = _search_organism(org, max_results=max_per_pathogen)
            log.info("  found %d PDB entries", len(pdb_ids))
            if not pdb_ids:
                continue
            log.info("  fetching metadata...")
            meta = _batch_metadata(pdb_ids)
            log.info("  parsed metadata for %d entries", len(meta))
            for pdb_id_lc, entry in meta.items():
                rows.extend(_flatten_entry(entry, pathogen_short=short, organism=org))

    df = pd.DataFrame(rows)
    if df.empty:
        log.warning("PDB: no rows collected")
        return df
    log.info("PDB total rows: %d (across %d pathogens)",
             len(df), df["pathogen_short"].nunique())

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False) if out_path.suffix == ".csv" else df.to_parquet(out_path, index=False)
        log.info("Wrote %d rows to %s", len(df), out_path)
    return df


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch PDB metadata for AMR pathogen structures")
    p.add_argument("--output", type=Path, default=Path("data/raw/pdb_amr_targets.csv"))
    p.add_argument("--max-per-pathogen", type=int, default=1000)
    p.add_argument("--pathogens", type=str, default=None)
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] pdb | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    pathogens = args.pathogens.split(",") if args.pathogens else None
    df = fetch_pdb_targets(
        out_path=args.output,
        pathogens=pathogens,
        max_per_pathogen=args.max_per_pathogen,
    )
    if df.empty:
        return 1
    log.info("Per-pathogen counts:\n%s", df["pathogen_short"].value_counts().to_string())
    log.info("Entries with ligand SMILES: %d / %d",
             (df["ligand_smiles"].astype(str).str.len() > 5).sum(), len(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
