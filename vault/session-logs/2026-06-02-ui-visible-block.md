# Act II — visible UI block (2026-06-02)

User pushed back: "not much happening in the UI, no clean work, I asked for
advanced-to-advanced." Right — I'd been trusting tsc instead of SEEING it.
This block got eyes on the running app (isolated puppeteer browser, no lock)
and did genuinely visible work.

## Verified on-screen (screenshots), committed + pushed
1. **Candidate Cockpit** (CandidateCockpit.tsx) — dense live-vitals hero at
   top of the Chemistry column. On every SMILES change, fires the FAST real
   engines and shows structure + composite reward + antibacterial prior +
   synth accessibility + ease-of-synthesis bar. VERIFIED live: acetaminophen
   → 0.54 / 0.93 likely-active / SA 1.4 easy / 96%. Kills the "tiny molecule
   in white space, nothing happening" top-of-column problem.
2. **uiPrimitives.tsx** — shared aligned building blocks (StatTile, MetricBar,
   BandPill, ProvenanceBadge, SectionLabel, EmptyState) + canonical band→colour
   map. The single source that fixes "every card invents its own markup".
3. **ResistomeCard** — AMR-landscape frontend (was invisible backend).
4. **2D builder molecule sizing** — viewBox pad 20%→6% so the molecule FILLS
   its canvas; card height 540→420. VERIFIED: acetaminophen now renders large.

## Known remaining UI issues (honest)
- 2D builder canvas is very WIDE (1664×347, 4.8:1) so the molecule scales to
  the short side and leaves horizontal space. This is a card grid-ratio issue,
  not the molecule. Needs the 2D card to be narrower or the host aspect capped.
- Cockpit 3rd tile clips at 1440px viewport (fine at full width — responsive
  repeat(3,1fr)). Could wrap to 2-row on narrow.
- The broader design-system rollout (thread uiPrimitives through synthesis/
  IP/ADMET/generator/peptide cards) is still pending (#210).

## Ops lessons
- Port 5173 collided with another project ("The PhD Journey") — relaunch lysos
  vite with --strictPort. EPIPE crash on browser disconnect is harmless.
- Use puppeteer (isolated) when the playwright browser is locked. NEVER touch
  the user's browser.

## Fleet status: 9 real engines, cockpit + resistome now visible.
