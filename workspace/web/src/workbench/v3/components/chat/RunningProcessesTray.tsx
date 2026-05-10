/**
 * RunningProcessesTray — sticky strip at the top of the chat panel
 * showing every in-flight process (agent runs, workflow runs, score
 * jobs) with live progress + cancel controls. Auto-hides when no
 * processes are running.
 *
 * Pulls process state from the chat events stream (single source of
 * truth) — same `agent_run` / `workflow_run` rows the message timeline
 * already renders. Each process can be:
 *   - "agent"     — Gemini tool-calling SSE stream
 *   - "workflow"  — declarative pipeline run (workflows.py)
 *   - "score"     — auto-scoring task fired on candidate-add
 *
 * Visual: lavender-glass banner with a row per process. Each row shows
 * an icon, name, progress (e.g. "step 2 of 4: harden_each · 3/4"),
 * elapsed timer, and a cancel × button. Click the row to scroll the
 * chat timeline to that process's card.
 */
import { useEffect, useState } from "react";
import { Loader2, Sparkles, Workflow as WorkflowIcon, X as IconX } from "lucide-react";

const LAV = {
  bg: "rgba(174, 158, 244, 0.10)",
  bgStrong: "rgba(174, 158, 244, 0.18)",
  border: "rgba(174, 158, 244, 0.32)",
  borderStrong: "rgba(174, 158, 244, 0.48)",
  fg: "#7c63d8",
  fgDeep: "#6041d0",
} as const;

const RED = { bg: "rgba(220,38,38,0.10)", border: "rgba(220,38,38,0.30)", fg: "#dc2626" };

export interface RunningProcess {
  /** Unique row id (run_id from the corresponding event row). */
  id: string;
  kind: "agent" | "workflow" | "score";
  /** Display name, e.g. "harden_candidate" or "score_explain". */
  name: string;
  /** Free-form status sub-label, e.g. "harden_each · 3/4". */
  status: string;
  /** ms since started — used to render an elapsed timer. */
  startedAt: number;
  cancellable?: boolean;
  onCancel?: () => void;
  onClick?: () => void;
}

interface Props {
  processes: RunningProcess[];
  /** Optional max-rows shown — extra collapse to "+N more". */
  maxVisible?: number;
}

export function RunningProcessesTray({ processes, maxVisible = 4 }: Props) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (processes.length === 0) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [processes.length]);

  if (processes.length === 0) return null;

  const visible = processes.slice(0, maxVisible);
  const hidden = processes.length - visible.length;

  // Single thin strip — all running processes inline as compact pills,
  // no parent box, no "RUNNING · N" header. Matches Claude Desktop's
  // top-of-thread "running" indicator: present when needed, invisible
  // otherwise. Click a pill to scroll to that row in the timeline.
  const top = visible[0];
  return (
    <div style={{
      position: "sticky", top: 0, zIndex: 20,
      // Solid white background so messages scrolling underneath don't
      // bleed through the strip. Was rgba(0.85) which left a ghost of
      // overlapping text visible.
      padding: "5px 8px",
      background: "white",
      borderBottom: `1px solid ${LAV.border}`,
      boxShadow: "0 1px 3px rgba(15,23,42,0.04)",
      display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap",
      fontFamily: "var(--lys-font-body)",
      // Negative top margin to absorb the chat panel's 12px padding so
      // the strip sits flush against the panel chrome.
      marginTop: -12, marginLeft: -16, marginRight: -16,
      marginBottom: 4,
    }}>
      <Loader2 size={11} style={{
        animation: "lys-spin 0.9s linear infinite",
        color: LAV.fgDeep, flexShrink: 0,
      }} />
      {top && <ProcessPill p={top} now={now} />}
      {processes.length > 1 && (
        <span style={{
          fontSize: 10, color: LAV.fgDeep, fontWeight: 600,
          fontFamily: "var(--lys-font-mono)",
        }}>+{processes.length - 1}</span>
      )}
      {hidden > 0 && (
        <span style={{
          fontSize: 10, color: LAV.fgDeep, opacity: 0.65,
          fontFamily: "var(--lys-font-mono)",
        }}>(+{hidden} hidden)</span>
      )}
      <style>{`@keyframes lys-spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}`}</style>
    </div>
  );
}

function ProcessPill({ p, now }: { p: RunningProcess; now: number }) {
  const elapsed = Math.max(0, now - p.startedAt);
  const elapsedLabel = elapsed < 1000
    ? `${elapsed}ms`
    : elapsed < 60_000
      ? `${(elapsed / 1000).toFixed(1)}s`
      : `${Math.floor(elapsed / 60_000)}m${Math.floor((elapsed % 60_000) / 1000)}s`;
  const accent = p.kind === "workflow" ? LAV.fgDeep : LAV.fg;
  return (
    <button
      type="button"
      onClick={p.onClick}
      style={{
        display: "inline-flex", alignItems: "center", gap: 5,
        padding: "1px 6px",
        background: "transparent",
        border: 0,
        cursor: p.onClick ? "pointer" : "default",
        fontFamily: "var(--lys-font-body)",
        fontSize: 11.5, color: "var(--lys-text)",
      }}>
      <span style={{
        fontFamily: "var(--lys-font-mono)", fontSize: 10,
        color: accent, fontWeight: 700,
        textTransform: "lowercase",
      }}>{p.kind}</span>
      <span style={{ fontWeight: 600 }}>{p.name}</span>
      {p.status && (
        <span style={{
          fontSize: 11, color: "var(--lys-text-faint)",
          maxWidth: 240,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>· {p.status}</span>
      )}
      <span style={{
        fontFamily: "var(--lys-font-mono)", fontSize: 10,
        color: "var(--lys-text-faint)",
      }}>{elapsedLabel}</span>
    </button>
  );
}


// Legacy ProcessRow removed — the slim tray uses ProcessPill above.
// Keeping the unused-imports clean.
void Sparkles; void WorkflowIcon; void IconX; void RED;
