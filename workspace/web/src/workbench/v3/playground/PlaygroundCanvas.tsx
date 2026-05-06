/**
 * PlaygroundCanvas — infinite zoomable whiteboard for the right side.
 *
 * Replaces the old TabStrip-based right pane with a single canvas that
 * hosts floating, draggable, resizable windows. Pan via background-drag,
 * zoom via wheel (with cmd-zoom support).
 *
 * State model is owned at the WorkbenchV3 level and passed in:
 *   layout: Record<windowId, WindowLayout>
 *   viewport: { pan, zoom }
 *
 * The canvas renders each child PlaygroundWindow at its layout-position,
 * applying the inverse viewport transform so that pan/zoom feels stage-y
 * (windows move together as one canvas).
 *
 * Keyboard:
 *   space + drag    → pan (Figma-style)
 *   wheel           → pan (with shift to swap horizontal/vertical)
 *   cmd-wheel       → zoom anchored at cursor
 *   cmd-0           → reset viewport
 *   cmd-1           → fit-to-windows
 */
import { useEffect, useRef, useState, ReactNode } from "react";
import { Maximize2, Minimize2, X as IconX, Move } from "lucide-react";

export interface WindowLayout {
  x: number;
  y: number;
  w: number;
  h: number;
  z: number;
  visible: boolean;
  minimized?: boolean;
}

export interface Viewport {
  pan: { x: number; y: number };
  zoom: number;
}

interface PlaygroundCanvasProps {
  layout: Record<string, WindowLayout>;
  viewport: Viewport;
  onLayoutChange: (id: string, next: WindowLayout) => void;
  onViewportChange: (v: Viewport) => void;
  /** id → rendered React node (window body). Window chrome is added by the canvas. */
  windows: Record<string, { title: string; body: ReactNode; tone?: string }>;
  onClose?: (id: string) => void;
  onFocus?: (id: string) => void;
  toolbar?: ReactNode;
}

const MIN_ZOOM = 0.3;
const MAX_ZOOM = 2.5;
const SNAP = 8; // 8px grid

export function PlaygroundCanvas(p: PlaygroundCanvasProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [panning, setPanning] = useState(false);
  const panStart = useRef<{ mx: number; my: number; pan: { x: number; y: number } } | null>(null);

  // Wheel pan + cmd-wheel zoom
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (e.metaKey || e.ctrlKey) {
        e.preventDefault();
        const rect = el.getBoundingClientRect();
        const cx = e.clientX - rect.left;
        const cy = e.clientY - rect.top;
        const next = clamp(p.viewport.zoom * (1 - e.deltaY * 0.0015), MIN_ZOOM, MAX_ZOOM);
        // Anchor zoom at cursor: re-aim pan so cursor stays put
        const k = next / p.viewport.zoom;
        p.onViewportChange({
          zoom: next,
          pan: {
            x: cx - (cx - p.viewport.pan.x) * k,
            y: cy - (cy - p.viewport.pan.y) * k,
          },
        });
      } else {
        e.preventDefault();
        p.onViewportChange({
          ...p.viewport,
          pan: {
            x: p.viewport.pan.x - e.deltaX,
            y: p.viewport.pan.y - e.deltaY,
          },
        });
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [p.viewport, p.onViewportChange]);

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "0") {
        e.preventDefault();
        p.onViewportChange({ pan: { x: 0, y: 0 }, zoom: 1 });
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "1") {
        e.preventDefault();
        // Fit-to-windows: compute bounding box, zoom to fit
        const visible = Object.values(p.layout).filter((l) => l.visible);
        if (!visible.length) return;
        const minX = Math.min(...visible.map((l) => l.x));
        const minY = Math.min(...visible.map((l) => l.y));
        const maxX = Math.max(...visible.map((l) => l.x + l.w));
        const maxY = Math.max(...visible.map((l) => l.y + l.h));
        const el = stageRef.current;
        if (!el) return;
        const r = el.getBoundingClientRect();
        const PAD = 24;
        const zX = (r.width - 2 * PAD) / (maxX - minX || 1);
        const zY = (r.height - 2 * PAD) / (maxY - minY || 1);
        const zoom = clamp(Math.min(zX, zY), MIN_ZOOM, MAX_ZOOM);
        p.onViewportChange({
          zoom,
          pan: {
            x: PAD - minX * zoom,
            y: PAD - minY * zoom,
          },
        });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [p.layout, p.onViewportChange]);

  // Background drag-pan
  function onBgMouseDown(e: React.MouseEvent) {
    if (e.target !== stageRef.current && e.target !== e.currentTarget) return;
    setPanning(true);
    panStart.current = {
      mx: e.clientX,
      my: e.clientY,
      pan: { ...p.viewport.pan },
    };
  }
  useEffect(() => {
    if (!panning) return;
    const onMove = (e: MouseEvent) => {
      if (!panStart.current) return;
      const dx = e.clientX - panStart.current.mx;
      const dy = e.clientY - panStart.current.my;
      p.onViewportChange({
        ...p.viewport,
        pan: {
          x: panStart.current.pan.x + dx,
          y: panStart.current.pan.y + dy,
        },
      });
    };
    const onUp = () => {
      setPanning(false);
      panStart.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [panning, p.viewport, p.onViewportChange]);

  return (
    <div
      ref={stageRef}
      onMouseDown={onBgMouseDown}
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        overflow: "hidden",
        background: "var(--lys-bg, #fafafa)",
        backgroundImage:
          "radial-gradient(circle, rgba(15,23,42,0.06) 1px, transparent 1px)",
        backgroundSize: `${24 * p.viewport.zoom}px ${24 * p.viewport.zoom}px`,
        backgroundPosition: `${p.viewport.pan.x}px ${p.viewport.pan.y}px`,
        cursor: panning ? "grabbing" : "default",
      }}
    >
      {/* The transformed inner stage — windows live in canvas-space coords */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          transform: `translate(${p.viewport.pan.x}px, ${p.viewport.pan.y}px) scale(${p.viewport.zoom})`,
          transformOrigin: "0 0",
          width: "100%",
          height: "100%",
          pointerEvents: "none", // children opt-in
        }}
      >
        {Object.entries(p.layout).map(([id, l]) => {
          if (!l.visible) return null;
          const win = p.windows[id];
          if (!win) return null;
          return (
            <PlaygroundWindow
              key={id}
              id={id}
              layout={l}
              viewport={p.viewport}
              title={win.title}
              tone={win.tone}
              onChange={(next) => p.onLayoutChange(id, next)}
              onClose={p.onClose ? () => p.onClose!(id) : undefined}
              onFocus={p.onFocus ? () => p.onFocus!(id) : undefined}
            >
              {win.body}
            </PlaygroundWindow>
          );
        })}
      </div>

      {/* Canvas toolbar — fixed-screen-space, stays put under pan/zoom */}
      <div style={{
        position: "absolute",
        top: 8,
        right: 8,
        display: "flex",
        alignItems: "center",
        gap: 4,
        padding: "4px 8px",
        background: "rgba(255,255,255,0.85)",
        backdropFilter: "blur(6px)",
        borderRadius: 8,
        fontSize: 10.5,
        fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)",
        zIndex: 1000,
      }}>
        <span>{Math.round(p.viewport.zoom * 100)}%</span>
        <button
          type="button"
          onClick={() => p.onViewportChange({ pan: { x: 0, y: 0 }, zoom: 1 })}
          title="Reset (⌘0)"
          style={{
            border: 0,
            background: "transparent",
            cursor: "pointer",
            padding: "2px 6px",
            borderRadius: 4,
            color: "var(--lys-text-dim)",
            fontSize: 10.5,
            fontFamily: "inherit",
          }}
        >
          reset
        </button>
        {p.toolbar}
      </div>
    </div>
  );
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

// ──────────────────────────────────────────────────────────────────────
// PlaygroundWindow — shared chrome (title bar, drag, resize, close)
// ──────────────────────────────────────────────────────────────────────

interface PlaygroundWindowProps {
  id: string;
  layout: WindowLayout;
  viewport: Viewport;
  title: string;
  tone?: string;
  children: ReactNode;
  onChange: (next: WindowLayout) => void;
  onClose?: () => void;
  onFocus?: () => void;
}

function PlaygroundWindow(p: PlaygroundWindowProps) {
  const [dragging, setDragging] = useState(false);
  const [resizing, setResizing] = useState(false);
  const dragStart = useRef<{ mx: number; my: number; layout: WindowLayout } | null>(null);

  function startDrag(e: React.MouseEvent) {
    e.stopPropagation();
    setDragging(true);
    dragStart.current = { mx: e.clientX, my: e.clientY, layout: { ...p.layout } };
    p.onFocus?.();
  }
  function startResize(e: React.MouseEvent) {
    e.stopPropagation();
    setResizing(true);
    dragStart.current = { mx: e.clientX, my: e.clientY, layout: { ...p.layout } };
    p.onFocus?.();
  }

  useEffect(() => {
    if (!dragging && !resizing) return;
    const onMove = (e: MouseEvent) => {
      if (!dragStart.current) return;
      const dx = (e.clientX - dragStart.current.mx) / p.viewport.zoom;
      const dy = (e.clientY - dragStart.current.my) / p.viewport.zoom;
      if (dragging) {
        p.onChange({
          ...dragStart.current.layout,
          x: snap(dragStart.current.layout.x + dx),
          y: snap(dragStart.current.layout.y + dy),
        });
      } else if (resizing) {
        p.onChange({
          ...dragStart.current.layout,
          w: Math.max(220, snap(dragStart.current.layout.w + dx)),
          h: Math.max(160, snap(dragStart.current.layout.h + dy)),
        });
      }
    };
    const onUp = () => {
      setDragging(false);
      setResizing(false);
      dragStart.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, resizing, p.viewport.zoom, p.onChange]);

  const minimized = !!p.layout.minimized;

  return (
    <div
      style={{
        position: "absolute",
        left: p.layout.x,
        top: p.layout.y,
        width: p.layout.w,
        height: minimized ? 28 : p.layout.h,
        zIndex: p.layout.z,
        background: "var(--lys-bg-2, #ffffff)",
        borderRadius: 10,
        boxShadow: "0 6px 18px rgba(15,23,42,0.10), 0 1px 3px rgba(15,23,42,0.06)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        pointerEvents: "auto",
        // Borderless — match chat-window design language
      }}
      onMouseDown={(e) => {
        // Focus on any click inside
        e.stopPropagation();
        p.onFocus?.();
      }}
    >
      {/* Title bar — drag handle */}
      <div
        onMouseDown={startDrag}
        style={{
          height: 28,
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "0 8px",
          background: "var(--lys-bg, #fafafa)",
          borderBottom: minimized ? 0 : "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
          cursor: dragging ? "grabbing" : "grab",
          userSelect: "none",
          fontSize: 10.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}
      >
        <Move size={10} style={{ color: p.tone ?? "var(--lys-text-faint)", flexShrink: 0 }} />
        <span style={{
          flex: 1,
          minWidth: 0,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}>
          {p.title}
        </span>
        <button
          type="button"
          title={minimized ? "Restore" : "Minimize"}
          onClick={(e) => {
            e.stopPropagation();
            p.onChange({ ...p.layout, minimized: !minimized });
          }}
          style={ghostBtn}
        >
          {minimized ? <Maximize2 size={10} /> : <Minimize2 size={10} />}
        </button>
        {p.onClose && (
          <button
            type="button"
            title="Close"
            onClick={(e) => {
              e.stopPropagation();
              p.onClose!();
            }}
            style={ghostBtn}
          >
            <IconX size={11} />
          </button>
        )}
      </div>

      {/* Body */}
      {!minimized && (
        <div style={{
          flex: 1,
          minHeight: 0,
          overflow: "hidden",
          position: "relative",
        }}>
          {p.children}
        </div>
      )}

      {/* Resize handle (bottom-right corner) */}
      {!minimized && (
        <div
          onMouseDown={startResize}
          style={{
            position: "absolute",
            right: 0,
            bottom: 0,
            width: 14,
            height: 14,
            cursor: "nwse-resize",
            background:
              "linear-gradient(135deg, transparent 50%, rgba(0,0,0,0.18) 50%, rgba(0,0,0,0.18) 60%, transparent 60%, transparent 75%, rgba(0,0,0,0.18) 75%, rgba(0,0,0,0.18) 85%, transparent 85%)",
          }}
        />
      )}
    </div>
  );
}

const ghostBtn: React.CSSProperties = {
  border: 0,
  background: "transparent",
  cursor: "pointer",
  padding: "2px 4px",
  borderRadius: 3,
  color: "var(--lys-text-faint)",
  display: "grid",
  placeItems: "center",
};

function snap(v: number): number {
  return Math.round(v / SNAP) * SNAP;
}
