# AMD Developer Hackathon — Lysos Execution Playbook

**Hackathon dates**: May 4-10, 2026 (kickoff Mon May 4, 12:00 PM EDT — submission Sun May 10, 3:00 PM EDT)
**Project**: Lysos — open-source generative drug designer for AMR on AMD MI300X
**Track**: Track 2 (Fine-Tuning on AMD GPUs) + Grand Prize + HF Most-Liked Space
**Prize stack target**: $5K (Grand) + $2.5K (Track 2 1st) + Reachy Mini robot + 6mo HF Pro + $500 (HF Most-Liked) + $500 cash

---

## Pre-Kickoff Verification (May 2-3)

### Data corpus state ✅ READY
- Stage 2 pro on HF Hub: **393K+ examples** (`rahul24raj/lysos-amr-stage2-pro`)
  - Base chemistry: 222K (NPAtlas, ChEMBL, DrugBank, etc.)
  - CO-ADD ingestion: +80K (845K raw datapoints filtered)
  - TDC ADMET+Tox: +38K (drug safety predictions)
  - EUCAST clinical breakpoints: +851
  - WHO MIA stewardship: +446
  - Clinical AMPs: +269
  - Reasoning corpus: +5,213 (Wikipedia + PubMed + CARD + ChEMBL mech)
  - Teacher CoT: +289 (handwritten high-quality)
- Raw data sources: 13 (~116K rows + CO-ADD 845K = ~960K total)
- All ingestion code in `src/data/` and `scripts/`
- Reproducible: rerun any loader to refresh data

### Reward model components ✅ READY
- `src/eval/rewards/safety.py` — PAINS+Brenk+NIH+Lipinski+Veber + ML hemolysis predictor
- ML MIC predictor: XGBoost on Morgan fps, scaffold-CV MAE 0.62 / R² 0.56
- ML hemolysis predictor: CV AUROC 0.813 on 782 DBAASP peptides
- Structural alert reward at weight 0.05 in Stage 3
- All wired into `src/eval/rewards/composite.py`

### Pre-built artifacts ✅ READY
- `data/processed/hemolysis_predictor.joblib`
- `data/processed/mic_predictor.joblib`
- `data/processed/known-antibiotics.smiles` for Tanimoto novelty filter
- All teacher CoT examples in `data/synthetic/teacher_examples.jsonl` (289 rows)
- Recent FDA approvals as named-drug dives in `data/synthetic/named_drug_examples.jsonl` (5 rows)

### TODO before May 4 kickoff
- [ ] **Verify AMD AI Developer Program credits arrive ($100, signed up Apr 29)**
- [ ] **Join lablab Discord** (community connection)
- [ ] **Watch 5 official AMD workshop videos** (template patterns)
- [ ] **Smoke-test rocm/vllm:latest with amd/gpt-oss-120b-MXFP4 once credits land**
- [ ] **Lock pitch deck slide skeleton** (TAM/SAM, revenue model, competitors, future prospects)
- [ ] **Lock 16:9 cover image** (Lysos brand visual)
- [ ] Verify HF token write-scope works for `rahul24raj/lysos-amr-stage1`, `lysos-amr-stage2-pro`, `lysos-rl`

---

## Day-by-Day Execution Plan

### Day 1 (Mon May 4) — Kickoff + Stage 1 Launch
**Hours 0-2 (12:00-14:00 EDT) — Cloud setup**
- Spin up AMD Dev Cloud Small (1× MI300X, 192GB VRAM, ~$2-4/hr)
- Pull `rocm/vllm:latest` Docker image (the AMD-blessed inference container)
- Smoke test: load `amd/gpt-oss-120b-MXFP4` via vLLM, confirm inference works
- Set up shared volume for model checkpoints + data sync from HF Hub

**Hours 2-6 (14:00-18:00 EDT) — Stage 1 baseline**
- Pull TxGemma-27B Hugging Face checkpoint to local cache
- Run benchmark eval (`scripts/benchmark_txgemma_27b.py` already in repo) on 100 sample SMILES
  to establish baseline MIC prediction accuracy
- Verify Stage 1 reward gradient flow

**Hours 6-12 (18:00-00:00 EDT) — Stage 1 LARGE provisioning**
- DESTROY Small VM (powered-off VMs still bill!)
- Provision LARGE 8× MI300X (1.5 TB total VRAM, ~$16-30/hr)
- Mount Stage 2 pro dataset (393K examples) from HF
- Launch Stage 1 SFT job: TxGemma-4 base on 393K examples
  - Effective batch size 256 across 8 GPUs
  - Sequence length 4096 (handles all teacher CoT examples)
  - Mixed precision bf16
  - Estimated wall clock: 6-8 hours for 1 epoch
- Monitor: Hugging Face Spaces dashboard or W&B

**Day 1 spend estimate**: $40-80 ($2-4 × 6 hr Small + $16-30 × 1 hr Large setup)

### Day 2 (Tue May 5) — Stage 1 Convergence + Stage 2 Plan
**Hours 0-8 — Wait for Stage 1 SFT to complete + monitor**
- Loss curves, gradient norms, sample generations every 1K steps
- Should converge to MIC prediction R² > 0.6 (vs heuristic 0.56)
- Push checkpoint to `rahul24raj/lysos-stage1` on HF Hub

**Hours 8-12 — Stage 2 prep**
- Load Stage 1 checkpoint
- Verify reasoning quality on held-out teacher CoT examples
- Configure Stage 2 SFT: continue training on full 393K Stage 2 pro corpus
  - Stage 1 was chemistry/MIC focused; Stage 2 adds reasoning + ADMET + EUCAST + WHO context
  - Same 8× MI300X cluster
  - Estimated wall clock: 4-6 hours

**Hours 12-24 — Stage 2 SFT training**
- Same monitoring approach
- Push to `rahul24raj/lysos-amr-stage2`

**Day 2 spend estimate**: $40-90 (mostly idle while training, plus storage)

### Day 3 (Wed May 6) — Stage 3 RL Setup + Initial Generations
**Hours 0-6 — Reward model calibration**
- Reward stack: MIC predictor (40%) + safety (30%) + drug-likeness (15%) + structural-alert (15%)
- Test on 100 known antibiotics (cipro, vanco, polymyxin, etc.) — should score high
- Test on 100 known decoys (PAINS, propyl gallate, etc.) — should score low
- Calibrate weights if needed

**Hours 6-18 — GRPO RL launch**
- Stage 3: Group Relative Policy Optimization on Stage 2 model
- Generate 8 candidates per prompt, score with reward stack, update policy
- Same 8× MI300X — RL is more compute-heavy due to multiple rollouts
- Estimated wall clock: 12 hours for ~5K policy updates
- Push intermediate checkpoints every 1K steps

**Hours 18-24 — First Lysos-RL generations**
- Generate 1000 novel SMILES targeting CRE-Kp + MRSA + Mtb
- Filter by Tanimoto similarity > 0.4 to known compounds (novelty)
- Filter by Lipinski + Veber + PAINS (drug-likeness)
- Hand-select top 20 candidates per pathogen for showcase

**Day 3 spend estimate**: $80-200 (RL training is expensive)

### Day 4 (Thu May 7) — Stage 3 Convergence + Spaces Demo
**Hours 0-8 — Continue RL training + monitor**
- Look for reward score plateau (typical convergence around 5-10K updates)
- Sample diverse generations across pathogens
- Push final `rahul24raj/lysos-rl` checkpoint to HF Hub

**Hours 8-16 — HF Spaces interactive demo**
- Build Gradio app at `rahul24raj/lysos-amr-designer` (HF Space)
- UI: pathogen selector + property targets + "Generate" button
- Inference: vLLM-served Lysos-RL model
- Display: SMILES → 2D structure (RDKit) + predicted MIC + safety scores + EUCAST
  interpretation context + WHO stewardship class
- AMD branding: footer "Powered by AMD MI300X — built for the AMD Developer Hackathon 2026"

**Hours 16-24 — Demo polish + share**
- Public Twitter/X thread: "Lysos: open-source generative drug designer for AMR"
- LinkedIn post for professional reach
- Submit to lablab.ai HF Most-Liked Space competition (3-day voting window)
- Tag @AMDdev, @huggingface, #AMRpipeline

**Day 4 spend estimate**: $60-100 (training tail + Spaces inference)

### Day 5 (Fri May 8) — Pitch Deck + Demo Video
**Hours 0-8 — Pitch deck (mandatory per lablab rules)**
- 12-15 slides, 16:9 PDF format
- Required content (per lablab pro tips):
  - Slide 1: Cover image + Lysos logo + tagline ("Generative drug design for AMR on AMD MI300X")
  - Slide 2-3: Problem (AMR crisis: 1.27M deaths/yr → 10M/yr by 2050) + market size (TAM/SAM)
  - Slide 4-5: Solution architecture (3-stage pipeline) + AMD MI300X advantage
  - Slide 6-7: Demo (HF Space screenshots + sample generations)
  - Slide 8: Validation (reward model performance + benchmark vs published baselines)
  - Slide 9: Revenue model (open-source + premium API + pharma partnerships)
  - Slide 10: Competitors (TxGemma, Bio-Mistral, BioGPT — what makes Lysos different)
  - Slide 11: Future prospects (TB-specific fine-tune, peptide-specific track, multimodal)
  - Slide 12: Team + AMD acknowledgment + contact

**Hours 8-16 — 5-min demo video (mandatory, 5 min MAX)**
- Tools: Loom or OBS Studio
- Script:
  - 0:00-0:30 — Hook: AMR statistics + the problem
  - 0:30-1:30 — Architecture: 3-stage pipeline + AMD MI300X
  - 1:30-3:00 — Live demo: HF Space generation + walk through a generated antibiotic
  - 3:00-4:00 — Validation: benchmark numbers + scaffold-novelty examples
  - 4:00-5:00 — Vision: AMR + cancer + future scaling
- Upload to YouTube, embed in HF Space, link in submission

**Hours 16-24 — Repository polish**
- Make `Rahul-Rajpurohitk/lysos` GitHub repo PUBLIC (currently private)
- Update README with: quickstart, architecture, results, AMD acknowledgment
- Add LICENSE (Apache 2.0 typical for ML model code)
- Tag v1.0.0 release with Lysos branding
- Update HF model cards for `lysos-stage1`, `lysos-stage2`, `lysos-rl`

**Day 5 spend estimate**: $30 (mostly idle inference)

### Day 6 (Sat May 9) — Buffer + On-site SF (if invited)
**If invited to on-site SF (May 9-10)** — fly out, present in-person
**If virtual** — additional showcase activity:
- Twitter Space or LinkedIn live for community Q&A
- Final HF Space optimization for "most-liked" voting
- Solicit upvotes from network (this matters for HF Most-Liked $500 prize)

### Day 7 (Sun May 10) — Submission Day
**Hours 0-3 (00:00-15:00 EDT)** — Final submission preparation
- Submit on lablab.ai BEFORE 3:00 PM EDT (HARD deadline):
  - Project name: Lysos
  - Track: Fine-Tuning on AMD GPUs (Track 2)
  - Pitch deck (PDF)
  - Demo video (YouTube link)
  - GitHub repo (public link)
  - HF Space URL (live demo)
  - Cover image (16:9)
  - Brief description (200 words)
  - Team info

**Hours 3-12** — Post-submission
- Submit Track 2 + Grand Prize categories (both stack)
- Post final showcase thread on Twitter
- Email AMD dev relations team for feature consideration
- Submit to additional AMR-focused communities (CDC, GARDP, CARB-X)

---

## Budget Tracking

**Total budget ceiling**: $300
**AMD Developer Program credits**: $100 (free)
**Out-of-pocket target**: $70-140

**Day-by-day estimate**:
- Day 1: $40-80 (provisioning + Stage 1 launch)
- Day 2: $40-90 (Stage 1 + Stage 2 SFT)
- Day 3: $80-200 (RL training)
- Day 4: $60-100 (RL tail + Spaces)
- Day 5: $30 (pitch + video)
- Day 6: $20 (buffer)
- Day 7: $20 (submission)
- **TOTAL: $290-540**

**Cost optimization levers if running over**:
- Use Small (1× MI300X) for Stage 2 SFT instead of Large — saves ~$100
- Skip GRPO and use simpler DPO instead — faster, cheaper, slightly less optimal
- Use smaller batch / fewer epochs and accept marginally weaker model
- Halt at end of Day 5, skip Day 6 buffer

---

## Judging Criteria — How Lysos Maps

Per lablab.ai: 4 equal-weighted criteria (25% each):

### 1. Application of Technology (25%)
- ✅ Heavy use of MI300X (Stage 1 needs 8× MI300X for TxGemma-4 base, busts H100 80GB)
- ✅ rocm/vllm Docker (AMD's blessed stack)
- ✅ Multi-stage pipeline showcasing different MI300X capabilities (training, RL, inference)
- ✅ Clear AMD-specific value proposition: "RL holds policy + reference + reward predictor coresident,
   ~150GB — busts H100 80GB. MI300X is the prerequisite, not optional."

### 2. Presentation (25%)
- Pitch deck slide 1-12 covers all required elements
- 5-min video with clear narrative arc
- HF Space provides interactive showcase
- README with clear architecture diagrams

### 3. Business Value (25%)
- ✅ AMR market: $11B in 2024, projected $20B by 2030
- ✅ Unmet need: only 5 truly-novel antibiotic classes in last 30 years
- ✅ Pharma pain point: $1.5B avg cost to bring antibiotic to market
- ✅ Public health: 1.27M deaths/year now, projected 10M by 2050
- Revenue model: open-source + premium API + pharma R&D partnerships

### 4. Originality (25%)
- ✅ NEW combination: TxGemma + AMR-specific SFT + GRPO with verifiable rewards
- ✅ NEW data integration: CO-ADD + TDC + EUCAST + WHO + 289 hand-curated CoT examples
- ✅ NEW architectural choice: scaffold-CV split + ML reward model + clinical-stewardship-aware
- Differentiation from competitors:
  - vs TxGemma proper: AMR-specialized, better safety reward
  - vs Bio-Mistral: trained on chemistry + biological reasoning combined
  - vs MolGen / generative chemistry models: bacterial-target-aware + clinical-context-aware

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| AMD credits delayed | Medium | High | Apply immediately Apr 29 (✅ done). If delayed, use existing HF inference for demo + train smaller model on local |
| MI300X availability constrained | Low | High | Multi-region failover (DigitalOcean has multiple AMD regions); reserve early Day 1 |
| Stage 1 SFT diverges or NaN | Medium | High | Bf16 precision + grad clipping + warmup. Have Stage 0 (TxGemma-4 base) checkpoint ready as fallback |
| Stage 3 RL unstable | High | Medium | Use DPO instead of GRPO if needed (more stable, slightly less optimal). Have Stage 2 SFT-only checkpoint as backup |
| HF Space inference slow | Medium | Medium | Quantize to GGUF / use smaller model for inference (10-15B param). Pre-generate 100 samples to show in demo |
| Submission deadline missed | Low | Critical | Submit final draft Day 6 morning as buffer. Build submission pipeline that auto-uploads on git push |
| Pitch deck unfinished | Low | Critical | Slide skeleton ready before kickoff (template). Draft each slide on Day 5 morning |
| Demo video tech issues | Medium | Medium | Pre-record fallback. Test on 2-3 platforms (mobile, desktop, YouTube) before submit |
| Public IP issues | Low | High | Apache 2.0 LICENSE explicit. Acknowledge AMD + HuggingFace in README + video |
| Resistance from judges to "drug discovery" framing | Low | Medium | Have backup framing: "AI-assisted hypothesis generation for medicinal chemists" |

---

## Pitch Deck Skeleton (Pre-build before May 4)

**Slide 1: Cover**
- Lysos logo (TBD: design with Midjourney prompt: "open-source antibiotic molecule logo, blue + green, scientific minimalist")
- Tagline: "Generative AI for the post-antibiotic era — built on AMD MI300X"
- Team: Rahul Rajpurohit
- AMD Developer Hackathon 2026 | Track 2 | rahul24raj on HuggingFace

**Slide 2: The AMR Crisis**
- Map of global AMR deaths (1.27M/year now → 10M/year by 2050)
- Key stat: "If we don't act, AMR will kill more people than cancer by 2050"
- WHO Priority 1 pathogens: CRE, CRPA, CRAB
- Pipeline drought: only 5 truly novel antibiotic classes in 30 years

**Slide 3: Why Generative AI**
- Traditional drug discovery: $1.5B and 10-15 years per drug
- AI generative: 100K+ candidates per day per GPU
- Bottleneck: not generation, but TARGETED generation with safety + efficacy constraints

**Slide 4: Lysos Architecture**
- Diagram: Stage 1 (TxGemma-4 base SFT) → Stage 2 (AMR specialization) → Stage 3 (GRPO RL with verifiable rewards)
- Data: 393K examples (CO-ADD + ChEMBL + AMP + clinical context)
- Reward stack: MIC predictor + safety + drug-likeness + structural-alerts

**Slide 5: AMD MI300X Advantage**
- Stage 3 RL holds policy (TxGemma-4 31B = 60GB) + reference (60GB) + reward (15GB) coresident
- Total VRAM needed: ~150GB — busts H100 80GB
- MI300X 192GB enables Stage 3 in single-GPU mode
- 1.5TB total VRAM in 8× MI300X enables Stage 1 distributed training of TxGemma-4 base

**Slide 6: Demo**
- HF Space screenshot
- Sample generation: input "MRSA-active β-lactam with low PBP2a Ki"
- Output: SMILES + 2D structure + predicted MIC + EUCAST classification + WHO category

**Slide 7: Validation**
- Benchmark vs published baselines on MIC prediction
- Reward model accuracy on known antibiotics vs decoys
- Scaffold novelty: % of generations with Tanimoto < 0.4 to training set

**Slide 8: Business Value**
- Market: $11B (2024) → $20B (2030)
- TAM: 50K medicinal chemists worldwide
- SAM: pharma R&D departments + academic labs + biotechs
- Revenue model:
  - Open-source: free model + community contributions
  - Premium API: $0.10-1.00 per generation, with safety filters + EUCAST integration
  - Pharma partnerships: $50K-500K licensing for proprietary fine-tunes

**Slide 9: Competitive Landscape**
- TxGemma: general bio + chem, not AMR-specialized
- Bio-Mistral: focuses on biological text, not chemistry generation
- MolGen / RDKit Generative: chemistry-focused but no biological context
- ChemSpace + ZINC virtual screens: no AI generation
- **Lysos differentiator**: AMR-specialized + WHO/EUCAST aware + clinical-context-aware

**Slide 10: Roadmap**
- Q3 2026: Lysos v2 with TB Alliance pipeline + EUCAST v16
- Q4 2026: Lysos-Pep specialized for antimicrobial peptides
- Q1 2027: Multimodal Lysos (X-ray crystallography conditioning)
- Q2 2027: Lysos-Cancer (oncology drug design extension)

**Slide 11: Team + Acknowledgments**
- Rahul Rajpurohit (sole dev)
- AMD: GPU compute via Developer Cloud
- HuggingFace: model hosting + Spaces
- Open data: ChEMBL, DrugBank, NPAtlas, CO-ADD, TDC, EUCAST, WHO

**Slide 12: Call to Action**
- Try Lysos: rahul24raj/lysos-rl on HuggingFace
- Contribute: github.com/Rahul-Rajpurohitk/lysos
- Cite: "Lysos: Generative AMR drug design on AMD MI300X" (forthcoming)
- Contact: rahulrajpurohit@gmail.com | LinkedIn

---

## Post-Hackathon (After May 10)

### If we WIN
- Press release for AMD + HF + lablab.ai networks
- Apply to follow-up programs: AMD AI Innovation Cloud (longer-term compute), Y Combinator AI batch
- Open-source Lysos as a community project — hand off to academic Mtb/AMR labs
- Write follow-up paper: "Lysos: Open-Source Generative AMR Design with Verifiable Rewards"

### If we don't win main prize but get HF Most-Liked
- Open-source release as planned
- Use $500 + Reachy Mini robot (MOST IMPORTANTLY: 6mo HF Pro)
- Build follow-up demo for academic Mtb conference

### If we don't win anything
- Still get the open-source Lysos in production
- Use it for the next hackathon (NeurIPS workshop, AAAI, etc.)
- Approach pharma collaborators directly

---

## Appendix A: Stage 1 Training Command (preview)

```bash
# Stage 1 SFT on 8× MI300X
docker run --rm --gpus all \
    -v $HOME/.cache/huggingface:/root/.cache/huggingface \
    -v $PWD/configs:/configs \
    -v $PWD/checkpoints:/checkpoints \
    rocm/vllm:latest \
    python -m torch.distributed.run \
        --nnodes 1 --nproc_per_node 8 \
        --master_addr localhost --master_port 29500 \
        scripts/train_stage1_sft.py \
        --base-model google/txgemma-4-31B-it \
        --train-dataset rahul24raj/lysos-amr-stage2-pro \
        --val-split 0.05 \
        --batch-size-per-device 32 \
        --grad-accum-steps 1 \
        --max-seq-len 4096 \
        --learning-rate 2e-5 \
        --num-epochs 1 \
        --warmup-ratio 0.03 \
        --logging-steps 50 \
        --save-steps 1000 \
        --output-dir /checkpoints/lysos-stage1 \
        --bf16 \
        --gradient-checkpointing \
        --push-to-hub rahul24raj/lysos-stage1
```

## Appendix B: Reward Stack (Stage 3 RL)

```python
def composite_reward(smiles: str, target_pathogen: str) -> dict:
    return {
        "mic_score": ml_mic_predictor.predict(smiles, target_pathogen) * 0.40,
        "safety_score": safety_reward(smiles) * 0.30,  # PAINS+Brenk+NIH+Lipinski+Veber
        "druglikeness": qed_score(smiles) * 0.15,       # 0-1 QED (quantitative drug-likeness)
        "novelty": tanimoto_novelty(smiles) * 0.10,     # vs known-antibiotics.smiles set
        "structural_alerts": -structural_alert_score(smiles) * 0.05,  # negative penalty
    }
```

## Appendix C: HF Spaces Demo Architecture

```python
# Gradio app structure
import gradio as gr
from lysos import LysosGenerator

generator = LysosGenerator.from_hub("rahul24raj/lysos-rl")

def generate_drug(pathogen, target_class, num_candidates):
    smiles_list = generator.generate(
        pathogen=pathogen,
        target_class=target_class,
        n=num_candidates,
        temperature=0.8,
    )
    # Score with reward stack
    scored = [(s, composite_reward(s, pathogen)) for s in smiles_list]
    # Sort by total reward
    scored.sort(key=lambda x: sum(x[1].values()), reverse=True)
    # Return top N as: SMILES + 2D image + EUCAST + WHO + safety scores
    return [format_candidate(s, scores) for s, scores in scored[:10]]

demo = gr.Interface(
    fn=generate_drug,
    inputs=[
        gr.Dropdown(choices=["MRSA", "VRE", "CRE-Kp", "CRAB", "CRPA", "Mtb", "Ngono", "EColi-CRE"],
                    label="Target pathogen"),
        gr.Dropdown(choices=["β-lactam", "FQ", "macrolide", "AMP", "novel"],
                    label="Target chemical class"),
        gr.Slider(1, 20, value=5, label="Number of candidates"),
    ],
    outputs=gr.Gallery(label="Top candidates with safety + clinical context"),
    title="Lysos — Generative AMR Drug Design",
    description="Powered by AMD MI300X. Built for the AMD Developer Hackathon 2026.",
)
demo.launch(server_name="0.0.0.0", server_port=7860)
```
