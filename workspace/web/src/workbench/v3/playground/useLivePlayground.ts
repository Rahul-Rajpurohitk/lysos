/**
 * useLivePlayground — WebSocket client for /ws/playground/{sid}.
 *
 * Connects to the live editing protocol, surfaces typed action senders,
 * tracks per-actor cursor presence, and aggregates the recent edit log.
 *
 * Reconnect logic: exponential backoff 1s → 2s → 4s → 8s, capped at 30s.
 * StrictMode-safe via ref-tracked in-flight connections.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export interface PlaygroundEvent {
  event: string;
  ts?: number;
  event_id?: string;
  actor?: string;
  agent?: string;
  molecule_id?: string;
  atom_idx?: number;
  atom_idxs?: number[];
  from_smiles?: string;
  to_smiles?: string;
  edit?: any;
  hints?: Record<string, string>;
  predicted?: any;
  reason?: string;
  rationale?: string;
  client_op_id?: string;
  recent_edits?: any[];
  [k: string]: any;
}

export interface CursorPresence {
  actor: string;
  molecule_id?: string;
  atom_idx?: number;
  ts: number;
}

export interface UseLivePlaygroundResult {
  connected: boolean;
  latest: PlaygroundEvent | null;
  cursors: Record<string, CursorPresence>; // by actor name
  recentEdits: PlaygroundEvent[];
  sendCursor: (params: { actor: string; molecule_id?: string; atom_idx?: number }) => void;
  sendHover: (params: { actor: string; molecule_id?: string; atom_idx: number; smiles?: string; predict_edit?: any }) => void;
  sendEdit: (params: { actor: string; molecule_id?: string; smiles: string; edit: any; clientOpId?: string }) => void;
  sendSelect: (params: { actor: string; molecule_id?: string; atom_idxs: number[] }) => void;
  sendAgentThinking: (params: { agent: string; molecule_id?: string; atom_idx?: number; rationale: string; confidence?: number; references?: any }) => void;
}

const PING_MS = 25_000;

export function useLivePlayground(sessionId: string, apiBase: string): UseLivePlaygroundResult {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);

  const [connected, setConnected] = useState(false);
  const [latest, setLatest] = useState<PlaygroundEvent | null>(null);
  const [cursors, setCursors] = useState<Record<string, CursorPresence>>({});
  const [recentEdits, setRecentEdits] = useState<PlaygroundEvent[]>([]);

  // Convert apiBase ("http://localhost:7860" or "" for same-origin) to WS url.
  const wsUrl = (() => {
    const base = apiBase || window.location.origin;
    const url = new URL(`/workbench/playground/ws/playground/${sessionId}`, base);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
  })();

  const connect = useCallback(() => {
    if (!sessionId) return;
    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) return;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptRef.current = 0;
      setConnected(true);
    };
    ws.onclose = () => {
      setConnected(false);
      // Exponential backoff reconnect
      const attempt = ++reconnectAttemptRef.current;
      const delayMs = Math.min(30_000, 1_000 * Math.pow(2, attempt - 1));
      reconnectTimerRef.current = window.setTimeout(connect, delayMs);
    };
    ws.onerror = () => {
      // Let onclose handle reconnect
      try { ws.close(); } catch { /* */ }
    };
    ws.onmessage = (msg) => {
      try {
        const ev = JSON.parse(msg.data ?? "{}") as PlaygroundEvent;
        setLatest(ev);
        if (ev.event === "session.snapshot" && Array.isArray(ev.recent_edits)) {
          setRecentEdits(ev.recent_edits as PlaygroundEvent[]);
        }
        if (ev.event === "cursor.moved" && ev.actor) {
          setCursors((c) => ({
            ...c,
            [ev.actor!]: {
              actor: ev.actor!,
              molecule_id: ev.molecule_id,
              atom_idx: ev.atom_idx,
              ts: ev.ts ?? Date.now() / 1000,
            },
          }));
        }
        if (ev.event === "edit.applied") {
          setRecentEdits((es) => [...es, ev].slice(-200));
        }
      } catch {
        /* ignore */
      }
    };

    // Ping keepalive
    const ping = window.setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ op: "ping" }));
      }
    }, PING_MS);
    (ws as any)._pingHandle = ping;
  }, [sessionId, wsUrl]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
      const w = wsRef.current;
      if (w) {
        try {
          if ((w as any)._pingHandle) window.clearInterval((w as any)._pingHandle);
          w.close();
        } catch {/* */}
        wsRef.current = null;
      }
      setConnected(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  function send(payload: any) {
    const w = wsRef.current;
    if (!w || w.readyState !== WebSocket.OPEN) return;
    try { w.send(JSON.stringify(payload)); } catch {/* */}
  }

  const sendCursor: UseLivePlaygroundResult["sendCursor"] = useCallback((p) => {
    send({ op: "cursor.move", ...p });
  }, []);
  const sendHover: UseLivePlaygroundResult["sendHover"] = useCallback((p) => {
    send({ op: "atom.hover", ...p });
  }, []);
  const sendEdit: UseLivePlaygroundResult["sendEdit"] = useCallback((p) => {
    send({ op: "edit.apply", ...p, client_op_id: p.clientOpId ?? crypto.randomUUID() });
  }, []);
  const sendSelect: UseLivePlaygroundResult["sendSelect"] = useCallback((p) => {
    send({ op: "select", ...p });
  }, []);
  const sendAgentThinking: UseLivePlaygroundResult["sendAgentThinking"] = useCallback((p) => {
    send({ op: "agent.thinking", actor: p.agent, ...p });
  }, []);

  return { connected, latest, cursors, recentEdits, sendCursor, sendHover, sendEdit, sendSelect, sendAgentThinking };
}
