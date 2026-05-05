"""mine_hard_negatives.py — build a DPO pair dataset of Pareto traps.

For each Stage 3 RL prompt, generate K diverse candidates, score them
on the 12-component reward stack, then for every "hard axis pair"
(X is high, Y is low — see HARD_AXIS_PAIRS) emit a (chosen, rejected)
DPO row where:

  chosen   = a top-quartile-on-COMPOSITE candidate that does NOT fall
             into the trap
  rejected = a top-quartile-on-X but bottom-quartile-on-Y candidate

The intuition: a model that learns to prefer chosen-over-rejected on these
pairs has internalized that "high X alone is not enough — Y matters too."
This pre-aligns the policy along orthogonal axes BEFORE Stage 3 GRPO,
which dramatically reduces the time GRPO spends fumbling toward Pareto
balance.

Pluggable generator:
  --use_stub_generator      synthesize candidates from a tiny SMILES bank
                            (CI / smoke testing — no GPU needed)
  --model_id <hub_id>       load a local model and generate (needs GPU)
  --hf_endpoint <url>       call HF Inference Endpoint (Pro tier)

Output:
  parquet with DPO-ready columns (prompt, chosen, rejected, ...).

Run:
  # Smoke test:
  python scripts/mine_hard_negatives.py \
      --prompts data/processed/rl_prompts_v3 \
      --max_prompts 16 --candidates_per_prompt 4 \
      --use_stub_generator \
      --out /tmp/hn_smoke.parquet

  # Production run (after Stage 2 SFT):
  python scripts/mine_hard_negatives.py \
      --prompts rahul24raj/lysos-rl-prompts-v3 \
      --candidates_per_prompt 20 \
      --model_id rahul24raj/lysos-base \
      --out data/processed/lysos-hard-negatives-v1.parquet
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_dotenv() -> None:
    """Source .env (and ~/.cache/huggingface/token / ~/.netrc fallbacks)
    so reward components that need GEMINI_API_KEY / HF_TOKEN find them."""
    import os
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and k not in os.environ and v:
                os.environ[k] = v
    if not os.environ.get("HF_TOKEN"):
        tok_p = Path.home() / ".cache" / "huggingface" / "token"
        if tok_p.exists():
            os.environ["HF_TOKEN"] = tok_p.read_text().strip()


_load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] hn-mine | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hn-mine")


# ----------------------------------------------------------------------
# Hard axis catalog — (high X, low Y) traps the policy will commonly
# fall into if not pre-aligned. Order: (X, Y) where Y is the failure mode.
# ----------------------------------------------------------------------

HARD_AXIS_PAIRS: list[tuple[str, str, str]] = [
    # (X — looks good, Y — fails, description)
    ("predicted_mic", "hemolysis_safety",
     "active but kills RBCs (membrane-disruptor trap)"),
    ("predicted_mic", "synthesizability",
     "active in silico, impossible to synthesize"),
    ("novelty", "validity",
     "completely new scaffold but invalid valence"),
    ("novelty", "drug_likeness_qed",
     "novel scaffold, breaks rule-of-5"),
    ("boltz2_pose_conf", "predicted_mic",
     "docks well but doesn't bind (spurious pose)"),
    ("spectrum_breadth", "resistance_robustness",
     "broad-spectrum but fragile to one mutation"),
    ("structural_alerts", "novelty",
     "novel because it's a PAINS reactive group"),
    ("hemolysis_safety", "predicted_mic",
     "safe but inactive — wasted candidate"),
    ("drug_likeness_qed", "embedding_novelty",
     "looks druglike because it's nearly a known antibiotic"),
    ("validity", "predicted_mic",
     "valid junk SMILES (e.g. CCC)"),
]

REWARD_COMPONENTS = [
    "validity", "structural_alerts", "predicted_mic", "drug_likeness_qed",
    "synthesizability", "hemolysis_safety", "novelty", "embedding_novelty",
    "boltz2_pose_conf", "spectrum_breadth", "resistance_robustness", "pareto_entry",
]


# ----------------------------------------------------------------------
# Generators — pluggable
# ----------------------------------------------------------------------

# Tiny SMILES bank that exercises every Pareto trap (used by the stub).
_STUB_SMILES_BANK = [
    ("CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O", "penG",
     "balanced classical antibiotic"),
    ("CC(C)Cc1ccc(C(C)C(=O)O)cc1", "ibuprofen",
     "drug-like but not an antibiotic - low MIC"),
    ("CCC", "propane",
     "valid junk - no medicinal value"),
    ("Cl[H+]", "HCl",
     "valid garbage - high validity, zero everything"),
    ("CCCCCCCCCCCCCCCCN", "C16-amine",
     "amphipathic - high MIC + high hemolysis trap"),
    ("c1ccc(-c2ccc(N=Nc3ccc(O)cc3)cc2)cc1", "azo-dye",
     "structural-alert + novelty trap"),
    ("OC(=O)c1cc(=O)nc(=O)[nH]c1=O", "barbiturate-like",
     "QED-good, MIC-bad"),
    ("CN1CCN(c2ccc(C(=O)Nc3ccc(F)cc3)nc2)CC1", "balanced-novel-1",
     "balanced - moderate everything"),
    ("CC(=O)N[C@@H](Cc1ccc(O)cc1)C(=O)O", "tyrosine",
     "amino acid - drug-like, low MIC"),
    ("[C-]#[N+]N=Nc1ccccc1", "diazonium",
     "high novelty, high alerts"),
    ("Cc1ccc(S(N)(=O)=O)cc1", "sulfanilamide",
     "active sulfa, low novelty (well-known)"),
    ("OC1=CC=C(/C=C/C(=O)CC2=CC=C(O)C=C2)C=C1", "curcumin",
     "novel, druglike-ish, weak antibiotic"),
    ("[C@@H](C(=O)O)(N)CC1=CN=CN1", "histidine",
     "amino acid - non-novel, druglike"),
    ("ClC(Cl)(Cl)Cl", "CCl4",
     "valid SMILES, toxic, useless"),
    ("CC[C@H](C)[C@H](NC(=O)CN)C(=O)O", "alanyl-leu",
     "peptidomimetic - high MIC, low synth"),
    ("c1nc(N)c2ncn([C@@H]3O[C@H](CO)[C@@H](O)[C@H]3O)c2n1", "adenosine",
     "nucleoside - druglike, low antimicrobial"),
    ("CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "caffeine",
     "drug-like, but not antibacterial"),
    ("CC1=C(C(=O)NC2=CC=CC=C2)NC=N1", "imidazole-amide",
     "novel scaffold, valid, moderate everything"),
    ("CC(=O)Oc1ccc2cc[nH]c2c1", "5-hydroxyindole-acetate",
     "balanced novel"),
    ("c1ccccc1", "benzene",
     "valid, low novelty, low MIC"),
]


def stub_generator(prompt: str, k: int, *, seed: int = 0) -> list[str]:
    """Synth fixed-bank generator for CI/smoke testing.

    Picks K diverse SMILES from the bank, formatted as 'SMILES: ...' so
    the reward extract_smiles() picks them up. Uses a per-prompt
    deterministic shuffle so the same prompt always returns the same set
    (reproducible mining for tests).
    """
    rng = np.random.default_rng(seed=hash(prompt) & 0xFFFFFFFF)
    idx = rng.permutation(len(_STUB_SMILES_BANK))[:k]
    out = []
    for i in idx:
        smi, name, intent = _STUB_SMILES_BANK[i]
        out.append(f"PROPOSAL: SMILES: {smi}\n# {name} - {intent}")
    return out


def hf_endpoint_generator(endpoint_url: str, hf_token: str) -> Callable:
    """Returns a generator that hits an HF Inference Endpoint."""
    import urllib.request

    def _gen(prompt: str, k: int, *, seed: int = 0) -> list[str]:
        out = []
        for j in range(k):
            req = urllib.request.Request(
                endpoint_url,
                headers={
                    "Authorization": f"Bearer {hf_token}",
                    "Content-Type": "application/json",
                },
                data=json.dumps({
                    "inputs": prompt,
                    "parameters": {
                        "do_sample": True,
                        "temperature": [0.5, 0.7, 0.9, 1.2, 1.5][j % 5],
                        "top_p": 0.95,
                        "max_new_tokens": 256,
                        "seed": seed + j,
                    },
                }).encode("utf-8"),
                method="POST",
            )
            try:
                resp = urllib.request.urlopen(req, timeout=60)
                d = json.loads(resp.read())
                if isinstance(d, list) and d:
                    out.append(d[0].get("generated_text", ""))
                else:
                    out.append(d.get("generated_text", ""))
            except Exception as exc:  # noqa: BLE001
                log.warning("HF endpoint call failed: %s", exc)
                out.append("")
        return out
    return _gen


def local_model_generator(model_id: str, dtype: str = "bfloat16") -> Callable:
    """Generator using a local transformers model (needs torch + GPU for speed)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    log.info("Loading local model %s (one-time cost)...", model_id)
    dtype_t = {"bfloat16": torch.bfloat16, "float16": torch.float16,
               "float32": torch.float32}[dtype]
    tok = AutoTokenizer.from_pretrained(model_id, use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_id, torch_dtype=dtype_t, device_map="auto",
    )
    # Disable training mode (inference only).
    model.train(False)

    def _gen(prompt: str, k: int, *, seed: int = 0) -> list[str]:
        ids = tok(prompt, return_tensors="pt").to(model.device)
        out = []
        for j in range(k):
            torch.manual_seed(seed + j)
            temp = [0.5, 0.7, 0.9, 1.2, 1.5][j % 5]
            with torch.no_grad():
                gen = model.generate(
                    **ids,
                    max_new_tokens=256,
                    do_sample=True,
                    temperature=temp,
                    top_p=0.95,
                    pad_token_id=tok.pad_token_id,
                )
            text = tok.decode(gen[0][ids["input_ids"].shape[-1]:],
                              skip_special_tokens=True)
            out.append(text)
        return out
    return _gen


# ----------------------------------------------------------------------
# Reward scoring
# ----------------------------------------------------------------------


def score_candidates(
    candidates: list[str],
    cfg_path: Path = ROOT / "configs/stage3_rl_grpo.yaml",
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Return (scores [K, C], component_names, weights[C])."""
    import yaml
    from src.eval.rewards import CompositeReward

    cfg = yaml.safe_load(cfg_path.read_text())
    reward_cfg = cfg["reward"]
    fn = CompositeReward(
        components=reward_cfg["components"],
        on_error=reward_cfg.get("on_error"),
    )
    _, per = fn(candidates)
    names = [c["name"] for c in reward_cfg["components"]]
    K = len(candidates)
    C = len(names)
    M = np.zeros((K, C), dtype=np.float32)
    for j, n in enumerate(names):
        vals = per.get(n, [0.0] * K)
        for i, v in enumerate(vals):
            M[i, j] = float(v)
    weights = np.array([c["weight"] for c in reward_cfg["components"]],
                       dtype=np.float32)
    return M, names, weights


# ----------------------------------------------------------------------
# Pareto-trap detector + DPO pair builder
# ----------------------------------------------------------------------


@dataclass
class HardPair:
    prompt: str
    chosen: str
    rejected: str
    chosen_smiles: str | None
    rejected_smiles: str | None
    chosen_scores: dict[str, float]
    rejected_scores: dict[str, float]
    chosen_composite: float
    rejected_composite: float
    hard_axis_x: str
    hard_axis_y: str
    gap_x: float
    gap_y: float


def _quartile_mask(arr: np.ndarray, q: float, *, above: bool) -> np.ndarray:
    if len(arr) == 0:
        return np.zeros_like(arr, dtype=bool)
    threshold = np.quantile(arr, q)
    return arr >= threshold if above else arr <= threshold


def find_pairs_for_prompt(
    prompt: str,
    candidates: list[str],
    scores: np.ndarray,
    component_names: list[str],
    weights: np.ndarray,
    max_pairs_per_axis: int = 2,
) -> list[HardPair]:
    """Mine DPO pairs from K candidates for a single prompt."""
    from src.eval.rewards import extract_smiles

    K = len(candidates)
    if K < 4:
        return []

    composite = scores @ weights
    name_to_idx = {n: i for i, n in enumerate(component_names)}

    out: list[HardPair] = []

    for x_name, y_name, _intent in HARD_AXIS_PAIRS:
        if x_name not in name_to_idx or y_name not in name_to_idx:
            continue
        ix, iy = name_to_idx[x_name], name_to_idx[y_name]
        x_high = _quartile_mask(scores[:, ix], q=0.75, above=True)
        y_low = _quartile_mask(scores[:, iy], q=0.25, above=False)
        trap_idx = np.where(x_high & y_low)[0]
        if len(trap_idx) == 0:
            continue

        not_trap = ~(x_high & y_low)
        balanced = np.where(not_trap)[0]
        if len(balanced) == 0:
            continue
        balanced_sorted = balanced[np.argsort(-composite[balanced])]

        trap_rank = scores[trap_idx, ix] - scores[trap_idx, iy]
        trap_sorted = trap_idx[np.argsort(-trap_rank)]

        n_pairs = min(max_pairs_per_axis, len(balanced_sorted), len(trap_sorted))
        for k in range(n_pairs):
            c_i = int(balanced_sorted[k])
            r_i = int(trap_sorted[k])
            if c_i == r_i:
                continue
            chosen_text = candidates[c_i]
            rejected_text = candidates[r_i]
            if chosen_text == rejected_text:
                continue
            chosen_smi = extract_smiles(chosen_text)
            rejected_smi = extract_smiles(rejected_text)
            if chosen_smi == rejected_smi and chosen_smi is not None:
                continue

            chosen_breakdown = {n: float(scores[c_i, name_to_idx[n]])
                                for n in component_names}
            rejected_breakdown = {n: float(scores[r_i, name_to_idx[n]])
                                  for n in component_names}

            out.append(HardPair(
                prompt=prompt,
                chosen=chosen_text,
                rejected=rejected_text,
                chosen_smiles=chosen_smi,
                rejected_smiles=rejected_smi,
                chosen_scores=chosen_breakdown,
                rejected_scores=rejected_breakdown,
                chosen_composite=float(composite[c_i]),
                rejected_composite=float(composite[r_i]),
                hard_axis_x=x_name,
                hard_axis_y=y_name,
                gap_x=float(scores[c_i, ix] - scores[r_i, ix]),
                gap_y=float(scores[c_i, iy] - scores[r_i, iy]),
            ))
    return out


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def _load_prompts(spec: str, max_n: int | None) -> list[str]:
    """Load prompts from a local dataset path or HF hub id."""
    from datasets import load_dataset, load_from_disk

    p = Path(spec)
    if p.exists():
        ds = load_from_disk(str(p))
    else:
        ds = load_dataset(spec)
    train = ds["train"] if "train" in ds else ds
    out = []
    for r in train:
        if "prompt" in r and r["prompt"]:
            out.append(r["prompt"])
        elif "text" in r and r["text"]:
            out.append(r["text"])
        if max_n is not None and len(out) >= max_n:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", required=True,
                    help="Local DatasetDict path OR HF hub id")
    ap.add_argument("--max_prompts", type=int, default=None)
    ap.add_argument("--candidates_per_prompt", type=int, default=20)
    ap.add_argument("--max_pairs_per_axis", type=int, default=2)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--use_stub_generator", action="store_true",
                    help="Use the deterministic stub bank (CI / smoke testing)")
    ap.add_argument("--model_id", type=str, default=None,
                    help="HF model id for local generation (needs GPU)")
    ap.add_argument("--hf_endpoint", type=str, default=None,
                    help="HF Inference Endpoint URL")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    n_gen_specs = sum([args.use_stub_generator,
                       bool(args.model_id), bool(args.hf_endpoint)])
    if n_gen_specs != 1:
        log.error("Pick exactly one of --use_stub_generator / --model_id / --hf_endpoint")
        return 2

    if args.use_stub_generator:
        gen = stub_generator
    elif args.model_id:
        gen = local_model_generator(args.model_id)
    else:
        import os
        tok = os.environ.get("HF_TOKEN", "").strip() or \
              Path("~/.cache/huggingface/token").expanduser().read_text().strip()
        gen = hf_endpoint_generator(args.hf_endpoint, tok)

    prompts = _load_prompts(args.prompts, args.max_prompts)
    log.info("Loaded %d prompts", len(prompts))

    all_pairs: list[HardPair] = []
    t0 = time.time()
    for i, prompt in enumerate(prompts):
        cands = gen(prompt, args.candidates_per_prompt, seed=args.seed)
        scores, names, weights = score_candidates(cands)
        pairs = find_pairs_for_prompt(
            prompt, cands, scores, names, weights,
            max_pairs_per_axis=args.max_pairs_per_axis,
        )
        all_pairs.extend(pairs)
        if (i + 1) % max(1, len(prompts) // 20) == 0 or i == len(prompts) - 1:
            elapsed = time.time() - t0
            rate = (i + 1) / max(elapsed, 1e-3)
            log.info("[%d/%d] %.1f prompts/s | %d pairs | eta %.1fs",
                     i + 1, len(prompts), rate, len(all_pairs),
                     (len(prompts) - i - 1) / max(rate, 1e-3))

    log.info("Mining done: %d total pairs from %d prompts",
             len(all_pairs), len(prompts))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    rows = []
    for p in all_pairs:
        rows.append({
            "prompt": p.prompt,
            "chosen": p.chosen,
            "rejected": p.rejected,
            "chosen_smiles": p.chosen_smiles,
            "rejected_smiles": p.rejected_smiles,
            "chosen_scores": json.dumps(p.chosen_scores),
            "rejected_scores": json.dumps(p.rejected_scores),
            "chosen_composite": p.chosen_composite,
            "rejected_composite": p.rejected_composite,
            "hard_axis_x": p.hard_axis_x,
            "hard_axis_y": p.hard_axis_y,
            "gap_x": p.gap_x,
            "gap_y": p.gap_y,
        })
    df = pd.DataFrame(rows)
    df.to_parquet(args.out, index=False)
    log.info("Wrote %d rows to %s", len(df), args.out)

    if not df.empty:
        per_axis = df.groupby(["hard_axis_x", "hard_axis_y"]).size()
        log.info("Pairs per (X,Y) axis:\n%s", per_axis.to_string())
        log.info("Median gap_x = %.3f, gap_y = %.3f",
                 df["gap_x"].median(), df["gap_y"].median())

    return 0


if __name__ == "__main__":
    sys.exit(main())
