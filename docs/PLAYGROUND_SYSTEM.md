# Lysos Playground — Real System Design (data + backend + events + rules)

> Stop UI-shallow. Build the **simulator** for atoms / bonds / molecules /
> agents that **persists** state, broadcasts **events**, queues **jobs**,
> enforces **chemistry rules**, and supports **live multi-actor editing**
> (user ⇄ agents) — the Figma / Cursor-IDE for antibiotic discovery.

---

## 1. The simulator's mental model

A **drug-design session** = a graph of molecules + an event log of every
atom touch + a set of agents acting on it. Every interaction is an event;
every event is persisted; replay is free; multi-actor live editing is the
default. Concretely:

```
┌─────────── SESSION ────────────────────────────────────────────────┐
│                                                                    │
│   ┌─ MOLECULE ─────────┐    ┌─ MOLECULE ──┐    ┌─ MOLECULE ──┐    │
│   │  smi: CCO          │ →  │  CCN(C)C    │ →  │  CCN(C)CF   │    │
│   │  atoms: [A0..A2]   │    │  atoms[…]    │    │  atoms[…]    │    │
│   │  bonds: [B0..B1]   │    │  bonds[…]    │    │  bonds[…]    │    │
│   └─────────┬──────────┘    └──────┬───────┘    └──────────────┘    │
│             │                      │                                │
│             ▼                      ▼                                │
│   ┌──── EDIT LOG (append-only) ──────────────────────────────┐    │
│   │ ts  actor      op             atom  result_smi  scoreΔ   │    │
│   │ T1  designer   propose CCO                                │    │
│   │ T2  user       hover  A1                                  │    │
│   │ T3  critic     flag   A1     "weakness: solubility"       │    │
│   │ T4  editor     apply  +OH    A1     CCO         +0.012    │    │
│   │ T5  user       click  A2     CCN(C)C            +0.045    │    │
│   │ ...                                                        │    │
│   └────────────────────────────────────────────────────────────┘    │
│                                                                    │
│   Cursors:  designer@A0  ·  critic@A1  ·  user@A2                  │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

Every write goes through the event log. Every read can be a materialized
projection or a replay. The model trains on the same events it writes —
the playground IS the training environment.

---

## 2. Domain entities (the data model)

```
Session
  id, user_id, project_id, target_pathogen, mode, autonomy
  created_at, terminated, termination_reason
  ↓ has many
Molecule
  id, session_id, parent_id, smiles, canonical_smiles, formula, mw, logp
  composite_score, pareto_rank, role  ("active" | "branch" | "discarded")
  created_at, created_by ("designer"/"user"/"editor"/"sar")
  ↓ has many
Atom                              Bond
  id, molecule_id, atom_idx       id, molecule_id, bond_idx
  element, formal_charge          atom_a_id, atom_b_id, type
  n_hydrogens, free_valence       in_ring
  is_aromatic, in_ring,           ↑
  ring_size, x, y, z              ↓
  ↑ referenced by                 ↓
MoleculeEdit  (THE EVENT LOG)
  id, ts, session_id, parent_molecule_id, child_molecule_id
  actor (agent_name | "user"), actor_kind ("agent" | "user")
  op (swap_element | add_methyl | break_bond | apply_smarts | propose)
  atom_idx?, bond_idx?, params (JSON), result_smiles
  composite_before, composite_after, delta
  client_op_id (for idempotency / dedup)

ScoreSnapshot
  id, molecule_id, ts
  composite, components (JSON: 12 axes)
  weakest, strongest, model_used

AgentAction
  id, session_id, ts, agent_name
  action_type ("propose"|"critique"|"edit"|"hover"|"select"|"terminate")
  target_molecule_id?, target_atom_idx?
  message_text, confidence, references (JSON)

CursorPresence (in-memory only)
  session_id, actor, target_molecule_id, atom_idx, ts

ChemRule
  id, rule_type ("valence"|"bond"|"structural_alert"|"sar")
  when_smarts, then_action, severity, source
  citations (JSON)

ResistanceFact
  pathogen, gene, mechanism, defeated_class, mic_shift, citation

KnowledgeFact   (the curated 387-drug corpus, indexed)
  id, drug, position, modification, effect_axis, magnitude, citation

Job
  id, session_id, kind ("dock"|"admet"|"conformer"|"retrosynth")
  status ("queued"|"running"|"done"|"error"|"cancelled")
  payload (JSON), result (JSON), error_text
  created_at, started_at, finished_at, worker_id

PlaygroundLayout
  session_id, user_id, layout_json, viewport_json, updated_at
```

---

## 3. Backend services

### 3.1 PlaygroundStore (SQLite)
File: `workspace/playground/store.py`

- WAL mode, single-file at `~/.lysos/playground.sqlite` (Postgres-portable schema)
- All writes through transactions
- Append-only append for `MoleculeEdit`, `AgentAction`, `ScoreSnapshot`
- Atom + Bond materialized from SMILES via RDKit on insert; recomputed on edit
- Indices: (session_id, ts), (molecule_id, atom_idx), (parent_molecule_id)

### 3.2 EventBus (in-memory + persistence)
File: `workspace/playground/bus.py`

- Per-session asyncio.Queue + sync to SQLite
- Subscribers: WebSocket clients, agent loop, orchestrator ledger
- Event types: `molecule.created`, `molecule.scored`, `atom.hovered`,
  `atom.selected`, `cursor.moved`, `edit.proposed`, `edit.applied`,
  `agent.thinking`, `agent.message`, `job.update`
- Backpressure: drop `cursor.moved` events older than 100ms; never drop edits

### 3.3 LiveEditingProtocol
WebSocket endpoint: `/ws/playground/{session_id}`

Client → server:
```json
{ "op": "cursor.move",   "actor": "user", "molecule_id": "m_42",
  "atom_idx": 5, "client_ts": 1715... }
{ "op": "atom.hover",    "actor": "user", "molecule_id": "m_42",
  "atom_idx": 5, "predict": true }
{ "op": "edit.propose",  "actor": "user", "molecule_id": "m_42",
  "edit": { "kind": "swap_element", "atom_idx": 5, "new_element": "F" },
  "client_op_id": "uuid" }
{ "op": "edit.apply",    "actor": "user", "molecule_id": "m_42",
  "edit": { ... }, "client_op_id": "uuid" }
{ "op": "select",        "actor": "user", "molecule_id": "m_42",
  "atom_idxs": [3, 5, 7] }
{ "op": "branch",        "actor": "user", "molecule_id": "m_42" }
```

Server → all subscribers:
```json
{ "event": "cursor.moved", "actor": "designer", "atom_idx": 3 }
{ "event": "atom.hovered", "actor": "user", "atom_idx": 5,
  "predicted_components": { "drug_likeness_qed": 0.62, ... } }
{ "event": "edit.applied", "actor": "user", "from_smi": "...", "to_smi": "...",
  "edit": { ... }, "delta_composite": +0.025, "molecule_id": "m_43" }
{ "event": "agent.thinking", "agent": "critic",
  "target_atom_idx": 5, "rationale": "weak solubility..." }
```

CRDT-lite: each edit has `(ts, actor, client_op_id)`. Server applies in
ts-order; if two clients propose edits at the same ts, the one with the
lower `client_op_id` wins. Conflicts emit `edit.rejected`.

### 3.4 RulesEngine
File: `workspace/playground/rules.py`

```python
class RulesEngine:
    def get_atom_context(smi, atom_idx) -> AtomContext: ...
    def get_allowed_attachments(smi, atom_idx) -> [Attachment]: ...
    def check_structural_alerts(smi) -> [Alert]: ...
    def check_resistance_escape(smi, pathogen) -> EscapeRisk: ...
    def predict_edit(smi, edit) -> PredictedDelta: ...
```

- RDKit-backed valence/bond/aromatic rules
- Reads `ChemRule`, `KnowledgeFact`, `ResistanceFact` from store
- Caches per (smi, atom_idx) for hover predictions

### 3.5 JobQueue
File: `workspace/playground/queue.py`

- `enqueue(kind, payload) → job_id`
- Worker pool (asyncio.create_task) per kind with concurrency caps
- Status events fed into the EventBus
- Cancellable; persistent across restarts

### 3.6 KnowledgeGraph
File: `workspace/playground/kg.py`

- Built once at startup from:
  - `data/synthetic/named_drug_examples.jsonl` (387 drugs × deep mech)
  - `data/synthetic/pharma_qa_layer.jsonl` (872 Q/A)
  - Curated `ResistanceFact` tables (mecA, KPC, NDM, OXA, vanA/B, …)
- Querying: `kg.query(target="mecA")`, `kg.relations_of(drug)`, `kg.path(a, b)`
- Used by ExplainCommand (already wired) + the rules engine SAR notes

---

## 4. Live multi-actor editing — what the user said is missing

| Capability | Backend | Frontend |
|---|---|---|
| Cursor presence | `cursor.moved` events broadcast | other actors' cursors visible as colored dots on the 2D structure |
| Hover prediction | `atom.hover` → RulesEngine.predict_edit → emit | radar shows "ghost" polygon for the predicted-after-edit state |
| Atom selection (multi) | `select` event with atom_idxs | selected atoms get a colored outline |
| Branch / fork | new Molecule with parent_id | side-by-side compare card auto-mounts |
| Undo / redo | walk MoleculeEdit log backwards | Cmd-Z / Cmd-Shift-Z |
| Real-time co-editing | edits from agent loop OR user routed through same event bus | both render in 2D builder simultaneously |
| Replay | scan_history(session_id) | timeline scrubber re-emits events |

**The agent loop participates in the same protocol.** When Designer
emits a SMILES, it's stored as a `MoleculeEdit` op="propose" by actor=
"designer". When Critic flags atom_idx=5, it's an `AgentAction`
type="critique" target_atom_idx=5. The frontend renders Critic's cursor
hovering atom 5 just like a user cursor — same protocol.

---

## 5. Chemistry rules engine — no hardcoding

The user said "no hardcoding". The rules engine derives everything from
RDKit + the curated corpus + a small set of declarative rules in JSON:

```
rules/
  valence.json              ← standard valence per element
  functional_groups.json    ← SMARTS patterns for groups
  structural_alerts.json    ← PAINS, reactive groups, toxicophores
  sar_motifs.json           ← curated position-effect mappings
  resistance_facts.json     ← pathogen × gene × defeated class
```

These get loaded once at startup. The `RulesEngine` evaluates them via
RDKit SMARTS matching. No Python switch-statement on element names; no
hardcoded "fluorine is good for solubility". The model and the rules
both come from data.

---

## 6. The agent ⇄ playground protocol

When Designer/Critic/Editor/Strategist take an action, the flow is:

```
agent_loop (graph.py)
   │
   │  llm.acomplete() returns content + tool_calls
   │
   ▼
HarnessAdapter.translate(agent_output)
   │
   │  produces:
   │    - MoleculeEdit row (op, atom, result_smi)
   │    - AgentAction row (action_type, references)
   │    - 0+ Job enqueues (e.g. score, dock)
   │    - 0+ EventBus broadcasts (cursor.moved, edit.applied, …)
   │
   ▼
PlaygroundStore.persist  +  EventBus.publish
   │
   ├─→ WebSocket clients receive `event:`
   ├─→ Orchestrator.ledger updates
   └─→ next iteration of agent loop reads the new state
```

Same path for user-initiated edits — the user IS another actor on the
same protocol. This is what makes it feel like Figma/Cursor.

---

## 7. Build phases (ship in this order)

### Phase A — Foundation (this push)
1. **store.py** — SQLite schema + repositories for Session, Molecule,
   Atom, Bond, MoleculeEdit, ScoreSnapshot, AgentAction, Job
2. **bus.py** — per-session asyncio event bus, persists to SQLite
3. **/ws/playground/{sid}** — bidirectional WebSocket handler
4. **rules.py** — RulesEngine wrapper around RDKit + JSON rules
5. **/workbench/molecule/{id}/atoms** — atom-level read API

### Phase B — Live editing UX
6. Frontend WebSocket client hook
7. Cursor presence overlay on the 2D builder (other actors' cursors)
8. Hover prediction (atom hover → server → "what if?" radar overlay)
9. Atom multi-select + branch/fork buttons
10. Undo/redo stack walking the MoleculeEdit log

### Phase C — Agent participation
11. HarnessAdapter — translate agent loop outputs to MoleculeEdit + events
12. Agent cursor sync (Designer "looking at" atom X shows up in UI)
13. Live agent_thinking events (typing-indicator-like, but per atom)

### Phase D — Job queue
14. queue.py — async job pool
15. Wire /dock /admet /conformer /retrosynth through the queue
16. Status pills in the playground show running jobs

### Phase E — Knowledge graph
17. kg.py — build at startup from named_drug_examples + pharma_qa
18. /workbench/kg/query endpoint
19. SAR-aware allowed_attachments (rules engine consults the KG)

### Phase F — Polish
20. Branch tree visualization (genealogy)
21. Replay scrubber
22. Multi-window state sync (radar pulses on edit, agent trace ticks)
23. Conflict resolution UI for concurrent edits

---

## 8. What this unlocks

- **The agent isn't writing prose about chemistry — it's editing atoms
  and bonds in a real model.** Every "I'd add fluorine here" turns into
  a MoleculeEdit row with the actual atom_idx + result_smi.
- **The user does the same operation via the 2D builder.** Same row
  shape, same event, same downstream effects.
- **The model trains on its own outputs in production.** Every session
  is a stream of `(state, action, reward)` tuples ready for RL.
- **Replay is free.** Click a past session in /library → scrub through
  the edits → see exactly what each agent did, atom by atom.
- **Chemistry rules aren't hallucinated.** Every edit gets validated by
  the RulesEngine before persistence. Invalid moves emit `edit.rejected`
  with a reason from RDKit (valence violation, structural alert, etc.).
- **Knowledge is queryable, not buried.** /workbench/kg/query gives the
  agent (and the user) typed access to "what's known about mecA".

This is the simulator. The Figma for atoms. The Cursor IDE for chem.
That's what we're building.
