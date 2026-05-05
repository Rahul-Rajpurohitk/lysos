---
title: Lysos Workbench
emoji: 🧬
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 4.40.0
app_file: app.py
pinned: true
license: cc-by-4.0
short_description: AI antimicrobial drug-design system on AMD MI300X
---

# Lysos — AI Antimicrobial Drug-Design Workbench

Open-source generative drug-design system specialized for antimicrobial
resistance (AMR), built on Gemma 4 with manually-authored teacher
distillation across 7 layers + 12-component GRPO reward stack on AMD
MI300X.

Targets the 8 WHO-priority pathogens. Pivots AROUND first-line therapy
classes to reduce cross-resistance pressure.

## Architecture

- 4 first-class agents (Designer, Critic, Strategist, Editor)
- 9 scoped sub-agents (Red-Team, Resistance-Forecaster, Manufacturing-Eval,
  Clinical-Positioning, Literature-Grounding, Confidence-Calibrator,
  Novelty-Checker, Editor, Critic-Novelty)
- 25-tool Workbench: amr (5) + scoring (6) + structural (3) +
  generative (4) + knowledge (5) + sandbox (2)
- 12-component GRPO reward stack
- 7-metric quantitative leaderboard

## Links

- [GitHub repo](https://github.com/Rahul-Rajpurohitk/lysos)
- [Methods paper](https://github.com/Rahul-Rajpurohitk/lysos/blob/main/docs/methods_paper.md)
- [Datasheet](https://github.com/Rahul-Rajpurohitk/lysos/blob/main/docs/datasheet.md)
- [Lysos-RL model](https://huggingface.co/rahul24raj/lysos-rl)
- [Pro-v12 dataset](https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2-pro-v12)

## Submission

AMD Developer Hackathon — May 2026 (lablab.ai). Track 2: Fine-Tuning on
AMD MI300X. Eligible for Grand Prize + HF Most-Liked Space stack.

## Out-of-scope

This Space cannot design chemical weapons, controlled substances, or
biological agents. Refusal training uses abstracted category tokens only — every safety_refusal
row in the corpus uses `<CWC_*>`, `<CDC_TIER_*>`, `<DEA_SCHEDULE_*>`
tokens, never literal harmful names.

## License

Code: MIT. Data + model: CC-BY-4.0 with attribution. See LICENSE.
