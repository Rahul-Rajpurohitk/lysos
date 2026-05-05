# API Keys + Access — Single Source of Truth

What we need to get Lysos to peak performance. No fallbacks that degrade
quality — every component runs at full capability or fails loudly.

## Required (training will not run without these)

| Service | What it gives us | Cost | Where |
|---------|------------------|------|-------|
| **HF write token** | Push datasets + models to Hub | FREE (already have) | huggingface.co/settings/tokens |
| **AMD Dev Cloud credits** | $100 free + $200 budget | FREE + we pay overflow | amd.digitalocean.com |
| **Gemma 4 access** | Base model for Stage 1 + 2 | FREE (gated, request via web) | huggingface.co/google/gemma-4-31b-it |

## Recommended (quality differentiators — no fallback)

| Service | What it gives us | Cost | Where |
|---------|------------------|------|-------|
| **HF Pro** ($9/mo) | Faster downloads, ZeroGPU on Spaces, higher rate limits, more storage | $9 (have) | huggingface.co/subscribe |
| **GEMINI_API_KEY** | Real `embedding_novelty` reward (Gemini Embedding 2 — semantic novelty) | FREE tier 50/day | aistudio.google.com/apikey |
| **WANDB_API_KEY** | Live training metrics + reward dashboards | FREE tier sufficient | wandb.ai/authorize |

## Optional (only if running comparative benchmark)

| Service | What it gives us | Cost | Where |
|---------|------------------|------|-------|
| **OPENAI_API_KEY** | GPT-4 zero-shot comparison row | ~$5-10 | platform.openai.com/api-keys |
| **ANTHROPIC_API_KEY** | Claude zero-shot comparison row | ~$5-10 | console.anthropic.com |

## What HF Pro specifically unlocks

1. **Faster Gemma 4 download** — accelerated endpoints make 62GB pull take ~15min instead of 1+ hour. Saves ~45min per VM provision.
2. **HF Inference API for comparators** — Gemma 4, Llama 3, Mistral zero-shot benchmarks run via HF (no separate API needed). Covers many comparators "free" within Pro rate limits.
3. **ZeroGPU on Spaces** — public Lysos demo runs with GPU at zero cost (instead of needing paid Inference Endpoint).
4. **Higher private repo limits** — we have 12 private dataset versions; Pro tier easily holds them.
5. **Inference Endpoints discount** — when we deploy Lysos-RL for the demo, Pro pricing applies.

## Set them up before training

```bash
# On the AMD MI300X VM, before any training:
export HF_TOKEN=hf_...                 # write scope
export GEMINI_API_KEY=AIza...          # for real embedding_novelty
export WANDB_API_KEY=...               # for monitoring

# Optional (for comparative benchmark):
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
```

## Get them now (5 min total)

1. **GEMINI_API_KEY** (most important to address fallback)
   → https://aistudio.google.com/apikey → "Create API key"
   → Copy, save to `.env` and Space secrets

2. **WANDB_API_KEY**
   → https://wandb.ai/authorize → copy

3. **Gemma 4 access** (if not done already)
   → https://huggingface.co/google/gemma-4-31b-it → "Request access"
   → Approval takes 0-24h depending on Google's queue

4. **OpenAI / Anthropic** (optional, for comparative bench)
   → platform.openai.com / console.anthropic.com
   → ~$10 each pre-paid is plenty for ~200-prompt benchmark

## Why no fallbacks

**embedding_novelty fail-closed to 0.5 was wrong** — even neutral 0.5 still
contaminates the composite reward signal. Real fix: require GEMINI_API_KEY,
fail loudly if missing. Same for boltz2_pose: real Boltz-2 only or skip
the component (set weight=0).

**Updated policy** (committing now):
- All reward components either run at full capability OR are explicitly
  disabled (weight=0 in config) for that run
- No silent degradation
- VM startup script verifies all required keys are set; refuses to train
  if any is missing
