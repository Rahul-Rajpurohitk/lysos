---
slug: scenarios/design
loaded_when: "user intent is one of: design, propose, generate, create, suggest, find, explore"
---

# Scenario: Design

User wants new candidate molecules. Default workflow.

## Steps

1. **Resolve target** — pathogen + optional structural target.
   - If user said "MRSA": pick PBP2a as default target (PDB 4DKI).
   - If user named both pathogen and target enzyme: use it.
   - If only enzyme name: ask which pathogen context.
2. **Resistome scan** — `/resistance <pathogen>` → know what mechanisms
   the candidate must escape.
3. **Pocket-aware proposal** — `/design <pathogen>` → 8 candidates from
   `propose_pocket_aware` seeded by the relevant pocket class.
4. **Score all** — `/score` each, build a Pareto plot in the right
   panel.
5. **Pick top 3** — by composite, OR by Pareto-front membership if
   multi-objective is salient.
6. **Critique top 1** — Critic agent picks weakest axis.
7. **Edit top 1** — `/edit <op>` targeting that axis.
8. **Re-score** — confirm the edit improved net composite.
9. **Optional: scaffold-hop** — for novelty boost.

## Output to user

Top 3 panel + brief rationale per candidate. Each row:
- SMILES + 2D structure
- composite + breakdown bars (which axes drive the score)
- "Edit history": op chain from `propose` to current
- One-click `/branch`, `/edit`, `/score` follow-ups
