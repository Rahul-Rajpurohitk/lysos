# Lysos Workbench v0.3 — Agentic UI/UX Overhaul Brief

> Captured from Rahul's voice prompts and the 10 screenshots stored under
> `docs/agentic_ui_screenshots/`. Cleaned grammar, kept all original
> intent, organised by surface area. This is the next major build.
>
> **Stance**: this is a hackathon-winning product, not a college project.
> No compromise on UI/UX, end-to-end backend wiring, real functionality,
> or scalability. Meta-engineering and meta-design to the core.

---

## 0. Mission frame

The Workbench is the visible front of Lysos. The judges will see this
*before* they see the trained model. It must:

1. Communicate **agentic depth**: the Designer / Critic / Editor /
   Strategist / sub-agents are doing real reasoning, not chat-cosplay.
2. Communicate **molecular depth**: every change to the molecule (functional
   groups, atomic edits, ring transforms) is reflected in real time on
   the 3D protein binding view, the 2D structure, and the reward radar.
3. Be **end-to-end real**: nothing mocked. The buttons, sliders, drag-edit
   chips, and constraint chips all wire to live FastAPI endpoints, which
   in turn drive the LysosGenerator + reward stack + tool registry.
4. **Scale**: the layout has to absorb new agents, new tool palettes, new
   panel types without breaking. Group-by-feature, not
   group-by-was-there-first.

---

## 1. Top header (replaces the current bulky bar)

**Reference screenshot**: `10_top_header_bulky.png`

**Current pain (verbatim from voice)**:
> "the main top thing it is bad and ugly bruh and the buttons and the
> spacing and the bulkyness and bad UI/UX and one backend and end-to-end
> work and functionalities and broken completely. Cmon get heavy and
> start arranging and the grouping of the features."

**Requirements**:

- One single line, dense but breathable, **height ≤ 56 px**.
- Left cluster: brand mark + product name (`Lysos · Workbench v0.3`)
  with a subtle agent-badge ring around the logo when a session is active.
- Centre cluster, three pill-selectors:
  1. **Pathogen picker** with full Latin name + tier badge (critical/high)
  2. **Mode picker**: `Design`, `Discover`, `Repair`, `Robustify`
  3. **Autonomy picker**: `Co-pilot`, `Auto`, `Manual` (with iconography
      that explains itself; tooltip on hover for full description)
- Right cluster: `Iters` numeric input, `▶ Start` primary action,
  download (export session) and refresh (reset) ghost-icons.
- **Below the header**, replace the current "RESISTANCE 6 · FIRST-LINE 4
  · BEST 0.857 · PARETO 1" chip strip with a **single hairline summary
  ribbon** that shows: pathogen → status pip → composite gauge → pareto
  count → active agent indicators (animated when working). Remove the
  "session id" tag — surface it on hover only.

**Design tokens**:
- Header background: light glass on dark mode, hairline 1px border
- Pill height: 32 px, radius 10 px, hover lift 1 px
- Spacing: 12 px gap between pills, 24 px between clusters

---

## 2. Chat window — agentic conversation surface

**Reference screenshots**: `01_chat_stream_compact.png` and
`02_columns_debate_compact.png`

**Current pain**:
> "the columnar UI/UX can be done way way way better with a lot of
> reasoning and the work and features and the rendering work deeply.
> Don't make a school college project; this is a product, we're pitching
> in the hackathon and has the potential to win. Go hard and heavy on
> things, get the best of the best design and end-to-end backend."
>
> "internal chat window and the text size and font style, and the tokens
> and reasoning and all the rendering and proper staff-level work."
>
> "the iteration UI is too compacted; the chat window has to have better
> space, and with that the right bar that connects to the 3D and 2D
> containers, there can be a grip using which we can expand and compress
> the chat window in respect to the right side 3D and 2D containers."

**Requirements**:

### 2.1 Layout
- Three-column layout: **chat (resizable, default 38%)** + **3D viewer
  (always visible, default 38%)** + **2D viewer + tool panels
  (collapsible, default 24%)**.
- A **vertical drag-grip** between chat and 3D, and another between 3D
  and 2D. Cursor changes to `col-resize`. Persist user's split in
  localStorage. Min chat width 320 px; max chat width 720 px.
- The 2D + tool-panel column has a **collapse button** (chevron arrow);
  when collapsed it slides off-screen and the chat + 3D split 50/50.
  3D never collapses.

### 2.2 Mode toggle (Stream | Columns)
Already exists; keep it but redesign:
- Sticky to the top of the chat panel, not inside the scroll area.
- `Stream` = chronological agent messages with tool-call sub-cards.
- `Columns` = per-agent vertical lanes (Designer, Critic, Editor,
  Strategist + dynamically-spawned sub-agents).

### 2.3 Agent toolbar / icon row
The 5 colored agent chips at the top of the chat panel
(`A`, `□`, pencil, compass, person). Redo:
- Icons must be **legible**, with a **2px ring in the agent's color**.
- Hover surfaces a tooltip with the agent's role + last-active timestamp.
- Click filters the chat to that agent only (with a clear-filter chip
  that appears on the right).
- New: a **+** button to spawn a sub-agent (Red-Team,
  Resistance-Forecaster, Manufacturing-Eval, Clinical-Positioning, etc).
  Clicking it opens a 9-tile picker (the 9 sub-agents we have).
- A small **filter funnel icon** lets the user multi-select agents.

### 2.4 Message bubbles
- **Agent badge** (color-coded) + **agent name** + **timestamp** in a
  single 16 px-tall row.
- Body: 14 px font for paragraph text; 13 px monospace for SMILES /
  code; 12 px for tool-call argument JSON.
- Tool-call cards collapsed by default; show name + agent + duration +
  status pip. Click expands to show full args, response, and a "Re-run
  tool" button.
- **Reasoning rendering**: when an agent emits a `<thinking>...
  </thinking>` block (typical of reasoning models), render it
  collapsible, dimmer text color, italic, with a "thought 1/3" pager
  if the model emitted multiple thinking blocks.
- **Token / latency footer**: each message ends with a hairline showing
  `847 tokens · 1.2s · gpt-4o` (or the right model). Hidden by default,
  visible on hover.

### 2.5 Iteration markers
- Currently shows `ITERATION 1/4 ████ complete`. Keep the bar but
  upgrade:
  - It's a **horizontal segmented progress** (4 segments for 4 iters).
  - Segments turn green as completed, amber for in-progress, with a
    composite-score number floating above the active segment.
  - Click a segment to scroll the chat to that iteration's first message.

### 2.6 Composer (input)
- Currently shows "Composer activates while a session is running".
  Overhaul:
  - Always visible.
  - When a session is running, show subtle "intervene" mode:
    user typing injects a Strategist-level directive mid-loop.
  - When idle, prompt: "Describe a target… (e.g. *design a non-toxic
    macrolide for MRSA that escapes mecA*)".
  - **Slash commands**: `/constraint`, `/from-paper`, `/scaffold-hop`,
    `/clear`, `/branch` — pop a small autocomplete on `/`.
  - Push button on the right; keyboard shortcut Cmd-Enter.
  - **Voice button**: optional whisper-based dictation (icon, defer
    implementation; reserve the slot).

### 2.7 The 4 starter "intent" buttons (Design / Critic / Editor /
Strategist) currently sit at the top — confused with agent-filter pills.
Decision: **kill those**. Replace with a single command-line composer
(2.6 above). Agents activate based on the composer's intent, not on a
button click.

---

## 3. Right pane — 3D + 2D molecular workspace

**Reference screenshot**: `03_3d_2d_drag_edit.png`

**Current pain**:
> "The 3D and the 2D visuals and the breakdown of the molecules and the
> freedom of joining and building with the atoms and such for the
> discovery of the antibiotics as per the goal of the project, the
> complete end-to-end work, the formula-based changes and the changes
> in the protein accordingly."
>
> "Compress and expand bar between the 3D and 2D, and the collapsable
> button as well for the 2D, whereas 3D always stays in the picture."

### 3.1 3D viewer (top half, always visible)
- Base: `3Dmol.js` or NGL viewer (NGL is more modern; pick NGL).
- Header strip (currently has 5 buttons): keep the layout, fix density:
  - **Representation picker** (`Cartoon (T)`, `Surface`, `Sticks`,
    `Spheres`) — segmented control with active highlight.
  - **Wireframe toggle** (separate from representation; for the ligand).
  - **Pocket toggle** (highlights binding pocket residues, default ON).
  - **Spin** toggle (autorotates the camera).
  - **Recenter** action.
- **PDB code chip** (left): click to swap PDB; opens a search modal.
- **Ligand SMILES chip** (left, below PDB): click to copy.
- **Properties card** (bottom-left of the 3D canvas): formula, MW,
  logP, atom count, bond count, energy estimate, atom-type histogram.
  Reposition: it currently overlaps the canvas — move to a hairline
  bar **below** the 3D area, integrated with the 2D header.
- **Live updates**: when the user drags an atom or applies a
  transformation in the 2D viewer, the 3D pose recomputes (Boltz-2
  proxy or fast docking) and animates from old → new pose.

### 3.2 2D structure viewer (collapsible bottom half)
- Header: `2D STRUCTURE [SMILES]` + `Mechanism` action.
- Body: RDKit-rendered SVG of the current candidate.
- **Drag-edit chips row** (currently a long row of `-OH`, `-F`, `-CH3`,
  `-NH2`, `-COOH`, `-SO2NH`, `Cl→F`, `F→Cl`, `-CH3`, `ring`):
  - Group them: **Add**, **Remove**, **Swap**, **Ring ops**.
  - Pills are draggable onto the 2D molecule. Drop on an atom = apply.
  - Each chip has a tooltip: chemistry rationale ("Add -OH increases
    polarity; expect logP -0.5, MIC effect varies by pocket
    H-bonding").
  - **Custom transform** input (text): user types `replace -Cl with -F`,
    Designer interprets and previews.
- **Mechanism button**: opens a short reasoning panel describing how
  the candidate is hypothesised to bind, with citations to the
  literature seeds + first-line therapy class.

### 3.3 Compress / expand grip
- Vertical hairline drag handle between 3D and 2D.
- Cursor `row-resize`.
- Persist user's split.
- 2D collapsing leaves a 24 px stub bar at the bottom with a "show 2D"
  caret. 3D never collapses.

### 3.4 The agent must be able to drive these viewers
This is the killer feature. Wire backend tools so the Designer agent
can call `propose_pocket_aware`, `transform_structure`,
`scaffold_hop`, `optimize_iteratively`. Each tool emission should
animate the 2D viewer + recompute the 3D pose, with a tool-call card
appearing in the chat in real time.

---

## 4. Right rail — analytics panels (Radar / Pareto / Synth / Graph / Lineage)

**Reference screenshots**: `04_radar_panel_broken.png` through
`08_lineage_panel.png`

**Current pain**:
> "The RL work and such things are too tightly congested with bad and
> extremely ugly UI/UX work, no real-time-ness or end-to-end backend and
> functionalities. Extremely broken and poor across all the order:
> Pareto, Synth, Graph, Lineage. All are pathetic and absurdingly
> breaking, the labels and the UI/UX as well."

### 4.1 Tab strip (currently `Radar Pareto Synth Graph Lineage`)
- Use a **proper tablist** with active-state underline + animated marker
  that slides between tabs. 14 px font, 36 px tall.
- Don't repeat the active tab name (currently shows `Radar Radar Pareto
  Synth Graph Lineage` — duplicate label).

### 4.2 Radar panel
- 8-axis radar (one per top reward component): `MIC`, `QED`, `SA`,
  `Safe`, `Tox-N`, `Sem-Nov`, `Alerts`, `Valid`.
- **Two overlays**: green polygon = current candidate; faint dotted =
  ideal target. Below the polygon, a per-axis legend with
  `axis · score · weight contribution to composite`.
- Hover an axis = highlights that component everywhere (chat
  filtering, 2D atom highlighting if applicable).

### 4.3 Pareto panel
- X / Y axis dropdowns (already exist) — fix label collision (`MIC`
  is currently overlapping `Dominated`).
- Scatter: green = on Pareto front, grey = dominated, with hover-card
  showing all 12 components for that candidate.
- **3D Pareto (toggle)**: opt-in WebGL plot for 3-axis Pareto if user
  enables. Default 2D.
- A small **histogram strip** under the scatter showing distribution
  along each axis.

### 4.4 Synth panel
- Big SA score number + bar (already there).
- Sub-cards: `STEPS`, `COST/G`, `CONFIDENCE`. Spacing tighter (16 px
  gap, not 32 px).
- **AiZynth route ladder**: when cache hit, show the actual
  retrosynthetic route as a vertical chain of reactions. Each rung
  shows: precursor → reaction class → intermediate. Hover a rung shows
  the published reaction + DOI.
- Cost/g bar coloured by feasibility (green < $100, amber $100-500,
  red > $500).

### 4.5 Graph panel (resistance graph)
- Force-directed graph of `pathogen → resistance gene → affected drug
  class`. Already exists.
- Fix label clipping (`MexAB-OprM` truncated). Use force-layout that
  respects label-bounding-box.
- **Click a gene**: shows the 3D structure of that gene in the 3D viewer
  + asks the Resistance-Forecaster sub-agent to project where this
  gene is going next.
- Filter chips at the top: `MDR / XDR / PanR`.

### 4.6 Lineage panel (currently 1 circle with `0.86`)
- Replace with a **tree view** of all candidates from the session,
  showing parent → mutation → child. Each node is a circle whose colour
  encodes composite score (red → green gradient).
- Edges labelled with the transformation (`-Cl → -F`).
- Click a node = loads it into the 3D + 2D viewers.
- Pan + zoom; mini-map in the bottom-right.

### 4.7 Candidates list (bottom of every panel)
- Currently fine; tighten:
  - Top entry shows star + composite score, large.
  - Below: rank, axes-where-it-leads (e.g. "best on MIC"), copy-SMILES
    icon, "Load in 3D" icon.
  - Scrollable with sticky header showing total count + Pareto count.

---

## 5. Iteration / constraints bar

**Reference screenshot**: `09_iteration_constraints_bar.png`

**Current pain**:
> "This is looking nonsensical and makes no sense; either is now at the
> bottom, it is taking unusually unnecessary space. Get it removed and
> fit in the one navber thing we have right."

**Decision**: kill the standalone bottom bar. Move:
- `<<  ▷  >>` playback controls → **into the iteration progress strip
  in the chat header** (§2.5).
- `1/1` and `2x` speed → small chips beside the play button.
- `+ Add` constraint button → **into the chat composer** as a
  slash-command (`/constraint`) and as a small "+" icon that opens a
  constraint modal.
- `From paper` button → into the chat composer slash-command as well
  (`/from-paper`).
- Existing constraint chips (e.g. `Replace -Cl with -F`) → render
  inline above the composer as removable chips.

Net effect: one less horizontal bar; the entire workbench feels more
focused.

---

## 6. Backend wiring (no mocks)

For every UI element above, name the FastAPI endpoint that drives it:

| UI element                  | Endpoint                                  |
|------------------------------|-------------------------------------------|
| Pathogen picker              | `GET /workbench/pathogens`                |
| Start session                | `POST /workbench/sessions`                |
| Run loop                     | `POST /workbench/sessions/{sid}/start`    |
| Live event stream            | `GET /workbench/sessions/{sid}/events` (SSE) |
| Intervene mid-loop           | `POST /workbench/sessions/{sid}/intervene`|
| Tool list                    | `GET /workbench/skills`                   |
| Run a tool                   | `POST /workbench/tools/{name}`            |
| 3D viewer payload            | `GET /workbench/molecule/3d?smiles=…`     |
| 2D drag-edit                 | `POST /workbench/molecule/edit`           |
| Pocket coords                | `GET /workbench/pathogen/{code}/pocket`   |
| Reward decomposition         | (computed inside the design loop, emitted via SSE event `score`) |
| Candidate list               | (in session state, returned by `GET /sessions/{sid}`) |
| Lineage tree                 | (graph extracted from session state)      |
| Graph (resistance)           | `GET /workbench/pathogen/{code}/graph`    |
| Synth route                  | `GET /workbench/molecule/synth?smiles=…`  |
| Constraints                  | embedded in session create/update payload |

**Streaming model**: every long-running thing is SSE. Frontend opens one
EventSource per session and routes events by `type`:
- `agent_message` → into chat
- `tool_call_start` / `tool_call_end` → tool-card in chat + animation
- `candidate_added` → bumps candidate list + re-renders Pareto + Radar
- `score` → updates composite + per-component bars
- `iteration_start` / `iteration_end` → progress strip
- `state_change` → repaints active-agent indicators

---

## 7. Sandbox / agent execution

**Pain**:
> "We need the sandbox-based work or how we doing everything regards to
> it; it's important and significant and crucial; it will bring a lot
> of attention to the project at an extraordinary level of work."

**Decision**: implement two sandbox surfaces.

1. **Code sandbox** (already in `workspace/tools/sandbox/execute_python.py`):
   - The agent can write small Python in a tool-call (e.g. RDKit
     calls, pandas analyses).
   - Frontend renders the executed code + output below the agent message.
   - Backend runs in a subprocess with timeout + memory cap + no
     network. Returns stdout, stderr, plots (as base64 PNG).

2. **Chemistry sandbox** (new):
   - The agent can request a *molecular transformation*:
     `transform(smiles, op="replace", from="-Cl", to="-F", at_atom=12)`.
   - Backend validates the transform under chemistry rules (RDKit
     `RWMol` + valence check + alert filter).
   - Returns: new SMILES, validity, predicted MIC delta,
     predicted hemolysis delta, alert delta, novelty delta.
   - Frontend animates the change in 2D + recomputes 3D pose.
   - This is the surface that makes the agent "actually do chemistry"
     visibly — judges will notice.

---

## 8. Visual design system

| Token        | Value                                          |
|--------------|------------------------------------------------|
| Background   | `#0d1117` (dark) / `#fafafa` (light)            |
| Surface      | `rgba(255,255,255,0.04)` glass                 |
| Border       | `1px solid rgba(255,255,255,0.08)`              |
| Radius       | `12px` cards, `8px` chips, `999px` pills       |
| Body font    | Inter / SF Pro at 14 px                        |
| Mono font    | JetBrains Mono at 13 px                        |
| Heading 1    | 20 px / 600 / tracking -0.02em                 |
| Heading 2    | 16 px / 600                                    |
| Caption      | 12 px / 500 / opacity 0.6                      |
| Agent colors | Designer #34d399 / Critic #f87171 / Editor #60a5fa / Strategist #a78bfa / User #fbbf24 |

Animation:
- All transitions 200ms ease-out
- Agent-active pulse 1.4s ease-in-out infinite
- Atom-edit micro-animation 350ms cubic-bezier(.2,.8,.2,1)

Frameworks (decision made — stop second-guessing):
- React 18 + Vite (already in)
- Tailwind CSS for tokens
- shadcn/ui for primitives (Dialog, Tooltip, Dropdown, Tabs)
- Framer Motion for animations
- NGL Viewer for 3D
- RDKit-JS for 2D + drag-edit
- Recharts for radar / scatter
- Cytoscape.js for resistance graph + lineage tree
- Allotment for the resizable splits

---

## 9. Build order

1. Top header redesign (§1) — unblocks everything
2. Three-column resizable layout (§2.1, §3.3)
3. Chat composer + slash commands (§2.6) — kills the bottom bar
4. Agent-toolbar redo + sub-agent picker (§2.3)
5. Message bubble redesign with thinking blocks (§2.4)
6. Iteration progress strip with playback controls (§2.5, §5)
7. 3D viewer header + properties card relocation (§3.1)
8. 2D drag-edit chip groups + custom transform (§3.2)
9. Tab strip cleanup + Radar / Pareto / Synth / Graph / Lineage redesign (§4)
10. Backend SSE event additions (§6)
11. Chemistry sandbox transform endpoint + animation (§7)
12. Polish pass: animations, tokens, accessibility (§8)

---

## 10. Out-of-scope (this iteration)

- Mobile layout (workbench is a desktop product; pitch demo on a 27"
  monitor).
- Multi-session compare side-by-side.
- Real-time collaboration (multiple users in one session).
- Voice command implementation (reserve UI slot only).

These can come later. Ship the v0.3 surface above first.

---

## 11. Acceptance criteria

A judge sitting in front of the workbench should within 60 seconds:
1. Pick a pathogen and click Start.
2. See agent messages stream in (Strategist briefs the resistome,
   Designer proposes, Critic challenges, Editor refines).
3. See a SMILES land in the 2D viewer with the protein binding pose
   updating live in 3D.
4. Drag a `-F` chip onto the 2D viewer and watch the 3D pose
   re-dock + the radar update.
5. Open the Pareto tab and see the candidate plotted, with a small
   tooltip explaining trade-offs.
6. Hit "Mechanism" and read a 60-word reasoned explanation citing real
   genes / first-line therapy.

If any of those 6 steps requires a refresh, a manual workaround, or a
mock response — we missed.

---

*Brief saved 2026-05-05 from voice prompts; will be picked up after the
6-gap closure work and worked end-to-end through the night.*
