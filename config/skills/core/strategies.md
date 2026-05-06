---
slug: core/strategies
loaded: always
---

# Design strategies — how to win

These are the meta-patterns the agent should bias toward. Not rules, not
rigid templates — heuristics for "what to try first."

## 1. Starting strategies

When the user gives you a target (pathogen + optional target enzyme):

1. **Resistome first.** `/resistance <pathogen>` — know what mechanisms
   you're up against before designing.
2. **Look at what already works.** `/find_active_against_mdr` —
   shortlist of known actives. Even if you "design from scratch", the
   active set defines the chemical space.
3. **Pocket class hint.** `/explain` an exemplar known-drug to seed
   the pocket class for `/design`.

## 2. Editing strategies

When you have a candidate and want to improve it:

1. **Pareto-axis-aware editing.** Run `/score`, find the lowest axis,
   pick a transform that targets it.
   - Low QED → `add_hydroxyl`, `remove_methyl`, `ring_close`.
   - Low synthesizability → `swap_chloro_to_fluoro`, simplify scaffold.
   - High hemolysis risk → reduce log P (`add_hydroxyl`, `add_amine`),
     replace lipophilic tail.
   - Low novelty → `/scaffold-hop` (bigger move).
2. **Always score before AND after.** Net delta is the only honest
   metric. Loss in one axis can be acceptable if gain elsewhere
   dominates the composite.
3. **Branch before risky moves.** A scaffold-hop + add-sulfonamide
   chain can wreck the candidate. Branch the parent so you can A/B.

## 3. Resistance-aware design

The whole point of Lysos: candidates that **escape** known resistance.

1. For β-lactams targeting MRSA: prioritize binding to **PBP2a** allosteric
   site (ceftaroline-style C3 substituent). Design from
   `propose_pocket_aware --pocket PBP_active_site` then
   `predict_complex_structure target=PBP2a`.
2. For ESBL-producers (E. coli CTX-M, K. pneumoniae KPC): pair the
   candidate with a β-lactamase inhibitor mentally. Score the
   stand-alone candidate but expect deployment with avibactam /
   tazobactam.
3. For MRD Acinetobacter / Pseudomonas: siderophore conjugation
   (cefiderocol-style). Resistance still rare, opportunity for novel
   scaffolds.
4. **Avoid**: scaffolds where resistance has been observed in <5 years
   without an obvious workaround (sulfa target = DHFR mutations are
   trivial to evolve; just adding a fluoroquinolone doesn't help).

## 4. Evaluation strategy

Once you have a top-3 set:

1. **Composite + Pareto plot** in the right panel. Show the trade-offs
   visually.
2. **Resistance-escape predictor** (`predict_resistance_escape`) for
   the top candidate.
3. **Boltz-2 pose** for the top candidate vs the target — the right
   panel shows the 3D scene.
4. **Synthesis route preview** (`predict_synthesis_route`) —
   show the user the cost and step-count trade-offs.

## 5. When stuck

If 5+ edits don't improve composite:

1. **Pivot scaffold.** `/scaffold-hop --n 8`. Sometimes the local
   minimum is too small.
2. **Re-read the resistome.** Maybe you're missing a key escape.
3. **Branch to a peptide.** Many AMPs out-perform small molecules on
   MDR Gram-negatives.
4. **Ask the user**: "I'm at a local minimum on this scaffold. Want
   to scaffold-hop, branch to a peptide, or change target?"

## 6. Communication strategy

1. **Lead with the score.** "Composite 1.13. Up from 0.82."
2. **Show the diff.** "Added -OH at C5; QED 0.41 → 0.58 (+0.17),
   hemolysis 0.61 → 0.71 (+0.10), MIC unchanged."
3. **Offer the next move.** "I can `/scaffold-hop` for novelty
   (+0.15-0.30 expected), or `/predict_synthesis_route` to check
   feasibility."
