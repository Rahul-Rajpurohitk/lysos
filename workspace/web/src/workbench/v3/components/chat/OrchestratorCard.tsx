/**
 * OrchestratorCard — Claude Desktop / Claude Code style chat surface.
 *
 * Critical contract: the orchestrator wraps DELEGATED execution
 * (workflow / agent / slash) — it does NOT render its own
 * representation of those. Instead it reduces the wrapped sub_events
 * through the SAME reducer the standalone path uses, and mounts the
 * SAME card component (WorkflowCard / AgentMessageCard / answer
 * prose). The user sees one "real" execution view, not a duplicated
 * second-tier shell.
 *
 * Render branches:
 *   - route === "answer"   → pure prose with tiny "↳ via gemini · 4.2s"
 *                            footer (no card chrome at all)
 *   - route === "workflow" → tiny one-line "via orchestrator" header
 *                            then the live WorkflowCard inline
 *   - route === "agent"    → same idea, AgentMessageCard inline
 *   - route === "slash"    → tiny "→ /score …" pill (the actual slash
 *                            response will land as its own message row)
 *
 * Reducer (unchanged contract):
 *   reduceOrchestratorEvent(state, ev) → next state, fed by SSE from
 *   /api/orchestrator/run.
 */
import { useMemo, useState } from "react";
import {
  Sparkles, Zap, Workflow as WorkflowIcon,
  AlertTriangle, ChevronRight,
} from "lucide-react";
import { reduceWorkflowEvent, type WorkflowState, WorkflowCard } from "./WorkflowCard";
import { reduceAgentEventStandalone } from "../../hooks/useAgentStream.helpers";
import type { AgentState } from "../../hooks/useAgentStream";
import { AgentMessageCard } from "./AgentMessageCard";
import { MarkdownText } from "./MarkdownText";

const COL = {
  fg: "var(--lys-text)",
  fgDim: "var(--lys-text-dim)",
  fgFaint: "var(--lys-text-faint)",
  lav: "#7c63d8",
  lavDeep: "#6041d0",
  green: "#10b981",
  red: "#dc2626",
  amber: "#ca8a04",
} as const;

export interface OrchestratorState {
  run_id: string;
  user_text: string;
  status: "running" | "done" | "error";
  plan?: {
    route?: "workflow" | "slash" | "agent" | "answer";
    rationale?: string;
    name?: string | null;
    inputs?: Record<string, any>;
    answer?: string;
  };
  plan_source?: string;
  dispatch?: {
    command: string;
    rendered: string;
    args?: Record<string, any>;
  };
  answer_text?: string;
  sub_events?: Array<{ event?: string; type?: string; sub_kind?: string; [k: string]: any }>;
  error?: string;
  elapsed_ms?: number;
}

export function reduceOrchestratorEvent(prev: OrchestratorState, ev: any): OrchestratorState {
  const evt = ev?.event ?? ev?.type;
  if (evt === "orchestrator.start") {
    return { ...prev, run_id: ev.run_id ?? prev.run_id, status: "running" };
  }
  if (evt === "orchestrator.plan") {
    return { ...prev, plan: ev.plan, plan_source: ev.plan_source };
  }
  if (evt === "orchestrator.answer") {
    return { ...prev, answer_text: ev.text };
  }
  if (evt === "orchestrator.dispatch_slash") {
    return {
      ...prev,
      dispatch: {
        command: ev.command,
        rendered: ev.rendered,
        args: ev.args,
      },
    };
  }
  if (evt === "orchestrator.delegate") {
    return {
      ...prev,
      // Push the inner sub_event AND its sub_kind ("workflow" / "agent")
      // so we can route to the right reducer downstream.
      sub_events: [...(prev.sub_events ?? []), {
        ...ev.sub_event,
        sub_kind: ev.sub_kind,
      }],
    };
  }
  if (evt === "orchestrator.error") {
    return { ...prev, status: "error", error: ev.error };
  }
  if (evt === "orchestrator.done") {
    return {
      ...prev,
      status: prev.status === "error" ? "error" : "done",
      elapsed_ms: ev.elapsed_ms,
    };
  }
  return prev;
}

interface Props {
  state: OrchestratorState;
  apiBase?: string;
}

function fmtElapsed(ms?: number): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m${Math.floor((ms % 60_000) / 1000)}s`;
}

export function OrchestratorCard({ state, apiBase = "" }: Props) {
  const route = state.plan?.route;

  // ─── Route 1: ANSWER — pure prose, no card chrome ───────────────
  if (route === "answer") {
    return <AnswerView state={state} />;
  }

  // ─── Still routing ───────────────────────────────────────────────
  if (state.status === "running" && !route) {
    return <ThinkingHeader />;
  }

  // ─── Route 2: WORKFLOW — render actual WorkflowCard inline ──────
  if (route === "workflow") {
    return <WorkflowDelegateView state={state} apiBase={apiBase} />;
  }

  // ─── Route 3: AGENT — render AgentMessageCard inline ────────────
  if (route === "agent") {
    return <AgentDelegateView state={state} />;
  }

  // ─── Route 4: SLASH ─────────────────────────────────────────────
  if (route === "slash") {
    return <SlashView state={state} />;
  }

  // Fallback for error / unknown routes
  return <ErrorView state={state} />;
}

function ThinkingHeader() {
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "2px 0",
      color: COL.fgFaint,
      fontSize: 12,
      fontFamily: "var(--lys-font-body)",
    }}>
      <ThinkingDots />
      <span>routing…</span>
    </div>
  );
}

function ErrorView({ state }: { state: OrchestratorState }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6,
      fontSize: 12.5, color: COL.red,
      fontFamily: "var(--lys-font-body)",
    }}>
      <AlertTriangle size={12} />
      <span>{state.error ?? "orchestrator failed"}</span>
    </div>
  );
}

/** Pure-prose answer view. Looks like a Claude Desktop assistant
 *  message: just text on the page, no border/box, with a small
 *  faint disclosure underneath. */
function AnswerView({ state }: { state: OrchestratorState }) {
  const text = state.answer_text;
  const isWaiting = state.status === "running" && !text;
  const elapsed = fmtElapsed(state.elapsed_ms);

  return (
    <div style={{
      fontFamily: "var(--lys-font-body)",
      color: COL.fg,
      fontSize: 14,
      lineHeight: 1.6,
      padding: "2px 0",
    }}>
      {isWaiting && <ThinkingHeader />}
      {text && <MarkdownText text={text} fontSize={14} />}
      {state.error && (
        <div style={{
          marginTop: 4,
          color: COL.red, fontSize: 12,
          display: "inline-flex", alignItems: "center", gap: 4,
        }}>
          <AlertTriangle size={11} /> {state.error}
        </div>
      )}
      {!isWaiting && (text || state.error) && elapsed && (
        <div style={{
          marginTop: 6,
          fontFamily: "var(--lys-font-mono)",
          fontSize: 10, color: COL.fgFaint,
          opacity: 0.7,
        }}>
          ↳ {elapsed}
        </div>
      )}
    </div>
  );
}

/** Render the actual WorkflowCard live, fed by reducing the
 *  delegated sub_events through reduceWorkflowEvent. The user sees
 *  the real workflow plan + step-by-step progress + summary —
 *  exactly the same surface as a standalone /wf invocation. */
function WorkflowDelegateView({ state, apiBase }: { state: OrchestratorState; apiBase: string }) {
  // Reduce sub_events into a WorkflowState
  const wfState = useMemo<WorkflowState | null>(() => {
    let acc: WorkflowState | null = null;
    for (const s of state.sub_events ?? []) {
      if (s.sub_kind && s.sub_kind !== "workflow") continue;
      acc = reduceWorkflowEvent(acc, s);
    }
    return acc;
  }, [state.sub_events]);

  return (
    <div style={{ fontFamily: "var(--lys-font-body)" }}>
      {/* tiny one-line breadcrumb above the workflow card */}
      <RouteBreadcrumb state={state} />
      {wfState ? (
        <div style={{ marginTop: 4 }}>
          <WorkflowCard state={wfState} apiBase={apiBase} />
        </div>
      ) : (
        <ThinkingHeader />
      )}
    </div>
  );
}

/** Render AgentMessageCard live for route=agent. */
function AgentDelegateView({ state }: { state: OrchestratorState }) {
  const agentState = useMemo<AgentState | null>(() => {
    let acc: AgentState = {
      status: "running",
      user_text: state.user_text,
      steps: [],
      text: "",
      n_tool_calls: 0,
    };
    let any = false;
    for (const s of state.sub_events ?? []) {
      if (s.sub_kind && s.sub_kind !== "agent") continue;
      acc = reduceAgentEventStandalone(acc, s);
      any = true;
    }
    return any ? acc : null;
  }, [state.sub_events, state.user_text]);

  return (
    <div style={{ fontFamily: "var(--lys-font-body)" }}>
      <RouteBreadcrumb state={state} />
      {agentState ? (
        <div style={{ marginTop: 4 }}>
          <AgentMessageCard state={agentState} />
        </div>
      ) : (
        <ThinkingHeader />
      )}
    </div>
  );
}

/** Slash dispatch — tiny pill summary; the real slash response
 *  appears as a separate message row from the auto-fired /api/chat. */
function SlashView({ state }: { state: OrchestratorState }) {
  const elapsed = fmtElapsed(state.elapsed_ms);
  return (
    <div style={{ fontFamily: "var(--lys-font-body)" }}>
      <RouteBreadcrumb state={state} />
      {state.dispatch && (
        <div style={{
          marginTop: 4, marginLeft: 18,
          display: "inline-flex", alignItems: "center", gap: 6,
          padding: "3px 8px",
          background: "rgba(202,138,4,0.08)",
          border: "1px solid rgba(202,138,4,0.32)",
          borderRadius: 4,
          fontFamily: "var(--lys-font-mono)", fontSize: 11.5,
          color: COL.amber, fontWeight: 600,
        }}>
          <Zap size={10} />
          {state.dispatch.rendered}
        </div>
      )}
      {elapsed && state.status === "done" && (
        <div style={{
          marginTop: 4, marginLeft: 18,
          fontSize: 10, fontFamily: "var(--lys-font-mono)",
          color: COL.fgFaint, opacity: 0.7,
        }}>
          ↳ {elapsed}
        </div>
      )}
    </div>
  );
}

/** Tiny one-line breadcrumb showing the routing decision — sits
 *  above the delegated card. Click to toggle the rationale. */
function RouteBreadcrumb({ state }: { state: OrchestratorState }) {
  const [open, setOpen] = useState(false);
  const route = state.plan?.route;
  const Icon = route === "workflow" ? WorkflowIcon
              : route === "slash" ? Zap
              : route === "agent" ? Sparkles
              : Sparkles;
  const accent = state.status === "error" ? COL.red
                : state.status === "done" ? COL.green
                : COL.lavDeep;
  return (
    <button
      type="button"
      onClick={() => setOpen((v) => !v)}
      style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "2px 0", width: "100%",
        background: "transparent", border: 0, cursor: "pointer",
        fontFamily: "inherit", color: "inherit", textAlign: "left",
      }}>
      <ChevronRight
        size={11}
        color={COL.fgFaint}
        style={{
          transition: "transform 0.15s",
          transform: open ? "rotate(90deg)" : "none",
          flexShrink: 0,
        }}
      />
      <Icon size={11} color={accent} style={{ flexShrink: 0 }} />
      <span style={{
        fontSize: 10, fontFamily: "var(--lys-font-mono)",
        color: COL.fgFaint, fontWeight: 600,
        textTransform: "uppercase", letterSpacing: "0.05em",
      }}>via orchestrator → {route}</span>
      <span style={{ flex: 1 }} />
      {open && state.plan?.rationale && (
        <div style={{
          fontSize: 11, color: COL.fgDim,
          fontStyle: "italic",
          maxWidth: 360,
          textAlign: "right",
          whiteSpace: "normal",
          lineHeight: 1.4,
        }}>
          {state.plan.rationale}
        </div>
      )}
    </button>
  );
}

function ThinkingDots() {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
      <Dot delay={0} />
      <Dot delay={0.2} />
      <Dot delay={0.4} />
      <style>{`
        @keyframes lys-orch-bounce {
          0%, 80%, 100% { transform: scale(0.5); opacity: 0.4; }
          40% { transform: scale(1); opacity: 1; }
        }
      `}</style>
    </span>
  );
}

function Dot({ delay }: { delay: number }) {
  return (
    <span style={{
      width: 4, height: 4, borderRadius: 999,
      background: COL.lavDeep,
      display: "inline-block",
      animation: `lys-orch-bounce 1.2s infinite ease-in-out`,
      animationDelay: `${delay}s`,
    }} />
  );
}
