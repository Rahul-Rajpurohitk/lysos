/**
 * useAgentStream — consumes /api/agent/run SSE stream and reduces it
 * into a structured agent message: tool calls (each with input/output/
 * elapsed/error), reasoning blocks, and accumulated assistant text.
 *
 * Returned shape:
 *   { state: AgentState, run: (text) => void, stop: () => void }
 *
 * The chat panel renders one AgentMessageCard per session-message that
 * walks AgentState.steps in order: each step is a Reasoning block, a
 * ToolCall block (with collapsible JSON), or a Text block.
 */
import { useCallback, useRef, useState } from "react";

export type AgentStep =
  | { kind: "thinking"; text: string }
  | { kind: "tool_call"; call_id: string; tool: string; args: any;
      result?: any; error?: string; elapsed_ms?: number; status: "running" | "ok" | "error" }
  | { kind: "text"; text: string };

export interface AgentState {
  status: "idle" | "running" | "done" | "error";
  user_text: string;
  steps: AgentStep[];
  /** Accumulated final assistant text (concatenation of all text deltas). */
  text: string;
  /** Total elapsed once `agent.done` fires. */
  elapsed_ms?: number;
  n_tool_calls: number;
  error?: string;
}

const empty: AgentState = {
  status: "idle", user_text: "", steps: [], text: "", n_tool_calls: 0,
};

interface RunArgs {
  apiBase: string;
  sessionId: string;
  text: string;
  smiles?: string | null;
  pathogen?: string;
  pdbId?: string | null;
  onEvent?: (ev: any) => void;
}

export function useAgentStream(): {
  state: AgentState;
  run: (args: RunArgs) => void;
  stop: () => void;
  reset: () => void;
} {
  const [state, setState] = useState<AgentState>(empty);
  const abortRef = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const reset = useCallback(() => {
    stop();
    setState(empty);
  }, [stop]);

  const run = useCallback((args: RunArgs) => {
    stop();
    setState({ ...empty, status: "running", user_text: args.text });
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    (async () => {
      try {
        const r = await fetch(`${args.apiBase}/api/agent/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: args.sessionId,
            text: args.text,
            smiles: args.smiles ?? null,
            pathogen: args.pathogen ?? "MRSA",
            pdb_id: args.pdbId ?? null,
            max_iterations: 6,
          }),
          signal: ctrl.signal,
        });
        if (!r.ok || !r.body) {
          const errBody = await r.text().catch(() => "");
          setState((s) => ({ ...s, status: "error",
            error: `HTTP ${r.status}: ${errBody}` }));
          return;
        }

        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const events = buf.split("\n\n");
          buf = events.pop() ?? "";
          for (const block of events) {
            const line = block.trim();
            if (!line.startsWith("data:")) continue;
            const json = line.slice(5).trim();
            if (!json) continue;
            try {
              const ev = JSON.parse(json);
              args.onEvent?.(ev);
              setState((prev) => reduceEvent(prev, ev));
            } catch {/* skip malformed */}
          }
        }
      } catch (exc: any) {
        if (exc?.name !== "AbortError") {
          setState((s) => ({ ...s, status: "error", error: String(exc?.message ?? exc) }));
        }
      }
    })();
  }, [stop]);

  return { state, run, stop, reset };
}


function reduceEvent(prev: AgentState, ev: any): AgentState {
  const e = ev?.event as string | undefined;
  switch (e) {
    case "agent.start":
      return { ...prev, status: "running", user_text: ev.user_text ?? prev.user_text };
    case "agent.thinking":
      return { ...prev, steps: [...prev.steps, { kind: "thinking", text: String(ev.text ?? "") }] };
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
        }],
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
      next[idx] = { ...next[idx] as any, status: "error", error: String(ev.error ?? "") };
      return { ...prev, steps: next };
    }
    case "text.delta": {
      const txt = String(ev.text ?? "");
      // Append to the last text step if there is one, else start a new one.
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
