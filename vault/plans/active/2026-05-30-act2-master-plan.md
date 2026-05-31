# Lysos — AMD Developer Hackathon ACT II — Master Plan

> Created 2026-05-30 · Build window ~May 30 → July 6 · Submissions July 6–11
> Team: 3 members · $100 AMD Developer Cloud credits each ($300 MI300X total)
> Prize pool $10K ($5K / $3K / +). Submissions must be MIT-licensed + original.

---

## 0. The thesis (why we win)

**Act I = prototype.** Heuristics + Gemini wrapper, good UI, but the science
numbers were physchem rules and the "AMD" story was thin (we trained one
adapter). A domain person could tell it was a demo.

**Act II = the open antibiotic foundry that actually runs on AMD.**
We replace heuristics with *real, peer-reviewed open-source models* and
**serve all of them on MI300X**. Every number becomes defensible, and the
AMD GPU story becomes the spine of the product, not a footnote.

Three things judges at an *AI-agents-on-AMD* hackathon reward, and how we hit each:
1. **Real GPU workload on MI300X** → we host Chemprop/ADMET-AI ensembles +
   GenMol generation + our Lysos-DPO model via vLLM-ROCm, with a published
   benchmark (throughput/latency/$ per 1k molecules on MI300X).
2. **Genuine agentic system** → planner→executor→verifier harness running a
   full autonomous *campaign* (design → make → test → IP → ADMET → decide),
   multi-agent debate visible, every proposal one-tap applyable.
3. **Real product, real domain value** → cleaned, trustworthy, med-chemist-
   grade UI with retrospective validation (does it rank known actives high?),
   honest labeling, citations, and an export a real team would use.

Positioning line: **"Lysos turns one prompt into a validated antibiotic
campaign — real open-source models, running on AMD MI300X, driven by agents."**

---

## 1. Open-source integrations (the heart of the 10x)

All MIT/Apache or compatible — verify license per repo before merging.

| Project | Repo | Role in Lysos | Runs on MI300X? |
|---|---|---|---|
| **Chemprop v2** | github.com/chemprop/chemprop | Property-prediction backbone (MPNN+RDKit) | Yes (PyTorch/ROCm) |
| **ADMET-AI** | github.com/swansonk14/admet_ai | Real 41-endpoint ADMET (TDC) → replaces our heuristics | Yes |
| **SyntheMol** | github.com/swansonk14/SyntheMol | Synthesizable generative engine (MCTS over Enamine REAL) | CPU-heavy + GPU scoring |
| **GenMol** | github.com/NVIDIA-Digital-Bio/genmol | Discrete-diffusion de-novo + lead-opt (SAFE) | Yes (diffusion on GPU) |
| **TDC** | tdcommons.ai | Dataset layer + benchmark groups (validation) | n/a |
| **CARD** (expand) | card.mcmaster.ca | Resistance panel — grow beyond current subset | n/a |
| *(optional)* **ApexAmphion / Amphorium / LLAMP** | GIST-CSBL/LLAMP | Antimicrobial-PEPTIDE modality + 2.1M open library | Yes (pLM+RL) |

**Decision — small-molecule first.** Adopt Chemprop+ADMET-AI (prediction),
GenMol (generation), SyntheMol (synthesizability) as core. **Peptides
(ApexAmphion/LLAMP) = stretch goal / second track** — only if Phase 1–3 land
early. Reason: peptides are a separate pipeline (no overlap with our β-lactam
small-molecule stack); doing both risks half-finishing both.

**Decision — orchestration stays hybrid.** Keep Gemini Pro/Flash for the
agent *reasoning* (cheap, fast, reliable), but the *scientific compute*
(prediction, generation, our domain LM) runs on MI300X. This is honest and
keeps the AMD workload real where it matters. If credits/time allow, also
serve Lysos-DPO on MI300X via vLLM and route the Designer/Critic roles to it
for the "fully on AMD" narrative.

---

## 2. The compute plan ($300 MI300X / ROCm)

One always-on **Lysos Inference Service** on AMD Developer Cloud (FastAPI +
ROCm PyTorch) hosting:
- Chemprop/ADMET-AI ensemble (batched SMILES → 41 ADMET endpoints + antibacterial-activity head)
- GenMol generation endpoint (de-novo + fragment-constrained + lead-opt)
- (stretch) Lysos-DPO via vLLM-ROCm for Designer/Critic roles
- A `/benchmark` route that records throughput + latency for the submission

Budget discipline: spin up only for (a) batch jobs, (b) the benchmark, (c)
demo + judging window. ~Most of the $300 goes to GPU hours here. Keep a
CPU/local fallback path so the product never hard-depends on a live GPU
during dev. Document spend in `vault/decisions/`.

---

## 3. Productization gaps to kill (the "not satisfied" list)

Honest audit of what makes it still feel like a demo:
- **Heuristic science** → fixed by §1 (real models).
- **Stale-artifact / half-render bug class** → we patched Synthesis+IP+ADMET
  client-side; needs a *global* solution: a `useArtifact` hook + shared
  non-drug/validity gate + skeleton/empty/error states for EVERY card.
- **No unifying object** → introduce a first-class **Campaign**: a goal
  (pathogen + objective) that owns candidates, runs, dossiers, and a decision
  log. Everything hangs off a campaign. This is the productization backbone.
- **Visuals not domain-grade** → design-system pass (tokens, spacing,
  typography), real molecule rendering everywhere (we have Mol2DThumb now),
  publication-quality charts, a clean campaign board.
- **No trust signals** → retrospective validation page, model cards +
  citations per service, confidence + provenance on every number.
- **Onboarding** → a guided first-campaign flow so a new med-chemist gets to
  "wow" in <2 min.
- **Export** → a real campaign report (PDF + shareable link) a team would
  circulate.

---

## 4. Agentic depth — the autonomous campaign

The headline demo: type *"find me a novel, synthesizable, safe lead against
MRSA"* → the agent runs a **planner→executor→verifier** loop end-to-end:
1. **Plan** — Orchestrator decomposes into steps, shows the DAG.
2. **Generate** — GenMol/SyntheMol propose N candidates on MI300X.
3. **Score** — Chemprop/ADMET-AI rank them (real models).
4. **Debate** — Designer/Critic/Editor/Strategist argue the top-K.
5. **Gate** — Synthesis route + IP/FTO + ADMET run per finalist.
6. **Verify** — adversarial verifier re-checks claims before they're shown.
7. **Decide** — Strategist writes the campaign decision + dossier; proposals
   are one-tap applyable.

This is the difference between "5 services" and "an agent that runs a
discovery campaign." Same services, but composed and autonomous.

---

## 5. Phased timeline (~5 wks) + 3-person split

**Roles** (confirm/override):
- **M1 — ML/GPU (MI300X)**: inference service, model integration, vLLM-ROCm
  serving, benchmark, retrospective validation. Owns most of the $300.
- **M2 — Backend/agents**: planner-executor-verifier harness, Campaign
  object, service↔model wiring, dossier, reporting/export, data layer.
- **M3 — Frontend/design/product**: design-system pass, global card states,
  Campaign board, validation dashboard, onboarding, demo polish.
- **Shared**: demo storyline, pitch deck, video (last week).

### Phase 0 — Foundations (Wk 1: May 30 – Jun 6)
- M1: stand up AMD Dev Cloud box; ROCm PyTorch; get Chemprop + ADMET-AI
  running on MI300X; first `/predict` endpoint live + smoke benchmark.
- M2: introduce the **Campaign** model (DB + API); refactor services to read
  the campaign; design the planner-executor-verifier interface.
- M3: design-system tokens + the global `useArtifact`/card-state primitives;
  kill the stale/half-render class everywhere; Campaign board shell.
- Gate: real ADMET numbers replacing heuristics in the ADMET card.

### Phase 1 — Real models in the loop (Wk 2: Jun 6 – 13)
- M1: GenMol generation endpoint on MI300X; SyntheMol synthesizability;
  ensemble + antibacterial head; batch scoring.
- M2: wire generation→scoring→services into the campaign; best-of-N.
- M3: candidate board with real structures + live ranking; service cards
  consume real-model outputs with provenance.
- Gate: type a goal → get GenMol candidates scored by Chemprop, ranked.

### Phase 2 — Autonomous campaign + verifier (Wk 3: Jun 13 – 20)
- M2: planner→executor→verifier harness; the full design→make→test→IP→ADMET
  →decide loop runs autonomously; adversarial verification of claims.
- M1: (stretch) serve Lysos-DPO via vLLM-ROCm; route Designer/Critic to it.
- M3: live campaign run visualization (DAG + agent debate + streaming);
  decision log + dossier UI.
- Gate: one prompt → a complete autonomous campaign with a defensible result.

### Phase 3 — Trust + productization (Wk 4: Jun 20 – 27)
- M1: retrospective validation (does Lysos rank known actives high? enrichment
  curve vs CARD/ChEMBL actives) + the MI300X benchmark writeup.
- M2: campaign report export (PDF + shareable link); model cards + citations.
- M3: onboarding flow; validation dashboard; design polish pass; empty/error
  states audited; mobile/responsive sanity.
- Gate: validation page shows real enrichment; a new user reaches "wow" fast.

### Phase 4 — Demo + submit (Wk 5: Jun 27 – Jul 6, submit Jul 6–11)
- Freeze features Jul 1. Bug-bash, perf, polish.
- Demo video (the autonomous MRSA campaign, end-to-end, on MI300X).
- Pitch deck + README + architecture diagram + benchmark + validation.
- Public repo MIT-clean; HF model card; deploy a live link.
- Submit. Watch lablab for the final rubric and tune the submission to it.

---

## 6. Submission checklist (build toward, refine when rubric drops)
- [ ] Working deployed app (live link)
- [ ] Public MIT repo, clean history, README + architecture diagram
- [ ] MI300X usage documented + benchmark numbers
- [ ] Demo video (≤ the limit they set) — the autonomous campaign
- [ ] Pitch deck
- [ ] HF model card (Lysos-DPO) + cited open-source models
- [ ] Retrospective validation results
- [ ] Honest-scope statement (decision-support, not wet-lab-validated)

## 7. Risks
- **Rubric unknown** → monitor lablab page weekly; design submission modular.
- **MI300X/ROCm friction** (deps, GenMol/Chemprop on ROCm) → spike in Wk 1;
  CPU fallback so dev never blocks.
- **Scope creep (peptides)** → gated to stretch only.
- **$300 burn** → batch + scheduled spin-up; track spend.
- **Over-claiming** → validation + honest labels are non-negotiable.

## 8. Open decisions (recommend → confirm)
1. Small-molecule first, peptides as stretch — **recommend YES**.
2. Hybrid orchestration (Gemini reason + MI300X compute), DPO-on-MI300X as
   stretch — **recommend YES**.
3. Team skill split (who is M1/M2/M3) — **needs your input**.
