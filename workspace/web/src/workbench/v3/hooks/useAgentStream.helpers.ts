/**
 * Standalone reducer for SSE agent events. Same logic as the one inside
 * useAgentStream's hook, exported so the chat composer can reduce events
 * inline against an arbitrary event row in the timeline (one row per run).
 */
import type { AgentState, AgentStep } from "./useAgentStream";

export function reduceAgentEventStandalone(prev: AgentState, ev: any): AgentState {
  const e = ev?.event as string | undefined;
  switch (e) {
    case "agent.start":
      return { ...prev, status: "running", user_text: ev.user_text ?? prev.user_text };
    case "agent.thinking":
      return { ...prev, steps: [...prev.steps,
        { kind: "thinking", text: String(ev.text ?? "") } as AgentStep] };
    case "tool.call":
      return {
        ...prev,
        n_tool_calls: prev.n_tool_calls + 1,
        steps: [...prev.steps, {
          kind: "tool_call",
          call_id: String(ev.call_id),
          tool: String(ev.tool),
          args: ev.args ?? {},
          status: "running",
        } as AgentStep],
      };
    case "tool.result": {
      const idx = prev.steps.findIndex(
        (s) => s.kind === "tool_call" && s.call_id === ev.call_id);
      if (idx < 0) return prev;
      const next = [...prev.steps];
      next[idx] = { ...next[idx] as any, status: "ok",
        elapsed_ms: ev.elapsed_ms, result: ev.result };
      return { ...prev, steps: next };
    }
    case "tool.error": {
      const idx = prev.steps.findIndex(
        (s) => s.kind === "tool_call" && s.call_id === ev.call_id);
      if (idx < 0) return prev;
      const next = [...prev.steps];
      next[idx] = { ...next[idx] as any, status: "error",
        error: String(ev.error ?? "") };
      return { ...prev, steps: next };
    }
    case "text.delta": {
      const txt = String(ev.text ?? "");
      const last = prev.steps[prev.steps.length - 1];
      if (last?.kind === "text") {
        const updated = [...prev.steps];
        updated[updated.length - 1] = { kind: "text", text: last.text + txt };
        return { ...prev, steps: updated, text: prev.text + txt };
      }
      return {
        ...prev,
        steps: [...prev.steps, { kind: "text", text: txt }],
        text: prev.text + txt,
      };
    }
    case "agent.done":
      return { ...prev, status: "done", elapsed_ms: ev.elapsed_ms,
        n_tool_calls: ev.n_tool_calls ?? prev.n_tool_calls };
    case "agent.error":
      return { ...prev, status: "error", error: String(ev.error ?? "") };
    default:
      return prev;
  }
}
