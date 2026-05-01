"""Inference / generation runtime for Lysos.

Used by:
  - The demo backend (FastAPI in workspace/) for live generation
  - Stage 3 RL prompts prep (to seed prompts)
  - Eval benchmarks
  - CLI for quick "design a molecule" sanity checks

Usage:

    # CLI (loads model, generates N samples for a target)
    python -m src.inference.generate \
        --model rahul24raj/lysos-rl \
        --target MRSA --n 50 --temperature 1.0

    # Programmatic
    from src.inference.generate import LysosGenerator
    gen = LysosGenerator(model_id="rahul24raj/lysos-rl")
    candidates = gen.design(target="MRSA", n=50)
    for c in candidates:
        print(c.smiles, c.scores)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] generate | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("generate")

PATHOGEN_CATALOG: dict[str, dict[str, str]] = {
    "MRSA": {
        "name": "Staphylococcus aureus (MRSA)",
        "category": "gram_positive",
        "context": "Methicillin-resistant Staphylococcus aureus is a major hospital-acquired pathogen causing skin, blood, and bone infections.",
    },
    "Mtb": {
        "name": "Mycobacterium tuberculosis",
        "category": "mycobacterium",
        "context": "M. tuberculosis kills 1.5 million people per year. MDR and XDR strains require new drug classes.",
    },
    "EColi-CRE": {
        "name": "Escherichia coli (ESBL+ / CRE)",
        "category": "gram_negative",
        "context": "ESBL-producing or carbapenem-resistant E. coli causes severe urinary tract and bloodstream infections.",
    },
    "KpneuCRE": {
        "name": "Klebsiella pneumoniae (CRE)",
        "category": "gram_negative",
        "context": "Carbapenem-resistant K. pneumoniae is among the WHO's highest priority pathogens; mortality up to 50%.",
    },
    "Abaum": {
        "name": "Acinetobacter baumannii",
        "category": "gram_negative",
        "context": "Multidrug-resistant A. baumannii causes ICU pneumonia, often pan-resistant. WHO priority 1.",
    },
    "Paer": {
        "name": "Pseudomonas aeruginosa",
        "category": "gram_negative",
        "context": "P. aeruginosa is intrinsically resistant to many antibiotics and a leading cause of CF lung infection.",
    },
    "VRE": {
        "name": "Enterococcus faecium (VRE)",
        "category": "gram_positive",
        "context": "Vancomycin-resistant Enterococcus faecium causes bloodstream and endocarditis infections.",
    },
    "NGono": {
        "name": "Neisseria gonorrhoeae",
        "category": "gram_negative",
        "context": "Drug-resistant gonorrhea is on the verge of becoming untreatable; new agents are urgently needed.",
    },
}


@dataclass
class Candidate:
    smiles: str | None
    sequence: str | None
    raw: str
    scores: dict[str, float] = field(default_factory=dict)
    combined: float | None = None

    def to_dict(self) -> dict:
        return {
            "smiles": self.smiles,
            "sequence": self.sequence,
            "scores": self.scores,
            "combined": self.combined,
            "raw": self.raw,
        }


GENERATION_PROMPT_SMI = (
    "Instructions: Design a small molecule antibiotic for the following pathogen.\n"
    "Context: {context}\n"
    "Question: Generate a single antibacterial molecule against {name}, "
    "prioritizing low MIC, drug-likeness (Lipinski-compliant), and synthetic accessibility.\n"
    "Output the molecule as a SMILES string."
)

GENERATION_PROMPT_AMP = (
    "Instructions: Design a short antimicrobial peptide (AMP) for the following pathogen.\n"
    "Context: {context}\n"
    "Question: Generate a single 10-30 residue antimicrobial peptide against {name}, "
    "prioritizing low hemolytic activity and high antibacterial potency.\n"
    "Output the peptide as a single-letter amino-acid sequence."
)


class LysosGenerator:
    """Loads a Lysos checkpoint and generates candidate molecules / peptides.

    On first instantiation, loads tokenizer + model (heavy). After that,
    .design() is fast (~seconds for 50 candidates on MI300X).
    """

    def __init__(
        self,
        model_id: str = "rahul24raj/lysos-rl",
        adapter_id: str | None = None,
        dtype: str = "bfloat16",
        device_map: str = "auto",
        attn_impl: str = "flash_attention_2",
    ):
        self.model_id = model_id
        self.adapter_id = adapter_id
        self.dtype = dtype
        self.device_map = device_map
        self.attn_impl = attn_impl
        self._tok = None
        self._model = None

    def _load(self):
        if self._model is not None:
            return
        log.info("Loading Lysos: %s (adapter=%s)", self.model_id, self.adapter_id)
        t0 = time.perf_counter()
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._tok = AutoTokenizer.from_pretrained(self.model_id, use_fast=True)
        if self._tok.pad_token is None:
            self._tok.pad_token = self._tok.eos_token

        dt = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[self.dtype]
        kwargs = dict(torch_dtype=dt, device_map=self.device_map, use_cache=True)
        if self.attn_impl == "flash_attention_2":
            kwargs["attn_implementation"] = "flash_attention_2"

        self._model = AutoModelForCausalLM.from_pretrained(self.model_id, **kwargs)

        if self.adapter_id:
            from peft import PeftModel
            log.info("Applying adapter: %s", self.adapter_id)
            self._model = PeftModel.from_pretrained(self._model, self.adapter_id)

        self._model.train(False)
        log.info("Model ready in %.1fs", time.perf_counter() - t0)

    def _build_prompt(
        self,
        target: str,
        *,
        modality: str = "smiles",
        rag_examples: list[dict] | None = None,
    ) -> str:
        info = PATHOGEN_CATALOG.get(target)
        if info is None:
            raise ValueError(f"unknown target: {target}; known: {list(PATHOGEN_CATALOG)}")
        template = GENERATION_PROMPT_AMP if modality == "peptide" else GENERATION_PROMPT_SMI
        prompt = template.format(name=info["name"], context=info["context"])

        # Optional RAG: append top-k known antibiotics as in-context examples
        if rag_examples:
            ref_lines = ["", "Reference examples (known antibiotics for this pathogen):"]
            for ex in rag_examples:
                line = f"- {ex.get('name', '?')}: SMILES = {ex.get('smiles', '')}"
                if ex.get("indication"):
                    line += f"  ({ex['indication']})"
                ref_lines.append(line)
            ref_lines.append("")
            ref_lines.append("Now design a NEW molecule, distinct from these references but inspired by their pharmacology.")
            prompt = prompt + "\n" + "\n".join(ref_lines)
        return prompt

    def design(
        self,
        target: str = "MRSA",
        n: int = 50,
        modality: str = "smiles",
        temperature: float = 1.0,
        top_p: float = 0.95,
        top_k: int = 0,
        max_new_tokens: int = 256,
        score: bool = True,
        enable_rag: bool = False,
        rag_index: str = "data/processed/known-antibiotics.smiles",
        rag_k: int = 3,
    ) -> list[Candidate]:
        """Generate `n` candidate molecules/peptides for `target`.

        Args:
            enable_rag: if True, retrieve top-k known antibiotics matching
                        the target and inject them as in-context examples.
                        Powered by EmbeddingGemma 300m.
            rag_index: path to indexed antibiotic corpus (.smi or .csv)
            rag_k: how many references to inject (default 3)
        """
        self._load()
        import torch

        rag_examples = None
        if enable_rag:
            try:
                from src.inference.retrieval import get_retriever
                retr = get_retriever(rag_index)
                pathogen_info = PATHOGEN_CATALOG.get(target, {})
                query = (f"antibiotic design for {pathogen_info.get('name', target)}: "
                         f"{pathogen_info.get('context', '')}")
                rag_examples = retr.retrieve(query, k=rag_k)
                log.info("RAG: retrieved %d in-context examples for %s",
                         len(rag_examples), target)
            except Exception as exc:  # noqa: BLE001
                log.warning("RAG retrieval failed (%s); generating without examples", exc)

        prompt = self._build_prompt(target, modality=modality, rag_examples=rag_examples)
        messages = [{"role": "user", "content": prompt}]
        formatted = self._tok.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False
        )
        inputs = self._tok(formatted, return_tensors="pt").to(self._model.device)

        log.info("Generating %d candidates for %s (modality=%s, T=%.2f)",
                 n, target, modality, temperature)
        t0 = time.perf_counter()

        outputs = self._model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            num_return_sequences=n,
            pad_token_id=self._tok.pad_token_id,
        )

        prompt_len = inputs["input_ids"].shape[-1]
        completions = [
            self._tok.decode(o[prompt_len:], skip_special_tokens=True).strip()
            for o in outputs
        ]
        log.info("Gen done in %.1fs (%.2fs/sample)",
                 time.perf_counter() - t0, (time.perf_counter() - t0) / max(1, n))

        candidates: list[Candidate] = []
        from src.eval.rewards import extract_smiles
        for raw in completions:
            smi = extract_smiles(raw)
            seq = None
            if modality == "peptide":
                # Peptide: extract amino acid sequence
                import re
                m = re.search(r"Sequence:\s*([A-Z]+)", raw)
                seq = m.group(1) if m else None
            candidates.append(Candidate(smiles=smi, sequence=seq, raw=raw))

        if score:
            self._score(candidates, target=target)

        return candidates

    def _score(self, candidates: list[Candidate], *, target: str) -> None:
        """Run the same composite reward used during Stage 3 training."""
        from src.eval.rewards.activity import predict_mic
        from src.eval.rewards.drug_likeness import qed_score
        from src.eval.rewards.novelty import tanimoto_distance_to_known
        from src.eval.rewards.safety import hemolysis_inverse
        from src.eval.rewards.synth import sa_score
        from src.eval.rewards.validity import smiles_valid

        raws = [c.raw for c in candidates]
        validity = smiles_valid(raws)
        mic = predict_mic(raws, target_pathogen=target)
        qed = qed_score(raws)
        synth = sa_score(raws)
        hemol = hemolysis_inverse(raws)
        novel = tanimoto_distance_to_known(raws)

        # Same weights as configs/stage3_rl_grpo.yaml
        weights = {
            "validity": 0.10,
            "predicted_mic": 0.35,
            "drug_likeness_qed": 0.15,
            "synthesizability": 0.10,
            "hemolysis_safety": 0.15,
            "novelty": 0.15,
        }
        for i, c in enumerate(candidates):
            c.scores = {
                "validity": validity[i],
                "predicted_mic": mic[i],
                "drug_likeness_qed": qed[i],
                "synthesizability": synth[i],
                "hemolysis_safety": hemol[i],
                "novelty": novel[i],
            }
            c.combined = sum(weights[k] * v for k, v in c.scores.items())


# ----------------------------- CLI -----------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate antibiotic candidates with Lysos")
    p.add_argument("--model", type=str, default="rahul24raj/lysos-rl",
                   help="HF model ID or local path")
    p.add_argument("--adapter", type=str, default=None, help="Optional LoRA adapter to apply")
    p.add_argument("--target", type=str, default="MRSA",
                   choices=list(PATHOGEN_CATALOG.keys()))
    p.add_argument("--n", type=int, default=50, help="Number of candidates to generate")
    p.add_argument("--modality", type=str, default="smiles", choices=["smiles", "peptide"])
    p.add_argument("--temperature", type=float, default=1.0)
    p.add_argument("--top-p", type=float, default=0.95)
    p.add_argument("--max-new-tokens", type=int, default=256)
    p.add_argument("--no-score", action="store_true", help="Skip scoring (faster)")
    p.add_argument("--output", type=Path, default=None,
                   help="Write candidates as JSON to this path")
    p.add_argument("--top", type=int, default=10, help="Print top-N to stdout")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    gen = LysosGenerator(model_id=args.model, adapter_id=args.adapter)
    candidates = gen.design(
        target=args.target,
        n=args.n,
        modality=args.modality,
        temperature=args.temperature,
        top_p=args.top_p,
        max_new_tokens=args.max_new_tokens,
        score=not args.no_score,
    )

    candidates.sort(key=lambda c: (c.combined or -1.0), reverse=True)
    log.info("Generated %d candidates. Top %d by composite score:", len(candidates), args.top)
    for i, c in enumerate(candidates[: args.top], 1):
        score_str = f"score={c.combined:+.3f}" if c.combined is not None else ""
        out = c.smiles or c.sequence or c.raw[:80]
        print(f"  {i:2d}. {score_str}  {out}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump([c.to_dict() for c in candidates], f, indent=2)
        log.info("Wrote %d candidates to %s", len(candidates), args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
