# Lysos Playground — The Right-Side Brainstorm

> **Vision**: the right side becomes THE drug-design playground. An
> infinite zoomable whiteboard with multiple specialized windows — 3D
> molecule theater, 2D builder, chemistry rules, reward radar, resistance
> map, agent reasoning trace — that the agents *and* the user co-edit
> atom by atom.

---

## 1. Why this is the right move

Drug design is **not a chat problem**, it's a **spatial problem**.
Atoms have valences. Bonds have geometries. Pockets have shapes.
Reward axes have tradeoffs. Resistance has a topology. None of this
fits in a linear chat scroll.

What we have now (right pane = tabs):
- Radar / Pareto / Synth / Lineage / Graph / Artifact
- Each tab is full-screen, mutually exclusive
- 3D viewer is in a separate vertical pane above
- No spatial relationship between them
- No infinite canvas, no multi-window co-presentation

What the user is asking for (right pane = playground canvas):
- **Single infinite canvas** with `zoom + pan` (Claude.ai design / Figma / Excalidraw / tldraw model)
- **Windows inside it** that float, snap, resize, cluster
- **3D / 2D / metrics / reasoning** all visible at once
- **Atoms and bonds are first-class** — drag them, watch valences highlight, see what can attach where
- **Real-time chem data modeling** — not LLM text alone, but periodic-table + bond-graph + 3D conformer pipelines that the agent/user manipulate
- **The agent's reasoning manifests visually** — when Designer proposes adding -OH, you SEE the atom appear, the bond form, the radar shift, the resistance probability tick up

---

## 2. The 10 candidate windows (pick the right 4-5 for hackathon)

| # | Window | What it shows | Why it matters | Tier |
|---|---|---|---|---|
| **W-1** | **3D Molecule Theater** | Protein pocket + ligand + interaction vectors (H-bonds, π-stacks, salt bridges) | The ground-truth visualization. NGL exists; deepen it. | T1 |
| **W-2** | **2D Atom Builder** | RDKit-rendered 2D structure with click-to-edit atoms; periodic-table palette; bond tool | Atom-by-atom editing the user can DO; mirrors what backend `/molecule/edit` already supports | T1 |
| **W-3** | **Live Reward Radar** | 12-axis spider chart updating in real time as the molecule changes; sparklines of each axis over edit history | Shows the agent's reasoning manifested as numbers; tradeoff visualization | T1 |
| **W-4** | **Agent Reasoning Trace** | Per-agent sticky notes that update as Designer/Critic/Editor speak; arrows showing dependencies | Makes the multi-agent debate spatial instead of buried in the chat scroll | T1 |
| **W-5** | **Chemistry Knowledge Card** | Click any atom → popover showing valence, possible bonds, common functional groups that attach there, known SAR for the position | The chem-rules engine the user said is missing; turns the playground into a tutor as well as a builder | T1 |
| **W-6** | **Resistance Map** | Pathogen-specific gene network (mecA, KPC, NDM, OXA family, efflux pumps, vanA/B). Clicking a gene shows which scaffolds it defeats. | The whole reason for AMR-targeted design — visualize escape | T2 |
| **W-7** | **Synthesis Route Tree** | Retrosynthetic decomposition tree with cost/availability badges per starting material | Decoupled from design-time loop; shipping reward only | T2 |
| **W-8** | **Comparator (N-candidates)** | Side-by-side 3D pose overlay + radar + scaffold tree; existing `/compare` data feeds it | Already shipped as chat card; promote to a window | T2 |
| **W-9** | **Replay Scrubber** | Timeline of every event in the session; drag a slider to re-watch | Already shipped via SSE; promote to canvas as a play/pause/scrub UI | T2 |
| **W-10** | **Permutation Explorer** | Pick an atom → see ALL k mutations side-by-side; click one to commit | Visualizes the SAR space; complements `/sar` slash | T2 |

**Hackathon scope: T1 (windows 1-5).** Five windows is enough to demonstrate
the playground concept. T2 is post-hackathon polish.

---

## 3. Canvas mechanics (the "whiteboard" itself)

The infinite canvas needs:

| Capability | What it does | How |
|---|---|---|
| **Pan** | drag the empty canvas to move the viewport | mouse-down on canvas bg → translate `transform: translate(x,y)` |
| **Zoom** | wheel + cmd-zoom shortcuts | `transform: scale(z)` on the inner stage with origin at cursor |
| **Window drag** | grab a window's title bar to move it | `framer-motion drag` constrained to canvas |
| **Window resize** | corner / edge handles | custom or `react-rnd` |
| **Snap-to-grid** | windows snap to 8px grid when dropped | round-to-grid on dragend |
| **Layouts (save/load)** | named layouts (e.g. "Design", "Compare", "Replay") | localStorage keyed by layout name |
| **Mini-map** | bottom-right thumbnail showing all windows + viewport rect | scaled-down render of window bboxes |
| **Multi-select** | shift-click windows to move/style as a group | selection state |
| **Z-order** | last-clicked window on top | z-index sort |
| **Window header** | title + close + minimize + maximize + drag handle | shared `<PlaygroundWindow>` component |

For hackathon: **Pan + Zoom + Window drag + Window resize + 1 saved layout** is enough.
Snap, mini-map, multi-select, layouts catalog are post.

**Library choice**: Build it ourselves with framer-motion + Allotment-as-fallback, OR adopt:
- `react-zoom-pan-pinch` — simple pan+zoom on a child container
- `react-rnd` — single-component drag+resize wrapper
- Combine: outer = `react-zoom-pan-pinch` on a stage; each window = `react-rnd` inside

Custom-built gives full control + no third-party CSS leaks. Wraps to ~150 LOC.

---

## 4. The chem-data layer the user is asking for

> "the system is about knowledge and knowing of the atoms and their binds
> with one another and the making like permutation and combinations"

Right — agents currently produce SMILES from LLM intuition. We need a
**chemistry rules engine** the agents (and UI) consult.

### What the rules engine answers

| Q | Backend resolves via |
|---|---|
| What atom can I attach here? | RDKit `GetAtomWithIdx().GetTotalNumHs()` + valence rules |
| What bond order is allowed? | RDKit `BondType` constants per element pair |
| Is this scaffold valid? | `Chem.SanitizeMol` + structural alert SMARTS |
| What known antibiotics share this substructure? | Tanimoto over our 30K-fingerprint reference set |
| What SAR is documented at this position? | Curated 387-drug pharma corpus (named_drug_examples) |
| Will the molecule fit the pocket? | Boltz-2 ipTM/pTM (already wired) |
| Will it be hydrolyzed by KPC? | Curated β-lactamase substrate scope tables |
| ADMET liabilities? | TDC predictors + OpenADMET grounding |

### New endpoint — `GET /workbench/chem/atom/{smiles}/{atom_idx}`
Returns:
```json
{
  "element": "C",
  "valence": 4,
  "n_hydrogens": 2,
  "is_aromatic": false,
  "in_ring": true,
  "ring_size": 6,
  "neighbors": [{"idx": 1, "bond": "single", "element": "C"}, …],
  "allowed_attachments": [
    {"atom": "F", "bond": "single", "label": "+F"},
    {"atom": "O", "bond": "single", "label": "+OH (via O-H)"},
    {"atom": "N", "bond": "single", "label": "+NH2"},
    {"functional_group": "carboxyl", "label": "+COOH"},
    …
  ],
  "sar_notes": [
    {"drug": "ciprofloxacin", "position": "C6", "effect": "+F at C6 boosts gyrase affinity 4×"},
    …
  ]
}
```

This becomes the **2D Builder window's** click-an-atom popover. Also
becomes a tool the agents can call (`get_atom_context` slash). The
agents stop hallucinating chemistry — they query the rules.

### New endpoint — `GET /workbench/chem/permutations/{smiles}/{atom_idx}?k=10`
For the **Permutation Explorer window**: returns the top-k structurally
valid mutations at that atom, each pre-scored. Reuses W3 SAR backend.

---

## 5. Software architecture pivot

### Current layout
```
Allotment(horizontal)
├── ChatPane (left, 38%)
├── MidPane (center, 38%)
│   └── Allotment(vertical)
│       ├── Mol3D
│       └── (drag-edit + 2D + mech panels)
└── RightPane (right, 24%)
    └── TabStrip [Radar | Pareto | Synth | Graph | Lineage | Artifact]
```

### New layout
```
Allotment(horizontal)
├── ChatPane (left, 35%)
└── PlaygroundCanvas (right, 65%)            ← the whole thing is one canvas
    ├── PanZoom outer stage
    └── inside the stage:
        ├── Mol3DTheaterWindow                (W-1)
        ├── Mol2DBuilderWindow                (W-2)
        ├── RewardRadarWindow                 (W-3)
        ├── AgentReasoningTraceWindow         (W-4)
        ├── ChemKnowledgeCardWindow           (W-5, popover-modal)
        └── (T2 windows on demand)
```

The center pane (3D + drag-edit + tabs) **collapses into the canvas as windows**.
The left chat pane stays. The top header stays. Two-way split is the user's
spec ("two way broken — left side chat, right side has the 3D and 3D and
all such new work and simulation metrics").

### State that has to move
- `currentSmiles` was Mol3D-local; now lives at canvas-state level
- `events`, `lastScores`, `bestScores` were ChatPanel-driven; the
  RewardRadarWindow subscribes to the same source
- `artifactDoc` already shared; promote to canvas-state
- New: `windowLayout` = map of windowId → {x, y, w, h, z, visible, minimized}
- New: `viewport` = {pan: {x,y}, zoom: number}

### Component tree
```
<PlaygroundCanvas>
  <PanZoomStage viewport={…} onViewportChange={…}>
    <PlaygroundWindow id="3d" {...layout["3d"]}>
      <Mol3DTheaterWindow {...} />
    </PlaygroundWindow>
    <PlaygroundWindow id="2d" {...layout["2d"]}>
      <Mol2DBuilderWindow {...} />
    </PlaygroundWindow>
    <PlaygroundWindow id="radar" {...layout["radar"]}>
      <RewardRadarWindow {...} />
    </PlaygroundWindow>
    <PlaygroundWindow id="agents" {...layout["agents"]}>
      <AgentReasoningTraceWindow {...} />
    </PlaygroundWindow>
  </PanZoomStage>
  <Minimap windows={layout} viewport={viewport} />
  <CanvasToolbar
    onAddWindow={(kind) => …}
    onSaveLayout={…} onLoadLayout={…}
    onResetViewport={…}
  />
</PlaygroundCanvas>
```

`<PlaygroundWindow>` is the shared chrome — title bar with close /
minimize / maximize, drag handle, resize corners, body slot. Every
specific window reuses it.

---

## 6. The agent's view of the playground

The agents already produce SMILES + score + critique. To make the
playground feel **alive**, route their actions to canvas events:

| Agent action | Canvas effect |
|---|---|
| Designer proposes a SMILES | 2D builder snaps to it; 3D theater fades in the new pose; radar tweens to new scores |
| Critic identifies WEAKNESS axis | The corresponding axis on the radar pulses red |
| Critic suggests a TRANSFORMATION | The 2D builder highlights the target atom in amber; a "ghost" atom shows the proposed addition |
| Editor applies the transform | 2D builder commits the change; 3D rebuilds; radar re-tweens |
| Strategist decides TERMINATE | Reward radar gets a "frozen" badge; final composite shown big |
| User clicks an atom in 2D builder | `get_atom_context` fires; chem knowledge card pops up at cursor |
| User commits an edit | Chat panel gets a new agent_message ("user edited C6 → +F"); agents react |

This is **bidirectional**. The agents drive the canvas; the user drives
the agents through canvas edits. That's the "co-build atom by atom"
the user described.

---

## 7. Hackathon scope — what we ship in this sprint

**Phase 1 (this push, ~6h work):**
1. New `<PlaygroundCanvas>` component replacing the right-pane tab strip
2. Pan + zoom (`react-zoom-pan-pinch` or hand-rolled)
3. `<PlaygroundWindow>` shared chrome (title, drag, resize, close, minimize)
4. **3 starter windows** wired with existing data:
   - **W-1 Mol3DTheater** — port existing Mol3D into a window
   - **W-3 RewardRadar** — port existing RadarPanel into a window
   - **W-4 AgentReasoningTrace** — per-agent sticky notes from the events stream
5. Default layout: 3D top-left (60% w / 60% h), Radar top-right, Agents bottom-spanning
6. Drop the right-pane tab strip entirely (Pareto / Synth / Graph / Lineage / Artifact become windows on demand later)

**Phase 2 (next, ~4h):**
7. **W-2 Mol2DBuilder** — RDKit-served 2D SVG, click-an-atom popover
8. **W-5 ChemKnowledgeCard** — backend `/chem/atom/{smiles}/{idx}` endpoint
9. Agent → canvas event router (when Designer emits SMILES, all windows update)
10. Save/load layouts (localStorage)

**Phase 3 (post-hackathon):**
11. Remaining T2 windows (Resistance Map, Synthesis Tree, Comparator, Replay, Permutation Explorer)
12. Mini-map, multi-select, layout catalog
13. Real-time conformer ensemble in the 3D theater
14. Agent reasoning trace as flowchart instead of sticky notes

---

## 8. Open questions for the user

1. **Library**: build pan-zoom ourselves, or use `react-zoom-pan-pinch`?
   Recommendation: **build ourselves** — 150 LOC, no CSS leaks, works
   with our existing Allotment outer split.
2. **Default canvas size**: 4000×3000px viewport? Or unbounded?
   Recommendation: **unbounded**, with a "frame" layer at 4000×3000
   that windows snap to.
3. **Window persistence**: per-chat-tab layouts (so each session can
   have its own arrangement) or per-project (one layout for all chats)?
   Recommendation: **per-chat-tab**, stored alongside `chatTabs[]`.
4. **Center-pane fate**: do we collapse the existing center pane (3D
   + drag-edit + 2D + mech) entirely into the canvas, or keep a
   compact center as a "primary 3D" while canvas holds expanded windows?
   Recommendation: **collapse fully** — single playground feels more
   Claude-artifacts-like. Two competing 3D viewers is confusing.
5. **Mobile / narrow chats**: at <800px viewport, fall back to the
   current tab UI? Or always playground?
   Recommendation: **playground always**, but auto-zoom-to-fit so
   one window fills the viewport on narrow screens.

**Locked-in default**: items 1, 2, 3, 4, 5 → adopt my recommendations
unless the user objects.

---

## 9. Why this wins the hackathon

| Other AI drug tools | Lysos with playground |
|---|---|
| Chat-only output, no spatial reasoning | Infinite canvas with co-located 3D/2D/metrics/reasoning |
| Static views, one at a time | Multi-window simultaneous; pan/zoom freely |
| Read-only outputs | User edits atoms; agents react in real time |
| LLM hallucinates chemistry | Chemistry rules engine consulted by agents + UI |
| Single composite score | Per-axis live radar with sparklines |
| Black-box reasoning | Agent reasoning trace window with per-agent state |

This is what makes the demo unforgettable: judge clicks an atom on the
2D structure → chemistry card pops up showing valence + allowed
attachments + SAR notes → judge picks "+F" → 2D updates → 3D fades to
new pose → radar tweens to new scores → Critic in the agent trace
window says "WEAKNESS: solubility — try +OH instead". All on one
canvas, all simultaneously, all driven by the same MI300X-trained
policy.

That's the playground. That's the win.
