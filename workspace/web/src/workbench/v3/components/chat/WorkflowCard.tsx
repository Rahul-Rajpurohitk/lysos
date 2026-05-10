/**
 * WorkflowCard — live workflow execution renderer.
 *
 * Renders a workflow run as a stepped Claude-style progress card. Each
 * step is one row with status (pending / running / done / error / skipped),
 * label, tool, elapsed time, and an expandable result preview.
 *
 * Driven by the SSE stream from POST /api/workflows/run. Reduce events
 * into WorkflowState then render that.
 */
import { useState } from "react";
import { ChevronRight, ChevronDown, CheckCircle2, AlertCircle,
         Loader2, Circle, MinusCircle, Sparkles, X as IconX } from "lucide-react";
import { MarkdownText } from "./MarkdownText";

const LAV = {
  bg: "rgba(174, 158, 244, 0.08)",
  bgStrong: "rgba(174, 158, 244, 0.14)",
  border: "rgba(174, 158, 244, 0.30)",
  borderStrong: "rgba(174, 158, 244, 0.45)",
  fg: "#7c63d8",
  fgDeep: "#6041d0",
} as const;
const GREEN = { bg: "rgba(16,185,129,0.10)", border: "rgba(16,185,129,0.30)", fg: "#10b981" };
const RED   = { bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.30)",  fg: "#dc2626" };
const AMBER = { bg: "rgba(202,138,4,0.10)",  border: "rgba(202,138,4,0.30)",  fg: "#ca8a04" };
const GREY  = { bg: "rgba(0,0,0,0.04)",      border: "rgba(0,0,0,0.10)",      fg: "#94a3b8" };

export interface WorkflowStep {
  id: string;
  label: string;
  tool: string;
  description?: string;
  depends_on?: string[];
  status: "pending" | "running" | "done" | "error" | "skipped";
  elapsed_ms?: number;
  result?: any;
  error?: string;
  /** For __loop__ steps — current item / total items. */
  progress?: { i: number; n: number; tool: string; args: any };
  retry_attempts?: number;
}

export interface WorkflowState {
  run_id: string;
  name: string;
  label: string;
  status: "running" | "done" | "error" | "cancelled";
  inputs: any;
  steps: WorkflowStep[];
  summary?: string;
  state_dump?: any;
  elapsed_ms?: number;
  error?: string;
  /** Whether the executing run can still be cancelled. */
  cancellable: boolean;
}

export function reduceWorkflowEvent(prev: WorkflowState | null, ev: any): WorkflowState {
  const e = ev?.event as string | undefined;
  if (e === "workflow.start" || prev == null) {
    return {
      run_id: ev.run_id ?? prev?.run_id ?? "",
      name: ev.name ?? prev?.name ?? "",
      label: ev.label ?? prev?.label ?? "",
      status: "running",
      inputs: ev.inputs ?? {},
      steps: prev?.steps ?? [],
      cancellable: true,
    };
  }
  switch (e) {
    case "workflow.plan":
      return {
        ...prev,
        steps: (ev.steps || []).map((s: any) => ({
          id: s.id, label: s.label, tool: s.tool,
          description: s.description, depends_on: s.depends_on,
          status: "pending",
        } as WorkflowStep)),
      };
    case "step.start":
      return {
        ...prev,
        steps: prev.steps.map((s) => s.id === ev.step_id
          ? { ...s, status: "running" }
          : s),
      };
    case "step.progress":
      return {
        ...prev,
        steps: prev.steps.map((s) => s.id === ev.step_id
          ? { ...s, progress: { i: ev.i, n: ev.n, tool: ev.tool, args: ev.args } }
          : s),
      };
    case "step.retry":
      return {
        ...prev,
        steps: prev.steps.map((s) => s.id === ev.step_id
          ? { ...s, retry_attempts: (s.retry_attempts ?? 0) + 1 }
          : s),
      };
    case "step.done":
      return {
        ...prev,
        steps: prev.steps.map((s) => s.id === ev.step_id
          ? { ...s, status: "done",
              elapsed_ms: ev.elapsed_ms, result: ev.result }
          : s),
      };
    case "step.error":
      return {
        ...prev,
        steps: prev.steps.map((s) => s.id === ev.step_id
          ? { ...s, status: "error",
              elapsed_ms: ev.elapsed_ms, error: ev.error }
          : s),
      };
    case "step.skipped":
      return {
        ...prev,
        steps: prev.steps.map((s) => s.id === ev.step_id
          ? { ...s, status: "skipped" }
          : s),
      };
    case "workflow.done":
      return {
        ...prev, status: "done",
        elapsed_ms: ev.elapsed_ms,
        summary: ev.summary,
        state_dump: ev.state,
        cancellable: false,
      };
    case "workflow.error":
      return { ...prev, status: "error", error: ev.error, cancellable: false };
    case "workflow.cancelled":
      return { ...prev, status: "cancelled", cancellable: false };
    default:
      return prev;
  }
}


interface Props {
  state: WorkflowState;
  apiBase: string;
}

export function WorkflowCard({ state, apiBase }: Props) {
  // showState toggle removed — state_dump no longer surfaced in UI.
  void useState;

  const onCancel = async () => {
    try {
      await fetch(`${apiBase}/api/workflows/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: state.run_id }),
      });
    } catch {/*noop*/}
  };

  return (
    // Lean wrapper — thin left rule matches the agent message style.
    <div style={{
      paddingLeft: 10,
      borderLeft: `2px solid ${LAV.border}`,
      display: "flex", flexDirection: "column", gap: 6,
      fontFamily: "var(--lys-font-body)",
    }}>
      {/* Header — single inline row that does NOT wrap. The label can
       *  ellipsize if the chat panel is narrow; the StatusPill always
       *  stays on the right edge. */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 12, color: LAV.fg, fontWeight: 600,
        fontFamily: "var(--lys-font-body)",
        flexWrap: "nowrap", minWidth: 0,
      }}>
        <Sparkles size={12} style={{ flexShrink: 0 }} />
        <span style={{ flexShrink: 0 }}>workflow</span>
        <span style={{
          fontFamily: "var(--lys-font-mono)", fontSize: 11,
          color: LAV.fgDeep, fontWeight: 700,
          flexShrink: 0, whiteSpace: "nowrap",
        }}>{state.name}</span>
        <span style={{
          color: "var(--lys-text-faint)", fontWeight: 500,
          minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>· {state.label}</span>

        <span style={{ flex: 1, minWidth: 4 }} />

        <StatusPill status={state.status} elapsed_ms={state.elapsed_ms} />

        {state.cancellable && (
          <button onClick={onCancel}
            title="Cancel running workflow"
            style={{
              border: 0, background: "transparent",
              cursor: "pointer", padding: 2,
              color: RED.fg,
              display: "inline-flex", alignItems: "center",
              flexShrink: 0,
            }}>
            <IconX size={11} />
          </button>
        )}
      </div>

      {/* Steps */}
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {state.steps.map((s) => <StepRow key={s.id} step={s} />)}
        {state.steps.length === 0 && state.status === "running" && (
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            fontSize: 9.5, color: LAV.fgDeep, fontFamily: "var(--lys-font-mono)",
          }}>
            <Loader2 size={11} className="lys-spin" />
            building plan…
          </div>
        )}
      </div>

      {/* Ranked candidates strip (only for workflows with a ranking).
       *  Each row gets an "Apply to canvas" button so the user can
       *  load the SMILES into the 2D + 3D viewer + auto-score. */}
      {state.status === "done" && state.state_dump
        && Array.isArray((state.state_dump as any).ranking)
        && (state.state_dump as any).ranking.length > 0 && (
        <RankingStrip
          ranking={(state.state_dump as any).ranking}
        />
      )}

      {/* Final summary — now markdown-rendered (bold, code, lists,
       *  clickable SMILES inside backticks). The onLoadSmiles handler
       *  fires the same global lysos:auto-slash event the RankingStrip
       *  Apply buttons use, so clicking ANY backtick-wrapped SMILES
       *  here loads it into 2D + 3D + auto-scores. */}
      {state.summary && (
        <div style={{
          marginTop: 4, padding: "6px 9px",
          background: GREEN.bg, border: `1px solid ${GREEN.border}`,
          borderLeft: `3px solid ${GREEN.fg}`,
          borderRadius: 4,
        }}>
          <MarkdownText
            text={state.summary}
            fontSize={12.5}
            onLoadSmiles={(smi) => {
              window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
                detail: { text: `/load ${smi}` },
              }));
            }}
          />
        </div>
      )}

      {/* Error banner */}
      {state.status === "error" && state.error && (
        <div style={{
          padding: "5px 8px",
          background: RED.bg, border: `1px solid ${RED.border}`,
          borderRadius: 4, fontSize: 9.5, color: RED.fg,
          fontFamily: "var(--lys-font-mono)",
        }}>⚠ {state.error}</div>
      )}

      {/* Cancelled banner */}
      {state.status === "cancelled" && (
        <div style={{
          padding: "5px 8px",
          background: AMBER.bg, border: `1px solid ${AMBER.border}`,
          borderRadius: 4, fontSize: 9.5, color: AMBER.fg,
          fontFamily: "var(--lys-font-mono)",
        }}>workflow cancelled</div>
      )}

      {/* state_dump exposed via raw JSON used to live here as a debug
       *  toggle but the truncated string preview was unreadable noise.
       *  All useful surface (ranking, summary, errors) is already
       *  rendered above; the underlying state_dump remains in the
       *  events stream for replay/debugging tools. */}
    </div>
  );
}

/** Compact list of ranked candidates with an Apply button per row.
 *  This is the missing "action taken" piece: the workflow lists
 *  candidates, the user clicks Apply, the molecule loads into 2D + 3D
 *  + auto-scores. Wired via the global `lysos:auto-slash` event so we
 *  don't need to plumb a callback through every layer. */
function RankingStrip({ ranking }: {
  ranking: Array<{ smiles: string; composite?: number; robustness?: number; fitness?: number }>;
}) {
  const apply = (smi: string) => {
    // Re-uses the existing /load slash handler in WorkbenchV3 so the
    // single source of truth for "load a SMILES" stays loadSmilesIntoCanvas.
    window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
      detail: { text: `/load ${smi}` },
    }));
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      {ranking.map((r, i) => (
        <div key={i} style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "4px 7px",
          background: i === 0 ? GREEN.bg : "rgba(255,255,255,0.55)",
          border: `1px solid ${i === 0 ? GREEN.border : LAV.border}`,
          borderLeft: `3px solid ${i === 0 ? GREEN.fg : LAV.fg}`,
          borderRadius: 4,
          fontFamily: "var(--lys-font-body)", fontSize: 11.5,
        }}>
          <span style={{
            fontFamily: "var(--lys-font-mono)", fontSize: 10.5,
            color: i === 0 ? GREEN.fg : LAV.fgDeep, fontWeight: 700,
            minWidth: 14,
          }}>#{i + 1}</span>
          <code style={{
            fontFamily: "var(--lys-font-mono)", fontSize: 11,
            color: "var(--lys-text)",
            background: "transparent",
            flex: 1, minWidth: 0,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>{r.smiles}</code>
          {typeof r.fitness === "number" && (
            <span style={{
              fontFamily: "var(--lys-font-mono)", fontSize: 10,
              color: "var(--lys-text-faint)", flexShrink: 0,
            }}>fit {r.fitness.toFixed(2)}</span>
          )}
          {typeof r.composite === "number" && (
            <span style={{
              fontFamily: "var(--lys-font-mono)", fontSize: 10,
              color: "var(--lys-text-faint)", flexShrink: 0,
            }}>· score {r.composite.toFixed(2)}</span>
          )}
          <button
            onClick={() => apply(r.smiles)}
            title="Load into the 2D builder + 3D theater + auto-score"
            style={{
              padding: "2px 8px",
              fontSize: 10.5, fontWeight: 700, fontFamily: "var(--lys-font-body)",
              background: i === 0 ? GREEN.fg : LAV.fgDeep,
              color: "white", border: 0, borderRadius: 3,
              cursor: "pointer", flexShrink: 0,
            }}>apply</button>
        </div>
      ))}
    </div>
  );
}


function StepRow({ step }: { step: WorkflowStep }) {
  const [open, setOpen] = useState(false);
  const tier = step.status === "done" ? GREEN
             : step.status === "error" ? RED
             : step.status === "running" ? AMBER
             : step.status === "skipped" ? GREY
             : GREY;
  const Icon = step.status === "done" ? CheckCircle2
             : step.status === "error" ? AlertCircle
             : step.status === "running" ? Loader2
             : step.status === "skipped" ? MinusCircle
             : Circle;
  const elapsed = step.elapsed_ms != null
    ? step.elapsed_ms < 1000 ? `${step.elapsed_ms}ms` : `${(step.elapsed_ms / 1000).toFixed(1)}s`
    : null;

  return (
    // Borderless step row — only the open state gets a soft surface.
    // The status icon's color carries the visual signal; no need for
    // a full bordered card per row. Saves ~30% vertical space.
    <div>
      <button onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%", textAlign: "left",
          display: "flex", alignItems: "center", gap: 6,
          background: "transparent", border: 0, cursor: "pointer",
          padding: "1px 0",
          fontSize: 12, fontFamily: "var(--lys-font-body)",
        }}>
        {open ? <ChevronDown size={11} color="var(--lys-text-faint)" />
              : <ChevronRight size={11} color="var(--lys-text-faint)" />}
        <Icon size={12} style={{
          color: tier.fg, flexShrink: 0,
          ...(step.status === "running" ? { animation: "lys-spin 0.9s linear infinite" } : {}),
        }} />
        <span style={{ fontFamily: "var(--lys-font-mono)", fontWeight: 700,
          color: tier.fg, fontSize: 11 }}>{step.id}</span>
        <span style={{ color: "var(--lys-text-dim)", flex: 1,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {step.label}
        </span>
        {step.progress && (
          <span style={{
            fontFamily: "var(--lys-font-mono)", fontSize: 8.5,
            color: AMBER.fg, fontWeight: 700,
          }}>{step.progress.i + 1}/{step.progress.n}</span>
        )}
        {step.retry_attempts && step.retry_attempts > 0 ? (
          <span style={{
            padding: "0 4px", borderRadius: 2,
            background: AMBER.bg, color: AMBER.fg,
            fontSize: 8, fontFamily: "var(--lys-font-mono)", fontWeight: 700,
          }}>retry {step.retry_attempts}</span>
        ) : null}
        {elapsed && (
          <span style={{
            fontFamily: "var(--lys-font-mono)", fontSize: 8.5,
            color: "var(--lys-text-faint)", flexShrink: 0,
          }}>{elapsed}</span>
        )}
      </button>

      {open && (
        <div style={{ marginTop: 4 }}>
          {step.description && (
            <div style={{
              fontSize: 9.5, color: "var(--lys-text-dim)",
              marginBottom: 3, lineHeight: 1.4,
            }}>{step.description}</div>
          )}
          {step.tool && step.tool !== "__inline__" && (
            <div style={{
              fontSize: 9, fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-faint)", marginBottom: 3,
            }}>tool: <code>{step.tool}</code></div>
          )}
          {step.error && (
            <div style={{
              padding: "3px 6px",
              background: RED.bg, border: `1px solid ${RED.border}`,
              borderRadius: 3,
              fontFamily: "var(--lys-font-mono)", fontSize: 9, color: RED.fg,
              wordBreak: "break-word",
            }}>{step.error}</div>
          )}
          {step.result !== undefined && step.status === "done" && (
            <pre style={{
              margin: 0, padding: "4px 6px",
              background: "rgba(0,0,0,0.04)", border: "1px solid rgba(0,0,0,0.06)",
              borderRadius: 3,
              fontFamily: "var(--lys-font-mono)", fontSize: 8.5, lineHeight: 1.45,
              maxHeight: 220, overflow: "auto",
              whiteSpace: "pre-wrap", wordBreak: "break-word",
              color: "var(--lys-text-dim)",
            }}>{safeStringify(step.result)}</pre>
          )}
        </div>
      )}
    </div>
  );
}


function StatusPill({ status, elapsed_ms }: { status: WorkflowState["status"]; elapsed_ms?: number }) {
  const tier = status === "done" ? GREEN
             : status === "error" ? RED
             : status === "cancelled" ? AMBER
             : LAV;
  const label = status === "done" ? "done"
              : status === "error" ? "error"
              : status === "cancelled" ? "cancelled"
              : "running";
  const elapsed = elapsed_ms != null
    ? elapsed_ms < 1000 ? `${elapsed_ms}ms` : `${(elapsed_ms / 1000).toFixed(1)}s`
    : null;
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 999,
      background: tier.bg, border: `1px solid ${tier.border}`,
      color: status === "running" ? LAV.fgDeep : tier.fg,
      fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
      letterSpacing: "0.04em", textTransform: "uppercase", fontWeight: 700,
      display: "inline-flex", alignItems: "center", gap: 3,
      whiteSpace: "nowrap", flexShrink: 0,
    }}>
      {status === "running" && <Loader2 size={9} className="lys-spin" />}
      {label}{elapsed ? ` · ${elapsed}` : ""}
    </span>
  );
}


function safeStringify(obj: any): string {
  try {
    const s = JSON.stringify(obj, null, 2);
    return s.length > 6000 ? s.slice(0, 6000) + "\n…(truncated)" : s;
  } catch {
    return String(obj);
  }
}
