/**
 * useSession — React hook subscribing to the harness WebSocket.
 *
 * Manages a single connection to /ws/session/<id>?user=<u>, handles
 * reconnect with exponential backoff, surfaces typed event streams to
 * consumers, and exposes typed action senders.
 *
 * Use:
 *   const sess = useSession({ sessionId, userId });
 *   sess.runCell("print(2+2)");
 *   sess.sendChat("/score CCO");
 *   sess.events.cells       // [Cell, ...] in arrival order
 *   sess.events.scene       // [SceneEvent, ...]
 *   sess.events.messages    // chat messages (ChatResponse-shaped)
 *   sess.connection         // "connecting" | "open" | "closed" | "error"
 *
 * Backend contract (workspace/api/chat.py):
 *   client→server actions:  chat | run_cell | scene | set_active_smiles |
 *                           set_active_target | ping
 *   server→client events:   chat.message | cell.done | scene.event |
 *                           session.snapshot | session.smiles |
 *                           session.target | error | pong
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

// ---- types (mirror server-side payload shapes) ----

export type ConnectionState = "idle" | "connecting" | "open" | "closed" | "error";

export interface CellPayload {
  cell_id: string;
  code: string;
  status: "done" | "error" | "running" | "timeout" | "pending";
  stdout: string;
  stderr: string;
  elapsed_ms: number;
  structured?: Record<string, unknown>;
  scene_events?: SceneEventPayload[];
}

export interface SceneEventPayload {
  event_id: string;
  kind: string;
  payload: Record<string, unknown>;
  timestamp: number;
  actor: string;
}

export interface ChatMessagePayload {
  text: string;
  error: string;
  artifact?: Record<string, unknown> | null;
  follow_ups?: string[];
  elapsed_ms?: number;
  trace?: Array<Record<string, unknown>>;
}

export interface SessionSnapshot {
  meta: {
    session_id: string;
    user_id: string;
    active_smiles: string | null;
    active_target: string | null;
    settings: Record<string, unknown>;
  };
  scene: {
    scene_id: string;
    objects: unknown[];
    camera: unknown;
    n_events: number;
  };
  n_cells: number;
}

interface UseSessionOptions {
  sessionId: string;
  userId?: string;
  apiBase?: string;        // e.g. "" | "http://localhost:8000"
  autoConnect?: boolean;   // default true
}

interface SessionEvents {
  cells: CellPayload[];
  scene: SceneEventPayload[];
  messages: ChatMessagePayload[];
  snapshot: SessionSnapshot | null;
}

// ---- hook ----

export function useSession({
  sessionId,
  userId = "anonymous",
  apiBase = "",
  autoConnect = true,
}: UseSessionOptions) {
  const [connection, setConnection] = useState<ConnectionState>("idle");
  const [events, setEvents] = useState<SessionEvents>({
    cells: [], scene: [], messages: [], snapshot: null,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef({ attempts: 0, timer: 0 as number | NodeJS.Timeout });
  const closedByCallerRef = useRef(false);

  const wsUrl = useMemo(() => {
    // Resolve the WS scheme from the API base / window.location
    let base = apiBase;
    if (!base) base = "";
    let host = base;
    if (!base) {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      host = `${proto}//${window.location.host}`;
    } else if (base.startsWith("http://")) {
      host = base.replace("http://", "ws://");
    } else if (base.startsWith("https://")) {
      host = base.replace("https://", "wss://");
    }
    return `${host}/ws/session/${sessionId}?user=${encodeURIComponent(userId)}`;
  }, [apiBase, sessionId, userId]);

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState <= 1) return;
    setConnection("connecting");
    closedByCallerRef.current = false;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.addEventListener("open", () => {
      setConnection("open");
      retryRef.current.attempts = 0;
    });

    ws.addEventListener("message", (e: MessageEvent) => {
      let msg: { event?: string; [k: string]: unknown };
      try {
        msg = JSON.parse(e.data);
      } catch {
        return;
      }
      switch (msg.event) {
        case "session.snapshot":
          setEvents((s) => ({ ...s, snapshot: msg.session as SessionSnapshot }));
          break;
        case "cell.done": {
          const cell = msg.cell as CellPayload;
          setEvents((s) => ({ ...s, cells: [...s.cells, cell] }));
          break;
        }
        case "scene.event": {
          const ev = msg.scene_event as SceneEventPayload;
          setEvents((s) => ({ ...s, scene: [...s.scene, ev] }));
          break;
        }
        case "chat.message": {
          const m = {
            text: (msg.text as string) ?? "",
            error: (msg.error as string) ?? "",
            artifact: msg.artifact as Record<string, unknown> | null,
            follow_ups: msg.follow_ups as string[] | undefined,
            elapsed_ms: msg.elapsed_ms as number | undefined,
            trace: msg.trace as Array<Record<string, unknown>> | undefined,
          };
          setEvents((s) => ({ ...s, messages: [...s.messages, m] }));
          break;
        }
        default:
          // session.smiles / session.target / error / pong — surface as msg
          break;
      }
    });

    ws.addEventListener("error", () => {
      setConnection("error");
    });

    ws.addEventListener("close", () => {
      setConnection("closed");
      if (closedByCallerRef.current) return;
      // Exponential backoff reconnect: 1s, 2s, 4s, 8s, capped 30s
      retryRef.current.attempts += 1;
      const delay = Math.min(30000, 1000 * 2 ** Math.min(retryRef.current.attempts - 1, 5));
      clearTimeout(retryRef.current.timer as number);
      retryRef.current.timer = setTimeout(connect, delay);
    });
  }, [wsUrl]);

  const disconnect = useCallback(() => {
    closedByCallerRef.current = true;
    clearTimeout(retryRef.current.timer as number);
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const send = useCallback((payload: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== 1) return false;
    ws.send(JSON.stringify(payload));
    return true;
  }, []);

  // ---- typed action senders ----

  const sendChat = useCallback((text: string) => send({ action: "chat", text }), [send]);
  const runCell = useCallback((code: string) => send({ action: "run_cell", code }), [send]);
  const emitScene = useCallback(
    (kind: string, payload: Record<string, unknown> = {}) =>
      send({ action: "scene", kind, payload }),
    [send],
  );
  const setActiveSmiles = useCallback(
    (smiles: string | null) => send({ action: "set_active_smiles", smiles }),
    [send],
  );
  const setActiveTarget = useCallback(
    (target: string | null) => send({ action: "set_active_target", target }),
    [send],
  );
  const ping = useCallback(() => send({ action: "ping" }), [send]);

  useEffect(() => {
    if (autoConnect) connect();
    return () => {
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsUrl, autoConnect]);

  return {
    connection,
    events,
    sendChat,
    runCell,
    emitScene,
    setActiveSmiles,
    setActiveTarget,
    ping,
    connect,
    disconnect,
  };
}
