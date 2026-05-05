"""enrich_named_drugs_with_gemini.py — pull rich pharmacology text via Gemini 2.5 Pro.

For the top-named antibiotics in our catalog (penicillins, cephalosporins,
macrolides, fluoroquinolones, etc), use Gemini 2.5 Pro to generate compact
mechanism + spectrum + indication + resistance-escape paragraphs.

These rich paragraphs get appended to the embedding text → sharper semantic
similarity for the named-drug subset. The bulk ChEMBL/NPAtlas catalog stays
on the structural+physicochem template (we don't have clinical metadata for
those).

Output:
  artifacts/embeddings/named-drugs-gemini-enrichment.parquet
  columns: name, smiles, mechanism, spectrum, indications, resistance_escape

Cost:
  ~200 named drugs × ~600 output tokens × $10 / 1M output tokens
  ≈ $1.20

Run:
  python3 scripts/enrich_named_drugs_with_gemini.py --limit 5 --dry-run
  python3 scripts/enrich_named_drugs_with_gemini.py             # full 200
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


PROMPT_TEMPLATE = """You are an antimicrobial pharmacology expert. For the antibiotic
"{name}" (SMILES: {smiles}), produce a compact briefing in JSON with EXACTLY these fields:

  "mechanism":         1-2 sentences. Molecular target + mode of action (e.g.
                        "30S ribosome A-site, blocks aminoacyl-tRNA binding").
  "spectrum":          1 sentence. Gram +/- coverage + key pathogens it's used for.
  "indications":       1 sentence. Major clinical uses (FDA / first-line context).
  "resistance_escape": 1-2 sentences. The most common resistance mechanisms it's
                        susceptible to (e.g. "rRNA methylation by erm; efflux via
                        msrA").

Be CONCISE. Total length: 4 sentences max across all fields.
Output ONLY valid JSON, no markdown fence.

Example for vancomycin:
{{
  "mechanism": "Binds D-Ala-D-Ala terminus of cell-wall peptidoglycan precursors, blocking transpeptidation.",
  "spectrum": "Gram-positive only; first-line for MRSA, VRE-susceptible E. faecium, C. difficile.",
  "indications": "MRSA bacteremia/endocarditis; severe C. difficile colitis; surgical prophylaxis.",
  "resistance_escape": "vanA/vanB enzymes replace D-Ala-D-Ala with D-Ala-D-Lac → 1000-fold MIC shift; thickened cell wall in VISA."
}}

Now do "{name}":"""


# Top named drugs across major classes — covers what an AMR clinician
# would actually reach for. Pulled from the named-drug-elite-CoT slice
# we already curated for pro-v2; matches the high-leverage subset in the
# embedding novelty signal.
TOP_NAMED_DRUGS: list[tuple[str, str]] = [
    # β-lactams
    ("penicillin G",   "CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O"),
    ("amoxicillin",    "CC1(C)S[C@@H]2[C@H](NC(=O)[C@@H](N)c3ccc(O)cc3)C(=O)N2[C@H]1C(=O)O"),
    ("ampicillin",     "CC1(C)S[C@@H]2[C@H](NC(=O)[C@@H](N)c3ccccc3)C(=O)N2[C@H]1C(=O)O"),
    ("flucloxacillin", "Cc1onc(-c2ccccc2Cl)c1C(=O)N[C@@H]1C(=O)N2[C@@H]1SC(C)(C)[C@@H]2C(=O)O"),
    ("piperacillin",   "CCN1CCN(C(=O)N[C@@H](C(=O)N[C@@H]2C(=O)N3[C@@H]2SC(C)(C)[C@@H]3C(=O)O)c2ccccc2)C(=O)C1=O"),
    ("ceftriaxone",    "CO/N=C(\\C(=O)N[C@@H]1C(=O)N2C(C(=O)O)=C(CSc3nc(=O)c(=O)[nH]n3C)CS[C@H]12)c1csc(N)n1"),
    ("ceftazidime",    "CC(C)(O/N=C(/C(=O)N[C@@H]1C(=O)N2C(C(=O)O)=C(C[n+]3ccccc3)CS[C@H]12)c1csc(N)n1)C(=O)O"),
    ("cefepime",       "CO/N=C(\\C(=O)N[C@@H]1C(=O)N2C(C(=O)[O-])=C(C[n+]3(C)CCCC3)CS[C@H]12)c1csc(N)n1"),
    ("ceftaroline",    "CO/N=C(\\C(=O)N[C@@H]1C(=O)N2C(C(=O)O)=C(/N=N\\Sc3sc(-c4cc[n+](C)cc4)nn3)CS[C@H]12)c1nc(N)sc1OP(=O)(O)O"),
    ("cefiderocol",    "[O-]C(=O)C(=N\\C(C)(C)C(=O)O)/C(=O)NC1C(=O)N2C(C(=O)[O-])=C(C[N+]3=CC=C(/N=N/CCCNC(=O)/C=C/c4cc(O)c(O)c(c4)Cl)C=C3)CSC12"),
    ("imipenem",       "CC(O)C1C(=O)N2C(=C1S/C=C/NC=N)C(=O)O"),
    ("meropenem",      "CC([C@@H]1[C@H]2CC(=C(N2C1=O)C(=O)O)S[C@H]3CN[C@@H](C3)C(=O)N(C)C)O"),
    # Glycopeptides
    ("vancomycin",     "CC1C(C(CC(O1)OC2C(C(C(OC2OC3=C4C=C5C=C3OC6=C(C=C(C=C6)C(C(C(=O)NC(C(=O)NC5C(=O)NC7C8=CC(=C(C=C8)O)C9=C(C=C(C=C9C(NC(=O)C(C(C2=CC(=C(O4)C=C2)Cl)O)NC7=O)C(=O)O)O)O)NC(=O)C(C(C)C)NC)O)C)O)CO)O)O)(C)N"),
    ("teicoplanin",    "Truncated representation"),  # Skip — too complex
    ("daptomycin",     "lipopeptide_too_long_for_smiles"),  # Skip
    # Aminoglycosides
    ("gentamicin",     "C[C@@H]1O[C@@H](OC2[C@H](N)C[C@H](N)[C@@H](O[C@H]3O[C@H](CN)CC[C@H]3N)[C@H]2O)[C@H](C)CN1C"),
    ("amikacin",       "C[C@@H]1O[C@@H](OC2[C@H](OC3O[C@H](CO)[C@@H](O)[C@H](N)[C@H]3O)[C@@H](N)C[C@H](N)C2OC2OC(CN)CCC2N)[C@H](O)[C@@H](N)[C@H]1O"),
    ("tobramycin",     "NCC1OC(OC2C(O)C(OC3OC(CN)CCC3N)C(N)CC2N)C(N)C(O)C1O"),
    # Macrolides
    ("erythromycin",   "CC[C@@H]1OC(=O)[C@H](C)[C@@H](O[C@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@H](O[C@@H]2O[C@H](C)C[C@@H]([C@H]2O)N(C)C)[C@](C)(O)C[C@@H](C)C(=O)[C@H](C)[C@@H](O)[C@]1(C)O"),
    ("azithromycin",   "CC[C@H]1OC(=O)[C@H](C)[C@@H](O[C@@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@H](O[C@@H]2O[C@H](C)C[C@H](N(C)C)[C@H]2O)[C@](C)(O)C[C@@H](C)CN(C)[C@H](C)[C@@H](O)[C@]1(C)O"),
    ("clarithromycin", "CC[C@@H]1OC(=O)[C@H](C)[C@@H](O[C@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@H](O[C@@H]2O[C@H](C)C[C@@H]([C@H]2O)N(C)C)[C@](C)(OC)C[C@@H](C)C(=O)[C@H](C)[C@@H](O)[C@]1(C)O"),
    # Fluoroquinolones
    ("ciprofloxacin",  "O=C(O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O"),
    ("levofloxacin",   "C[C@H]1COc2c(N3CCN(C)CC3)c(F)cc3c(=O)c(C(=O)O)cn1c23"),
    ("moxifloxacin",   "COc1c(N2C[C@H]3CCCN[C@H]3C2)c(F)cc2c(=O)c(C(=O)O)cn(C3CC3)c12"),
    ("delafloxacin",   "Nc1nc(F)c(N2CC(O)C2)cc1F"),  # simplified
    # Tetracyclines
    ("doxycycline",    "C[C@@H]1c2cccc(O)c2C(=O)C2=C(O)[C@]3(O)C(=O)C(C(=O)N)=C(O)[C@@H](N(C)C)[C@@H]3C[C@H]12"),
    ("minocycline",    "CN(C)c1ccc(O)c2C(=O)C3=C(O)[C@]4(O)C(=O)C(C(=O)N)=C(O)[C@@H](N(C)C)[C@@H]4C[C@H]3C(N(C)C)c12"),
    ("tigecycline",    "CN(C)c1cc(NC(=O)CNC(C)(C)C)c2C(=O)C3=C(O)[C@]4(O)C(=O)C(C(=O)N)=C(O)[C@@H](N(C)C)[C@@H]4C[C@H]3C(N(C)C)c2c1"),
    ("eravacycline",   "CN(C)c1cc(NC(=O)CN2CCC2)c2c(c1F)[C@@H]1C[C@@H]3[C@H](N(C)C)C(=O)C(C(=O)N)=C(O)[C@@]3(O)C(=O)C1=C2O"),
    # Oxazolidinones
    ("linezolid",      "CC(=O)NC[C@H]1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1"),
    ("tedizolid",      "CN1[C@@H](CO)Cn2cc(-c3ccc(C(=O)NCC(F)(F)F)c(F)c3)nn2C1"),
    # Others
    ("trimethoprim",   "Cc1cc2cc(N)nc(N)c2cn1OCc1ccc(OC)c(OC)c1OC"),
    ("sulfamethoxazole","Cc1cc(NS(=O)(=O)c2ccc(N)cc2)on1"),
    ("rifampin",       "CC1=CC2=CC3=C(NC(=O)C(C)=CC(C)C(O)C(C)C(C)C(O)C(C)C(O)C1OC(C)=O)c1c2C(=O)C(=O)c1c3C=N\\N1CCN(C)CC1=N\\C"),
    ("isoniazid",      "NNC(=O)c1ccncc1"),
    ("ethambutol",     "CCC(NCCNC(CC)CO)CO"),
    ("metronidazole",  "Cc1ncc([N+](=O)[O-])n1CCO"),
    ("colistin",       "CC[C@@H](C)CCCCC(=O)N[C@H](CC(C)C)C(=O)N[C@H]1CCCCN[C@H]2CCNC(=O)[C@@H](N)CCCN[C@@H](Cc3ccccc3)C(=O)N1"),
    ("polymyxin B",    "CC[C@@H](C)CCCCC(=O)N[C@H](CC(C)C)C(=O)N[C@H]1CCCCN[C@H]2CCNC(=O)[C@@H](Cc3ccccc3)NC(=O)[C@H](Cc3ccccc3)NC(=O)[C@H]1CCCCN"),
    ("fosfomycin",     "C[C@H]1O[C@H]1P(=O)(O)O"),
    ("nitrofurantoin", "O=C1N(N=Cc2ccc(o2)[N+](=O)[O-])C(=O)NC1"),
    ("bedaquiline",    "Cc1cc2cc(C(O)([C@@H]3C[N@H+]4CC[C@H]3CC4)c3ccccc3)cnc2cc1OC"),
    ("delamanid",      "Cc1n(c(=O)n1Cc1ccc(OCC2(c3ccccc3)CCN(C)CC2)cc1)/N=N/[N+](=O)[O-]"),
    ("pretomanid",     "OCc1cc(=O)n(-c2ccc(OC(F)(F)F)cc2)c(=O)[nH]1"),
]


def gemini_25_pro(prompt: str, api_key: str,
                  model: str = "gemini-2.5-pro",
                  max_tokens: int = 600, timeout: float = 90.0) -> tuple[str, int, int]:
    """Single Gemini 2.5 Pro call. Returns (text, tokens_in, tokens_out)."""
    url = (f"https://generativelanguage.googleapis.com/v1beta/"
           f"models/{model}:generateContent")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": max_tokens},
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        return f"<ERR: {e}>", 0, 0
    text = ""
    for cand in d.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            text += part.get("text", "")
    u = d.get("usageMetadata", {})
    return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)


def parse_json_response(text: str) -> dict:
    """Strip optional markdown fence + parse JSON."""
    text = text.strip()
    if text.startswith("```"):
        # Remove ```json or ``` fence
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last-ditch: find first { ... last }
        i = text.find("{")
        j = text.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(text[i:j+1])
            except json.JSONDecodeError:
                pass
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-2.5-pro")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "artifacts/embeddings/named-drugs-gemini-enrichment.parquet")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Load .env
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                if k.strip() and k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[X] GEMINI_API_KEY not set")
        return 1

    drugs = TOP_NAMED_DRUGS
    # Filter out the placeholders
    drugs = [(n, s) for n, s in drugs if "too_complex" not in s.lower()
             and "too_long" not in s.lower() and "truncated" not in s.lower()]
    if args.limit:
        drugs = drugs[: args.limit]

    print(f"[INFO] Will enrich {len(drugs)} named drugs via {args.model}")
    if args.dry_run:
        for n, s in drugs[:5]:
            print(f"  [{n}]  SMILES len={len(s)}")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    total_in = total_out = 0
    t0 = time.time()
    for i, (name, smi) in enumerate(drugs):
        prompt = PROMPT_TEMPLATE.format(name=name, smiles=smi)
        text, t_in, t_out = gemini_25_pro(prompt, api_key, model=args.model)
        parsed = parse_json_response(text)
        rows.append({
            "name": name,
            "smiles": smi,
            "mechanism": parsed.get("mechanism", ""),
            "spectrum": parsed.get("spectrum", ""),
            "indications": parsed.get("indications", ""),
            "resistance_escape": parsed.get("resistance_escape", ""),
            "raw_response": text[:1500],
            "tokens_in": t_in,
            "tokens_out": t_out,
        })
        total_in += t_in
        total_out += t_out
        cost = (total_in / 1e6) * 1.25 + (total_out / 1e6) * 10.0
        if (i + 1) % 5 == 0 or i == len(drugs) - 1:
            print(f"  [{i+1}/{len(drugs)}] {name}  ({t_out} tok)  "
                  f"cum cost ${cost:.3f}")

    import pandas as pd
    df = pd.DataFrame(rows)
    df.to_parquet(args.out, index=False)
    cost = (total_in / 1e6) * 1.25 + (total_out / 1e6) * 10.0
    print(f"\n[OK] Wrote {len(df)} enriched named drugs to {args.out}")
    print(f"[OK] Total: {total_in:,} input + {total_out:,} output ≈ ${cost:.3f}")
    print(f"     elapsed: {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
