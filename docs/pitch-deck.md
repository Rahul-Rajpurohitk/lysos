---
marp: true
theme: default
size: 16:9
paginate: true
backgroundColor: "#06121a"
color: "#e6f7f3"
style: |
  section {
    font-family: Inter, system-ui, sans-serif;
    background: linear-gradient(180deg, #06121a 0%, #001114 100%);
    color: #e6f7f3;
  }
  h1, h2, h3 { color: #00e6b9; font-family: 'JetBrains Mono', ui-monospace, monospace; letter-spacing: -0.5px; }
  h2 { border-bottom: 1px solid #1f4458; padding-bottom: 0.4em; }
  table { color: #a3c2bd; }
  table th { color: #56cbb6; border-bottom: 1px solid #1f4458; }
  td, th { padding: 6px 12px; }
  code, pre { color: #00e6b9; background: #001114; }
  blockquote { color: #88c552; border-left: 3px solid #00e6b9; }
  section.title { text-align: left; }
---

# Lysos — Pitch Deck (10 slides, startup format)

> **Format**: 16:9 PDF for the lablab submission. Each slide capped at 2-3
> sentences per lablab guidelines. PDF generated from this markdown via Marp
> or similar; design system matches the workspace UI (dark biomedical, accent
> teal-cyan, JetBrains Mono for values).

---

## Slide 1 — Title + tagline

![cover](assets/cover-1920.png)

**Lysos**

Generative drug designer for antimicrobial resistance.

Built on Gemma 4 31B, RL-tuned on AMD Instinct™ MI300X.

`#hackathon #amd #lablab #aiagainstamr`

---

## Slide 2 — Problem

**Antimicrobial resistance is the silent pandemic.**

- 1.27 million deaths every year today (WHO).
- Projected to reach 10 million per year by 2050 (UN).
- Every routine surgery, childbirth, hospital stay becomes deadly without working antibiotics.
- The pharmaceutical industry has largely abandoned antibiotic R&D — too expensive, too slow, too low-margin.

We need a new tool — and AI on the right hardware can deliver it.

---

## Slide 3 — Solution

**Lysos generates novel antibacterial molecules in seconds, on a single GPU, with publicly verifiable activity scores.**

- **Open weights** — Gemma 4 31B fine-tuned for antibiotic design.
- **Reinforcement-learned** — GRPO with verifiable rewards (predicted MIC, drug-likeness, hemolysis, novelty).
- **Single GPU** — runs entirely on one AMD MI300X (192 GB VRAM).
- **Pathogen-aware** — 8 priority targets including MRSA, M. tuberculosis, ESBL+ E. coli, K. pneumoniae (CRE), A. baumannii, P. aeruginosa, VRE, N. gonorrhoeae.

---

## Slide 4 — Demo

**Pick a target → ranked candidate molecules in 30 seconds.**

Live demo on Hugging Face Spaces (`lablab-ai-amd-developer-hackathon/lysos`):

1. User selects a pathogen (e.g., MRSA).
2. Lysos generates 50 candidate antibacterial molecules.
3. Each candidate scored on: predicted MIC, drug-likeness, synthetic accessibility, hemolytic safety, novelty vs known antibiotics.
4. "Find similar known drugs" button: EmbeddingGemma cosine search returns top-5 closest known antibiotics with similarity bars.

Insert: `docs/assets/workspace-screenshot.png` (real screenshot of the local build — sidebar of 8 pathogens, MRSA selected, generation parameters, generate button).

![workspace](assets/workspace-screenshot.png)

---

## Slide 5 — Architecture

**Two-model coresident pipeline on a single MI300X.**

- **Generator**: Gemma 4 31B-it (33B dense, multimodal, frontier April 2026).
- **Embedder**: EmbeddingGemma 300m (Matryoshka 768→128 dims, Gemma 3 architecture).
- **Three-stage training**:
  1. Stage 1 — TxGemma-4 chemistry foundation (TDC ~50 tasks).
  2. Stage 2 — AMR specialization SFT on 96,975 real instruction-tuning examples (ChEMBL + DBAASP + DRAMP + DrugBank + CARD + PDB).
  3. Stage 3 — GRPO RL with 6-component verifiable reward.
- **Memory needs (during RL)**: ~150 GB → busts H100 80 GB → MI300X 192 GB is the prerequisite, not optional.

Insert: `docs/assets/architecture.svg` — full pipeline diagram with the MI300X "192 GB" memory-budget bar.

![architecture](assets/architecture.png)

---

## Slide 6 — Application of Technology

**Frontier ML primitives composed end-to-end:**

- LoRA + QLoRA on Gemma 4 31B for parameter-efficient SFT.
- Group Relative Policy Optimization (DeepSeek-R1 style) for RL training.
- Multi-component composite reward — each component logged separately to wandb so we catch reward-hacking.
- EmbeddingGemma 300m for semantic novelty (cosine over Matryoshka 768d) + RAG-augmented generation + training data dedup.
- Real data from 6 working public sources: ChEMBL (REST), DBAASP (REST + N+1 detail), DRAMP (XLSX/FASTA), CARD (tarball), PDB (GraphQL), ZINC.

All open-source, MIT-licensed, on a public GitHub.

---

## Slide 7 — Business Value

**TAM**: $50B annual antibiotic market. **SAM**: $5–10B "novel antibiotic R&D" — pharma is leaving this market; our cost structure changes the equation.

**Why now**: Every new MIC measurement on AMD MI300X gets cheaper as ROCm matures. Drug discovery cost per molecule drops 100× with generative + RL. Closes the gap between "pre-clinical screen" and "clinical candidate" by an order of magnitude.

**Customers**: BARDA + CARB-X + academic AMR labs (CDC funded), pharma rare-disease divisions, biosecurity orgs (DARPA, IARPA).

**Revenue model**: dataset + model licensing + enterprise hosting; cost-per-design API for academic labs.

---

## Slide 8 — Competitor analysis + USP

| Competitor | Approach | Our differentiation |
|---|---|---|
| Insilico Medicine | Proprietary stack, focus on oncology | Open weights; AMR-specialized |
| Recursion | Lab-in-the-loop screening | Pure-AI design; no wet lab needed for first-pass |
| Atomwise | Docking-based screening | Generative + RL; goes beyond known scaffolds |
| ChemLLM, Galactica | General chemistry LLMs | Pathogen-aware specialization; RL with verifiable AMR rewards |

**Our USP**: only open-source frontier-model AMR drug designer. Built specifically for the antibiotic resistance crisis. Verifiable rewards instead of expert-rater preferences. Runs on a single GPU.

---

## Slide 9 — Future prospects + roadmap

**Now**: Lysos v1 — proof of concept, hackathon submission, open weights + open dataset on Hugging Face Hub.

**Q3 2026**: wet-lab partnerships — partner with academic AMR labs (UCSD, USF, CARB-X grantees) to test top-10 generated candidates against actual MRSA / Mtb / Pseudomonas isolates. Closes the loop from in-silico to in-vitro.

**Q4 2026**: Lysos v2 — multimodal (X-ray crystal structure of binding pocket as image input), expanded pathogen set (fungi, viruses), human-in-the-loop optimization for individual molecules.

**2027**: spin-out company; partner with pharma for translational research on top-3 hits.

**Long-term**: same architecture extended to ESKAPE pathogens, mycobacteria, parasites — anywhere we have public activity data + a wet-lab partner.

---

## Slide 10 — Ask + close

**What we're asking for from this hackathon:**

- Recognition for the open-source release (model weights + 31K-example AMR dataset on HF Hub).
- Continued AMD Developer Cloud access to scale Stage 1 training to a true TxGemma-4 successor (10× the TDC corpus).
- Connection to AMR-focused academic labs to start wet-lab validation.

**What we're committing back:**

- Public model artifacts (`rahul24raj/lysos-rl`) under Apache-2.0.
- Public dataset (`rahul24raj/lysos-amr-stage2`).
- Open-source repo (`github.com/Rahul-Rajpurohitk/lysos`) with reproducible training pipeline.
- Two technical blog posts on building Lysos for the AMD Developer Hackathon — already in `vault/`.

**Antimicrobial resistance is the silent pandemic. Lysos is one tool in the fight.**

---

## Speaker notes

- Total reading time per slide: 25–35 seconds. Whole pitch ≈ 5 minutes.
- For the live pitch (May 10, on-stage if invited): demo the workspace at slides 4 and 5. Live generation should take <30s.
- Slide 1 cover: `docs/assets/cover-1920.svg` — title + tagline + stats row.
- Slide 4 demo screenshot: real workspace screen capture (MRSA, 5 candidates with score panels).
- Slide 5 insert: `docs/assets/architecture.svg` — full pipeline diagram with the 192 GB memory bar.
- Slide 6 insert: `docs/assets/reward-curves.svg` (placeholder) → swap with real wandb screenshot post-training. Show how "novelty" reward grew during RL.
- Slide 6 bonus: `docs/assets/data-flow.svg` — 10-source pipeline ending at HF Hub.
- Slide 7 insert: bar chart "antibiotic R&D investment 2010-2025" showing the abandonment.

## Production checklist

- [ ] Convert this `pitch-deck.md` to PDF via Marp (`marp pitch-deck.md --pdf`)
- [ ] Cover image (slide 1, 16:9 PNG)
- [ ] Architecture diagram for slide 5
- [ ] Wandb screenshot for slide 6
- [ ] Workspace screenshot for slide 4
- [ ] Final review against lablab judging criteria (Presentation, Business Value, Application of Tech, Originality)
- [ ] Submit at https://lablab.ai/event/amd-developer-hackathon/submit
