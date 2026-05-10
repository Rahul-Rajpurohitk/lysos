/**
 * AgentSuggestionStrip — what to do next, surfaced above the composer.
 *
 * Two integrated affordances:
 *  1. Suggestion chips driven by GET /api/agent/suggest-next — context
 *     aware buttons that LAUNCH a workflow when clicked (they don't
 *     just paste text into the composer; they actually run).
 *  2. WorkflowPaletteButton — a "+" pill that opens a popover listing
 *     ALL registered workflows so the user can pick any one regardless
 *     of state.
 *
 * Each suggestion shows: a colored dot for priority, the action label,
 * a one-line reason, and a "run →" affordance. Clicking immediately
 * fires onRunWorkflow(name, inputs) which the parent wires to the SSE
 * pipeline (same path as /wf <name>).
 */
import { useEffect, useState, useRef } from "react";
import { Sparkles, Plus, ChevronDown, Play, Wrench } from "lucide-react";

const LAV = {
  bg: "rgba(174, 158, 244, 0.06)",
  bgStrong: "rgba(174, 158, 244, 0.14)",
  border: "rgba(174, 158, 244, 0.28)",
  borderStrong: "rgba(174, 158, 244, 0.42)",
  fg: "#7c63d8",
  fgDeep: "#6041d0",
} as const;

interface Suggestion {
  label: string;
  workflow: string;
  inputs: Record<string, any>;
  reason: string;
  priority: number;
}

interface WorkflowSpec {
  name: string;
  label: string;
  description: string;
  tags: string[];
  n_steps: number;
  inputs: Array<{ name: string; type: string; required?: boolean; default?: any }>;
}

interface Props {
  apiBase: string;
  smiles?: string | null;
  pdbId?: string | null;
  pathogen?: string;
  hasScore?: boolean;
  hasResistance?: boolean;
  hasHarden?: boolean;
  nCandidates?: number;
  /** Recent unique SMILES from this session — auto-fills compare_top_n
   *  / batch workflows that need an array of candidates. */
  sessionCandidates?: string[];
  /** Fire a workflow run via the same SSE pipeline /wf uses. */
  onRunWorkflow: (name: string, inputs: Record<string, any>) => void;
  /** Hide entirely when input has text — keeps the composer clean. */
  hidden?: boolean;
  /** When true, render ONLY the workflow palette button (no suggestion
   *  cards, no "computing…" placeholder). Used once the chat has real
   *  activity so the strip doesn't burn vertical space duplicating
   *  workflow chrome already visible in the timeline. */
  compact?: boolean;
}

export function AgentSuggestionStrip({
  apiBase, smiles, pdbId, pathogen,
  hasScore, hasResistance, hasHarden, nCandidates,
  sessionCandidates,
  onRunWorkflow, hidden, compact,
}: Props) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowSpec[]>([]);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Pull suggestions on context change.
  // apiBase=="" is VALID (relative URL via Vite proxy) — only skip on
  // explicit null/undefined. The earlier truthy check silently blocked
  // every fetch when running through the Vite dev server.
  useEffect(() => {
    if (apiBase == null || hidden) return;
    let cancelled = false;
    const params = new URLSearchParams();
    if (smiles) params.set("smiles", smiles);
    if (pdbId) params.set("pdb_id", pdbId);
    if (pathogen) params.set("pathogen", pathogen);
    if (hasScore) params.set("has_score", "true");
    if (hasResistance) params.set("has_resistance", "true");
    if (hasHarden) params.set("has_harden", "true");
    if (nCandidates != null) params.set("n_candidates", String(nCandidates));

    fetch(`${apiBase}/api/agent/suggest-next?${params}`)
      .then((r) => r.ok ? r.json() : { suggestions: [] })
      .then((d) => { if (!cancelled) setSuggestions(d.suggestions || []); })
      .catch(() => {/* noop */});
    return () => { cancelled = true; };
  }, [apiBase, smiles, pdbId, pathogen, hasScore, hasResistance, hasHarden, nCandidates, hidden]);

  // Pull workflow list once. Same fix — accept apiBase==="" as valid.
  useEffect(() => {
    if (apiBase == null) return;
    let cancelled = false;
    fetch(`${apiBase}/api/workflows/list`)
      .then((r) => r.ok ? r.json() : { workflows: [] })
      .then((d) => { if (!cancelled) setWorkflows(d.workflows || []); })
      .catch(() => {/* noop */});
    return () => { cancelled = true; };
  }, [apiBase]);

  if (hidden) return null;
  // No SMILES + no suggestions = no value. The "load a candidate" hint
  // was cluttering the bottom of every empty chat.
  if (!smiles && suggestions.length === 0 && !compact) return null;

  // COMPACT mode — only the workflow palette button, right-aligned.
  // Used once the chat has real activity so the strip doesn't keep
  // shouting suggestion cards on top of an active workflow.
  if (compact) {
    return (
      <div style={{
        marginBottom: 4,
        display: "flex", alignItems: "center", justifyContent: "flex-end",
      }}>
        <WorkflowPaletteButton
          workflows={workflows}
          open={paletteOpen}
          setOpen={setPaletteOpen}
          onPick={(name, inputs) => {
            setPaletteOpen(false);
            onRunWorkflow(name, inputs);
          }}
          ctx={{ smiles, pdbId, pathogen, sessionCandidates }}
        />
      </div>
    );
  }

  const priorityColor = (p: number) =>
    p >= 9 ? "#10b981" : p >= 7 ? "#0891b2" : "#94a3b8";

  return (
    <div style={{
      marginBottom: 6,
      display: "flex", flexDirection: "column", gap: 4,
    }}>
      {/* Section header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 9, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)",
        letterSpacing: "0.04em", textTransform: "uppercase", fontWeight: 600,
        marginBottom: 1,
      }}>
        <Sparkles size={9} style={{ color: LAV.fg }} />
        <span>agent suggests</span>
        <span style={{ flex: 1 }} />
        <WorkflowPaletteButton
          workflows={workflows}
          open={paletteOpen}
          setOpen={setPaletteOpen}
          onPick={(name, inputs) => {
            setPaletteOpen(false);
            onRunWorkflow(name, inputs);
          }}
          ctx={{ smiles, pdbId, pathogen, sessionCandidates }}
        />
      </div>

      {suggestions.length === 0 ? (
        <div style={{
          padding: "5px 8px",
          fontSize: 9.5, color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-body)",
          fontStyle: "italic",
        }}>
          {smiles
            ? "Computing best next steps for this candidate…"
            : "Load a candidate or pick a workflow from the palette →"}
        </div>
      ) : (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 4,
        }}>
          {suggestions.slice(0, 4).map((s, i) => (
            <button
              key={`${s.workflow}-${i}`}
              type="button"
              onClick={() => onRunWorkflow(s.workflow, s.inputs)}
              title={s.reason}
              style={{
                display: "flex", flexDirection: "column", gap: 2,
                padding: "6px 8px",
                background: LAV.bg,
                border: `1px solid ${LAV.border}`,
                borderRadius: 5,
                cursor: "pointer",
                fontFamily: "var(--lys-font-body)",
                textAlign: "left",
                minWidth: 0,
                transition: "background 0.12s, border-color 0.12s",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = LAV.bgStrong;
                (e.currentTarget as HTMLButtonElement).style.borderColor = LAV.borderStrong;
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = LAV.bg;
                (e.currentTarget as HTMLButtonElement).style.borderColor = LAV.border;
              }}
            >
              <div style={{
                display: "flex", alignItems: "center", gap: 5, minWidth: 0,
              }}>
                <span style={{
                  width: 6, height: 6, borderRadius: 999,
                  background: priorityColor(s.priority), flexShrink: 0,
                }} />
                <span style={{
                  fontSize: 10.5, fontWeight: 600,
                  color: LAV.fgDeep,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  flex: 1, minWidth: 0,
                }}>{s.label}</span>
                <Play size={9} style={{ color: LAV.fgDeep, flexShrink: 0 }} />
              </div>
              <span style={{
                fontSize: 9, color: "var(--lys-text-faint)",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {s.reason}
              </span>
              <span style={{
                fontSize: 8, fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)",
                opacity: 0.7,
              }}>
                /wf {s.workflow}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}


function WorkflowPaletteButton({
  workflows, open, setOpen, onPick, ctx,
}: {
  workflows: WorkflowSpec[];
  open: boolean;
  setOpen: (v: boolean) => void;
  onPick: (name: string, inputs: Record<string, any>) => void;
  ctx: {
    smiles?: string | null;
    pdbId?: string | null;
    pathogen?: string;
    /** Recent unique candidate SMILES from the session — used to
     *  auto-fill compare_top_n / broad workflows that need an array. */
    sessionCandidates?: string[];
  };
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current) return;
      if (!ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, setOpen]);

  const buildInputs = (wf: WorkflowSpec): Record<string, any> => {
    const inputs: Record<string, any> = {};
    for (const inp of wf.inputs) {
      if (inp.name === "smiles") {
        // Always send a smiles — fall back to benzene seed so workflows
        // that REQUIRE smiles (harden_candidate, broad_spectrum_screen)
        // never fail with "step predict args failed" because no
        // candidate has been loaded yet.
        inputs.smiles = ctx.smiles || "c1ccccc1";
      } else if (inp.name === "smiles_list") {
        // compare_top_n / batch workflows need an ARRAY of smiles.
        // Pull from session recent candidates; if empty, fall back
        // to a small benzene-only list so the workflow at least
        // executes instead of crashing on a missing key.
        const sess = ctx.sessionCandidates ?? [];
        const list = sess.length > 0 ? sess.slice(0, 3) : (ctx.smiles ? [ctx.smiles] : ["c1ccccc1"]);
        inputs.smiles_list = list;
      } else if (inp.name === "pdb_id") {
        inputs.pdb_id = ctx.pdbId || inp.default || "1VQQ";
      } else if (inp.name === "pathogen") {
        inputs.pathogen = ctx.pathogen || inp.default || "MRSA";
      } else if (inp.default !== undefined) {
        inputs[inp.name] = inp.default;
      }
    }
    return inputs;
  };

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        style={{
          display: "inline-flex", alignItems: "center", gap: 3,
          padding: "2px 7px", height: 20,
          background: LAV.bgStrong, border: `1px solid ${LAV.borderStrong}`,
          borderRadius: 999, color: LAV.fgDeep,
          fontSize: 9.5, fontWeight: 600, fontFamily: "var(--lys-font-body)",
          cursor: "pointer",
        }}>
        <Plus size={10} /> workflow
        <ChevronDown size={9} style={{
          transition: "transform 0.15s",
          transform: open ? "rotate(180deg)" : "rotate(0)",
        }} />
      </button>
      {open && (
        // Drop-DOWN at top:100% can clip when there's lots of chat
        // below (it falls outside the panel). Anchor BOTTOM:100% so
        // the menu opens UPWARD into the existing chat space, and
        // shrink the width to fit narrow side panes (320px max).
        <div style={{
          position: "absolute", bottom: "100%", right: 0, marginBottom: 6,
          width: "min(320px, calc(100vw - 60px))",
          maxHeight: 360, overflowY: "auto",
          background: "white",
          border: `1px solid ${LAV.borderStrong}`,
          borderRadius: 6,
          boxShadow: "0 -8px 24px rgba(15,23,42,0.18)",
          zIndex: 100,
          padding: 4,
        }}>
          <div style={{
            padding: "4px 8px",
            fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)",
            letterSpacing: "0.06em", textTransform: "uppercase", fontWeight: 700,
            borderBottom: `1px solid ${LAV.border}`,
            marginBottom: 3,
          }}>
            workflows · pick one
          </div>
          {workflows.length === 0 && (
            <div style={{
              padding: 12, fontSize: 10, color: "var(--lys-text-faint)",
              textAlign: "center", fontStyle: "italic",
            }}>no workflows registered</div>
          )}
          {workflows.map((wf) => (
            <button
              key={wf.name}
              type="button"
              onClick={() => onPick(wf.name, buildInputs(wf))}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "6px 8px",
                background: "transparent",
                border: 0, borderRadius: 4,
                cursor: "pointer",
                fontFamily: "var(--lys-font-body)",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = LAV.bg;
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = "transparent";
              }}
            >
              <div style={{
                display: "flex", alignItems: "center", gap: 5, marginBottom: 2,
              }}>
                <Wrench size={10} style={{ color: LAV.fgDeep, flexShrink: 0 }} />
                <span style={{
                  fontSize: 10.5, fontWeight: 700, color: "var(--lys-text)",
                }}>{wf.label}</span>
                <span style={{ flex: 1 }} />
                <span style={{
                  fontSize: 8, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)",
                  padding: "0 4px", borderRadius: 2,
                  background: "rgba(0,0,0,0.04)",
                }}>{wf.n_steps} steps</span>
              </div>
              <div style={{
                fontSize: 9.5, color: "var(--lys-text-dim)",
                lineHeight: 1.4,
              }}>{wf.description}</div>
              <div style={{
                marginTop: 3, display: "flex", flexWrap: "wrap", gap: 3,
              }}>
                {wf.tags.map((t) => (
                  <span key={t} style={{
                    padding: "0 5px", borderRadius: 2,
                    background: LAV.bg, color: LAV.fgDeep,
                    fontSize: 8, fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                  }}>{t}</span>
                ))}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
