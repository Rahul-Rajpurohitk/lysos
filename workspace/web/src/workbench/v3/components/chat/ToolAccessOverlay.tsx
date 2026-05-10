/**
 * ToolAccessOverlay — floating bottom-right popup showing the most
 * recent tool call as it streams. Auto-hides after a tool finishes
 * (or after 3.5s if no new activity).
 *
 * Reads from the events stream:
 *   - agent_run rows with agent_state.steps[].kind === "tool_call"
 *   - workflow_run rows with workflow_state.steps[].status === "running"
 *   - tool_call_result / tool_call_error standalone events
 *
 * Visual: small lavender-glass card pinned bottom-right, slides in
 * from the right. One row per active tool call with kind, args
 * preview, elapsed timer, and a status pip.
 */
import { useEffect, useMemo, useState } from "react";
import { Wrench, CheckCircle2, AlertTriangle } from "lucide-react";

const LAV = {
  bg: "rgba(174, 158, 244, 0.10)",
  bgStrong: "rgba(174, 158, 244, 0.18)",
  border: "rgba(174, 158, 244, 0.32)",
  fg: "#7c63d8",
  fgDeep: "#6041d0",
} as const;

const GREEN = { bg: "rgba(16,185,129,0.10)", border: "rgba(16,185,129,0.34)", fg: "#10b981" };
const RED = { bg: "rgba(220,38,38,0.10)", border: "rgba(220,38,38,0.32)", fg: "#dc2626" };

export interface ToolAccessEvent {
  /** Stable id for this call (run_id + step idx, or tool name + ts). */
  id: string;
  tool: string;
  args?: any;
  /** "running" | "done" | "error" */
  status: "running" | "done" | "error";
  startedAt: number;
  endedAt?: number;
  result_preview?: string;
  error?: string;
  /** Source: which run produced this (agent / workflow / chat). */
  source?: string;
}

interface Props {
  events: any[];  // raw chat events array
}

export function ToolAccessOverlay({ events }: Props) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 400);
    return () => clearInterval(t);
  }, []);

  // Walk the recent events to extract tool-call activity. We render only
  // the LAST 3 tool calls (running OR recently done), and only those
  // updated within the last 5s.
  const recent = useMemo(() => {
    const tools: ToolAccessEvent[] = [];
    for (const e of events as any[]) {
      // Standalone tool_call events emitted by the harness
      if (e.type === "tool_call_result" || e.type === "tool_call_error") {
        tools.push({
          id: `${e.tool ?? "tool"}-${e.ts}`,
          tool: e.tool ?? "tool",
          args: e.args,
          status: e.type === "tool_call_error" ? "error" : "done",
          startedAt: (e.ts ?? 0) * 1000,
          endedAt: (e.ts ?? 0) * 1000,
          result_preview: typeof e.result === "string"
            ? e.result.slice(0, 80)
            : undefined,
          error: e.error,
          source: e.agent ?? "agent",
        });
      }
      // Agent run inline tool_call steps
      if (e.type === "agent_run" && e.agent_state?.steps) {
        for (const s of e.agent_state.steps) {
          if (s.kind !== "tool_call") continue;
          tools.push({
            id: `${e.run_id}-${s.id ?? s.tool ?? "step"}`,
            tool: s.tool ?? s.name ?? "tool",
            args: s.args ?? s.arguments,
            status: s.status === "error" ? "error"
                  : s.status === "done" ? "done"
                  : "running",
            startedAt: (s.started_at ?? e.ts ?? 0) * 1000,
            endedAt: s.ended_at ? s.ended_at * 1000 : undefined,
            result_preview: typeof s.result === "string"
              ? s.result.slice(0, 80) : undefined,
            error: s.error,
            source: "agent",
          });
        }
      }
      // Workflow run steps
      if (e.type === "workflow_run" && e.workflow_state?.steps) {
        for (const s of e.workflow_state.steps) {
          if (s.status !== "running" && s.status !== "done" && s.status !== "error") continue;
          tools.push({
            id: `${e.run_id}-${s.id ?? s.name}`,
            tool: s.name ?? s.id ?? "step",
            args: s.inputs,
            status: s.status,
            startedAt: (s.started_at ?? e.ts ?? 0) * 1000,
            endedAt: s.ended_at ? s.ended_at * 1000 : undefined,
            source: "workflow",
          });
        }
      }
    }
    // Sort by startedAt desc, keep last 3 active or recently-finished
    tools.sort((a, b) => b.startedAt - a.startedAt);
    const cutoff = now - 4000;
    const filtered = tools.filter((t) =>
      t.status === "running" || (t.endedAt ?? t.startedAt) > cutoff
    );
    // Dedupe by id (latest wins)
    const seen = new Set<string>();
    const out: ToolAccessEvent[] = [];
    for (const t of filtered) {
      if (seen.has(t.id)) continue;
      seen.add(t.id);
      out.push(t);
      if (out.length >= 3) break;
    }
    return out;
  }, [events, now]);

  if (recent.length === 0) return null;

  return (
    <div style={{
      position: "fixed",
      bottom: 12, right: 12,
      zIndex: 50,
      display: "flex", flexDirection: "column", gap: 4,
      pointerEvents: "none",
    }}>
      {recent.map((t) => <ToolPopup key={t.id} t={t} now={now} />)}
    </div>
  );
}

function ToolPopup({ t, now }: { t: ToolAccessEvent; now: number }) {
  const elapsed = (t.endedAt ?? now) - t.startedAt;
  const elapsedLabel = elapsed < 1000
    ? `${elapsed}ms`
    : elapsed < 60_000
      ? `${(elapsed / 1000).toFixed(1)}s`
      : `${Math.floor(elapsed / 60_000)}m${Math.floor((elapsed % 60_000) / 1000)}s`;

  const isRunning = t.status === "running";
  const isError = t.status === "error";
  const accent = isError ? RED.fg : isRunning ? LAV.fgDeep : GREEN.fg;
  const bg = isError ? RED.bg : isRunning ? LAV.bg : GREEN.bg;
  const border = isError ? RED.border : isRunning ? LAV.border : GREEN.border;

  // Render a tiny preview of args
  const argsPreview = t.args ? (() => {
    try {
      const json = typeof t.args === "string" ? t.args : JSON.stringify(t.args);
      return json.slice(0, 60) + (json.length > 60 ? "…" : "");
    } catch {
      return "";
    }
  })() : "";

  return (
    <div style={{
      pointerEvents: "auto",
      minWidth: 260, maxWidth: 360,
      padding: "5px 9px",
      background: bg,
      backdropFilter: "blur(10px)",
      border: `1px solid ${border}`,
      borderLeft: `3px solid ${accent}`,
      borderRadius: 5,
      boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
      display: "flex", flexDirection: "column", gap: 2,
      fontFamily: "var(--lys-font-body)",
      animation: "lys-tool-slide 0.2s ease-out",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 5,
        fontSize: 9.5, fontWeight: 700,
        color: accent, fontFamily: "var(--lys-font-mono)",
        textTransform: "uppercase", letterSpacing: "0.05em",
      }}>
        {isRunning ? <Wrench size={9} style={{ animation: "lys-tool-pulse 1.2s ease-in-out infinite" }} />
                  : isError ? <AlertTriangle size={10} />
                  : <CheckCircle2 size={10} />}
        <span>tool</span>
        <span style={{ color: "var(--lys-text)", fontWeight: 600, textTransform: "none", letterSpacing: 0 }}>
          {t.tool}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontSize: 8.5, color: "var(--lys-text-faint)",
          fontWeight: 600,
        }}>{elapsedLabel}</span>
      </div>
      {argsPreview && (
        <div style={{
          fontSize: 9, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-dim)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{argsPreview}</div>
      )}
      {t.result_preview && (
        <div style={{
          fontSize: 9, color: "var(--lys-text-faint)",
          fontStyle: "italic",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>→ {t.result_preview}</div>
      )}
      {t.error && (
        <div style={{
          fontSize: 9, color: RED.fg, fontWeight: 600,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{t.error.slice(0, 80)}</div>
      )}
      <style>{`
        @keyframes lys-tool-slide {
          from { transform: translateX(20px); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        @keyframes lys-tool-pulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.15); opacity: 0.7; }
        }
      `}</style>
    </div>
  );
}
