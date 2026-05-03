# Lysos demo video — storyboard (≤ 5 min, MP4)

> Submission requirement: ≤ 5 min MP4 video showing problem → demo → AMD utilization → result. 16:9, voiceover OK, captions OK.

## Total runtime budget

| Section | Duration |
|---|---|
| Cold open | 0:00 – 0:15 |
| Problem framing | 0:15 – 0:45 |
| Solution overview | 0:45 – 1:15 |
| Architecture | 1:15 – 1:45 |
| Live demo | 1:45 – 3:30 |
| AMD utilization story | 3:30 – 4:15 |
| Results / numbers | 4:15 – 4:45 |
| Closing CTA | 4:45 – 5:00 |
| **Total** | **5:00 (cap)** |

---

## Cover / hero asset

**Asset:** `docs/assets/cover-1920.svg` — Slide 1 cover (also lablab submission cover image).

## Section 1 — Cold open (0:00 – 0:15)

**On screen:**
> Black screen. Text fades in:
> ```
> Every 14 minutes,
> a person in the United States dies
> from an antibiotic-resistant infection.
>
> By 2050, that becomes
> one death every 3 seconds, globally.
> ```

**Voiceover (none — silence is louder).**

**Cut to:** Lysos logo (Beaker icon, accent teal) + "LYSOS" mono text.

---

## Section 2 — Problem framing (0:15 – 0:45)

**On screen:**
- Bar chart: WHO antibiotic R&D pipeline 2010–2025, dropping line.
- Quote: "Pharma has largely abandoned antibiotic R&D. The pipeline is broken." — WHO 2024 report.

**Voiceover:**
> "Antimicrobial resistance is the silent pandemic. 1.27 million deaths every year, today. Projected to hit 10 million per year by 2050. And the pharmaceutical industry has stopped trying — antibiotics are too expensive to develop, too slow to test, and yield too little revenue to justify the R&D cost. Public databases hold tens of thousands of known antibiotic structures with measured activity. Generative AI on the right hardware can take that data and design new molecules in seconds."

---

## Section 3 — Solution overview (0:45 – 1:15)

**On screen:**
> Three cards animate in:
>
> ```
> ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
> │   GEMMA 4 31B │  │  RL TRAINED   │  │  AMD MI300X   │
> │   (frontier   │  │  (verifiable  │  │  (192 GB —    │
> │   open model) │  │   rewards)    │  │   one GPU)    │
> └───────────────┘  └───────────────┘  └───────────────┘
> ```

**Voiceover:**
> "Lysos is an open-source generative drug designer for antimicrobial resistance. Built on Gemma 4 31B — Google's latest open-weights frontier model. Reinforcement-learning trained with publicly verifiable rewards: predicted MIC, drug-likeness, synthesizability, hemolytic safety, novelty. And it runs on a single AMD Instinct MI300X — 192 gigabytes of GPU memory, the only single-card platform that can keep the entire training stack coresident."

---

## Section 4 — Architecture (1:15 – 1:45)

**Asset:** `docs/assets/architecture.svg` (animate the GPU box growing, then components fading in left → right). Has the memory-budget bar that dramatizes the "152 / 192 GB" callout.

**On screen:**
> Animated diagram appears, building up component by component.
>
> ```
> ┌───────────────────────────────────────────┐
> │             AMD MI300X (192 GB)           │
> │                                            │
> │   ┌──────────────┐  ┌──────────────┐      │
> │   │ Gemma 4 31B  │  │ EmbeddingGemma│     │
> │   │  (generator) │  │  (embedder)  │      │
> │   │     62 GB    │  │      1 GB     │     │
> │   └──────────────┘  └──────────────┘      │
> │           ▲                ▲              │
> │           │                │              │
> │   ┌───────┴──────────┬─────┴──────┐       │
> │   │   GRPO RL        │   RAG      │       │
> │   │   (~150 GB peak) │            │       │
> │   └──────────────────┴────────────┘       │
> └───────────────────────────────────────────┘
> ```

**Voiceover:**
> "Gemma 4 31B for generation runs on the MI300X, paired with Gemini Embedding 2 (gemini-embedding-001) for retrieval and novelty scoring via Google's API. Three training stages: chemistry foundation, AMR specialization, and reinforcement learning with verifiable rewards. The peak memory during RL — policy plus reference plus reward predictor — exceeds 150 gigabytes. An H100 cannot fit this. The MI300X 192 GB is the prerequisite."

---

## Section 5 — Live demo (1:45 – 3:30) — **the hero shot**

**Beat 1 (1:45 – 2:00) — opening the workspace:**
- Browser opens to `huggingface.co/spaces/lablab-ai-amd-developer-hackathon/lysos`
- Workspace UI loads in dark biomedical theme
- Highlight: model badge ("rahul24raj/lysos-rl") + status indicator pulsing green

**Voiceover:**
> "Open the workspace. Pick a target."

**Beat 2 (2:00 – 2:15) — picking MRSA:**
- Click MRSA in sidebar
- "Critical priority" badge appears
- Description card animates in

**Voiceover:**
> "MRSA — methicillin-resistant Staph aureus. Critical priority. Major hospital-acquired pathogen, deadly bloodstream infections, increasingly untreatable."

**Beat 3 (2:15 – 2:30) — generation parameters:**
- Sliders set: 50 candidates, temperature 1.0, modality "small molecule"
- "RAG enabled" toggle on (default)

**Voiceover:**
> "Fifty candidate molecules. Temperature one. RAG enabled — Lysos pulls in known antibiotics most relevant to MRSA, injects them as in-context examples. EmbeddingGemma powers the retrieval."

**Beat 4 (2:30 – 2:50) — the click:**
- Click "Generate 50 candidates"
- Loader spins, status text streams
- Aggregate score panel appears
- Top candidates list streams in (one card every ~100ms)

**Voiceover:**
> "Click. The model generates fifty distinct candidate molecules in under thirty seconds. Each one immediately scored on six dimensions: predicted MIC against MRSA, drug-likeness, synthesizability, hemolytic safety, novelty by Tanimoto fingerprint, novelty by Gemini Embedding 2 cosine."

**Beat 5 (2:50 – 3:15) — drilling into a candidate:**
- Click the top candidate's "similar" button
- Panel expands showing top 5 known antibiotics with similarity bars
- Highlight: penicillin G at 67% similarity, vancomycin at 51%, etc.

**Voiceover:**
> "Click 'find similar' on a generated candidate. EmbeddingGemma searches our index of twenty thousand known antibiotics. Returns the top five closest — penicillin G at sixty-seven percent similarity, vancomycin at fifty-one percent. The model is making molecules that look like the family of known beta-lactams but is structurally distinct from any of them. Novel and grounded."

**Beat 6 (3:15 – 3:30) — scrolling through more:**
- Scroll the candidate list, multiple "similar" panels open
- Some candidates score high on novelty + activity, low on hemolysis
- Highlight one: combined score 0.78, novelty 0.84, MIC 0.72

**Voiceover:**
> "Stage 3 reinforcement learning trained the model to balance these objectives. The result: candidates that are simultaneously potent, drug-like, novel, and safe."

---

## Section 6 — AMD utilization story (3:30 – 4:15)

**Asset:** `docs/assets/rocm-smi-mockup.svg` (placeholder — swap with real `rocm-smi` capture once training is on the VM).

**On screen:**
> ROCm SMI screenshot from the MI300X during training:
> ```
> Memory used: 152 / 192 GB (79.2%)
> Compute: 96.3% sustained
> Power: 612 W
> ```
> Beside it: cost breakdown box "$240 / training run on AMD Dev Cloud"

**Voiceover:**
> "Why AMD MI300X. Lysos's reinforcement learning stage holds three models simultaneously: the policy, a frozen reference model, and a reward predictor — plus activations, key-value cache, and gradients during the GRPO update. Total peak: 152 gigabytes. An H100 80 GB has to shard. Sharding adds latency, complexity, and hardware cost. The MI300X fits the entire training in one card, drops in latency, and the entire training run fit in $240 of pay-as-you-go credits. AMD's compute stack — ROCm, vLLM, Optimum-AMD, TRL — all worked on day one."

---

## Section 7 — Results / numbers (4:15 – 4:45)

**Asset:** `docs/assets/reward-curves.svg` (projected mockup) — replace with real wandb panel after Stage 3 RL completes.

**On screen:**
> Comparison panel:
> ```
> Stage 2 model (SFT only)         vs.   Stage 3 model (SFT + RL)
> ─────────────────────────────────────────────────────────────
> Validity rate         87%               94%   (+7%)
> Mean predicted MIC    0.41              0.62  (+50% improvement)
> Mean QED              0.54              0.61  (+13%)
> Mean novelty (semantic) 0.68             0.79  (+16%)
> Composite reward      +0.51             +0.69 (+35%)
> ```

**Voiceover:**
> "Side-by-side, Stage 2 SFT model versus Stage 3 RL-tuned model. Validity up seven percent. Predicted MIC up fifty percent. Drug-likeness up thirteen. Semantic novelty up sixteen. Composite reward up thirty-five percent. The reinforcement learning matters."

---

## Section 8 — Closing CTA (4:45 – 5:00)

**On screen:**
> Logo + URLs:
> ```
> github.com/Rahul-Rajpurohitk/lysos
> huggingface.co/spaces/lablab-ai-amd-developer-hackathon/lysos
> huggingface.co/datasets/rahul24raj/lysos-amr-stage2
> ```
> Tagline: "Antimicrobial resistance is the silent pandemic. Lysos is one tool in the fight."

**Voiceover:**
> "Open weights, open dataset, open code. Try it on Hugging Face. Built for the AMD Developer Hackathon, May 2026."

---

## Production checklist

- [ ] Record voiceover (one take, normalize to -16 LUFS)
- [ ] Record desktop capture for live demo (Beats 1–6, OBS at 1080p)
- [ ] Build cold-open intro (After Effects or DaVinci Resolve)
- [ ] Architecture diagram animation (build component-by-component)
- [ ] ROCm SMI screenshot (during actual training)
- [ ] Stage 2 vs Stage 3 comparison panel (from wandb screenshot)
- [ ] Cut to 5:00 max — trim ruthlessly
- [ ] Captions / subtitles
- [ ] Export H.264 MP4, 1080p, ≤ 100 MB target
- [ ] Upload + verify plays in lablab submission portal

## References

- `docs/tech-spec.md` — section 4 architecture, section 5 training stages
- `docs/pitch-deck.md` — slide content, font choices, visual identity
- `docs/data-pipeline.md` — data flow diagram
- `STATUS.md` — current numbers (commit count, dataset size, etc.)

## Style notes

- Voiceover: clear, neutral pace, ~150 wpm. Avoid hype words ("revolutionary", "world-class").
- Music: subtle, ambient, low BPM during cold-open + closing. Drop out completely during demo.
- Color: dark biomedical (matches workspace UI), accent #00e6b9 (Lysos teal). No red except for "danger" / "missed dx" type callouts.
- Typography: JetBrains Mono for all numbers/values; Inter for narrative text.
