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
import { PlaygroundGroup, type GroupLayout, type CardSpec } from "./PlaygroundGroup";

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

export type WindowCategory = "Chemistry" | "Scoring" | "Agents" | "Knowledge" | "Library" | "Live" | "Report";

export interface WindowSpec {
  title: string;
  body: ReactNode;
  /** Category label shown next to the title; drives the color accent. */
  category?: WindowCategory;
  /** Optional explicit color override (otherwise derived from category). */
  tone?: string;
}

export interface GroupSpec {
  id: string;
  category: WindowCategory;
  cards: CardSpec[];
}

interface PlaygroundCanvasProps {
  // Legacy single-window layout (kept for backward compat — empty in groups mode)
  layout?: Record<string, WindowLayout>;
  windows?: Record<string, WindowSpec>;
  onLayoutChange?: (id: string, next: WindowLayout) => void;

  viewport: Viewport;
  onViewportChange: (v: Viewport) => void;
  onClose?: (id: string) => void;
  onFocus?: (id: string) => void;
  toolbar?: ReactNode;

  // NEW: groups model — preferred. If set, the canvas renders groups
  // (not free-floating windows). Each group holds multiple cards.
  groupLayout?: Record<string, GroupLayout>;
  groups?: GroupSpec[];
  onGroupLayoutChange?: (id: string, next: GroupLayout) => void;
}

// Category → accent color. The canvas uses this for the title-bar dot
// and the category pill, giving each surface a clear group identity.
export const CATEGORY_COLOR: Record<WindowCategory, string> = {
  Chemistry: "#10b981",   // emerald
  Scoring:   "#d97706",   // amber
  Agents:    "#8b5cf6",   // violet
  Knowledge: "#3b82f6",   // blue
  Library:   "#64748b",   // slate
  Live:      "#dc2626",   // red — system / DB / events
  Report:    "#0891b2",   // cyan — deliverable / export
};

const MIN_ZOOM = 0.3;
const MAX_ZOOM = 2.5;
const SNAP = 8; // 8px grid

export function PlaygroundCanvas(p: PlaygroundCanvasProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [panning, setPanning] = useState(false);
  // panMouseStartRef declared lower; legacy panStart removed.

  // Extreme-smooth wheel handling. The lag was from React reconciliation
  // on every viewport change. New strategy:
  //   1. Track viewport in a ref (live, mutated directly)
  //   2. Apply transform via DOM-mutation in a RAF loop (no React rerender
  //      while the user is scrubbing the wheel)
  //   3. Flush to React state only when wheel quiets for 80ms
  //
  // Result: pan/zoom feels like a native canvas — 60fps on any input rate.
  const liveViewportRef = useRef<Viewport>(p.viewport);
  const transformLayerRef = useRef<HTMLDivElement | null>(null);
  const wheelDeltaRef = useRef<{ x: number; y: number; zoomFactor: number; cx: number; cy: number } | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const flushTimerRef = useRef<number | null>(null);

  // Sync the ref when prop changes (e.g. cmd-0 reset, layout swap)
  useEffect(() => {
    liveViewportRef.current = p.viewport;
    applyTransform();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.viewport.zoom, p.viewport.pan.x, p.viewport.pan.y]);

  function applyTransform() {
    const el = transformLayerRef.current;
    if (!el) return;
    const v = liveViewportRef.current;
    el.style.transform = `translate3d(${v.pan.x}px, ${v.pan.y}px, 0) scale(${v.zoom})`;
    // Keep the dot-grid background synced with the pan/zoom too,
    // otherwise the cards drift while the grid stays put.
    const stage = stageRef.current;
    if (stage) {
      stage.style.backgroundSize = `${24 * v.zoom}px ${24 * v.zoom}px`;
      stage.style.backgroundPosition = `${v.pan.x}px ${v.pan.y}px`;
    }
  }

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;

    const flush = () => {
      rafIdRef.current = null;
      const acc = wheelDeltaRef.current;
      if (!acc) return;
      wheelDeltaRef.current = null;
      const v = liveViewportRef.current;
      if (acc.zoomFactor !== 1) {
        const next = clamp(v.zoom * acc.zoomFactor, MIN_ZOOM, MAX_ZOOM);
        const k = next / v.zoom;
        liveViewportRef.current = {
          zoom: next,
          pan: {
            x: acc.cx - (acc.cx - v.pan.x) * k,
            y: acc.cy - (acc.cy - v.pan.y) * k,
          },
        };
      } else if (acc.x !== 0 || acc.y !== 0) {
        liveViewportRef.current = {
          ...v,
          pan: { x: v.pan.x - acc.x, y: v.pan.y - acc.y },
        };
      }
      applyTransform();
      // Schedule a React-state flush after the user stops scrolling.
      // 40ms feels almost instantaneous to the user but still coalesces
      // rapid wheel ticks into one re-render.
      if (flushTimerRef.current != null) window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = window.setTimeout(() => {
        p.onViewportChange(liveViewportRef.current);
      }, 40);
    };

    const onWheel = (e: WheelEvent) => {
      // If the wheel happens INSIDE a card body (or any scrollable element
      // inside it), let the browser handle native scroll — don't hijack it
      // for canvas pan/zoom. Cmd/Ctrl+wheel always zooms the canvas though.
      if (!(e.metaKey || e.ctrlKey)) {
        let node = e.target as HTMLElement | null;
        while (node && node !== el) {
          if (node.classList && node.classList.contains("lys-card-body")) {
            // Wheel landed on a card body subtree — check if any ancestor
            // up to this card body has a scrollable overflow that needs
            // this scroll. If so, let native scroll proceed.
            return;  // do NOT preventDefault, do NOT pan canvas
          }
          // Also early-out if any ancestor is scrollable (catches inner
          // overflow:auto containers like ScaffoldPickerCard's list).
          const cs = getComputedStyle(node);
          const oy = cs.overflowY;
          if ((oy === "auto" || oy === "scroll") &&
              node.scrollHeight > node.clientHeight) {
            return;
          }
          node = node.parentElement;
        }
      }
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const acc = wheelDeltaRef.current ?? { x: 0, y: 0, zoomFactor: 1, cx, cy };
      acc.cx = cx; acc.cy = cy;
      if (e.metaKey || e.ctrlKey) {
        // Exponential zoom: factor = exp(-deltaY * 0.0007)
        // For a typical wheel click (deltaY≈33) this gives ~2.3% per click
        // — 2× finer than the old 5% and FEELS continuous, not stepped.
        // Trackpad pinch sends fine deltaY (~1-2) → ~0.07-0.14% per event,
        // so pinch zoom is silky-smooth at unit-level granularity.
        acc.zoomFactor *= Math.exp(-e.deltaY * 0.0007);
      } else {
        acc.x += e.deltaX;
        acc.y += e.deltaY;
      }
      wheelDeltaRef.current = acc;
      if (rafIdRef.current == null) {
        rafIdRef.current = requestAnimationFrame(flush);
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      el.removeEventListener("wheel", onWheel);
      if (rafIdRef.current != null) cancelAnimationFrame(rafIdRef.current);
      if (flushTimerRef.current != null) window.clearTimeout(flushTimerRef.current);
    };
  }, [p.onViewportChange]);

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "0") {
        e.preventDefault();
        p.onViewportChange({ pan: { x: 0, y: 0 }, zoom: 1 });
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "1") {
        e.preventDefault();
        // Fit-to-content: union of visible windows + groups bounding boxes
        const wins = p.layout ? Object.values(p.layout).filter((l) => l.visible) : [];
        const grps = p.groupLayout ? Object.values(p.groupLayout) : [];
        const all: Array<{ x: number; y: number; w: number; h: number }> = [...wins, ...grps];
        if (!all.length) return;
        const minX = Math.min(...all.map((l) => l.x));
        const minY = Math.min(...all.map((l) => l.y));
        const maxX = Math.max(...all.map((l) => l.x + l.w));
        const maxY = Math.max(...all.map((l) => l.y + l.h));
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

  // Pan — RAF+ref pattern matching wheel handler. The OLD path called
  // p.onViewportChange() on every mousemove, forcing a full React tree
  // re-render of every group + card on every pixel of drag → ~10fps when
  // many cards are open. New path: mutate liveViewportRef + DOM transform
  // directly during drag, only flush to React state on mouseup. 60fps
  // regardless of card count.
  //
  // Pan triggers:
  //   • Background mouse-down (click empty grid area)
  //   • Middle-mouse-button anywhere on canvas
  //   • Space + left-drag anywhere (Figma-style)
  const spaceDownRef = useRef(false);
  const panMouseStartRef = useRef<{ mx: number; my: number; pan: { x: number; y: number } } | null>(null);

  function startPan(e: React.MouseEvent | MouseEvent) {
    setPanning(true);
    panMouseStartRef.current = {
      mx: e.clientX,
      my: e.clientY,
      pan: { ...liveViewportRef.current.pan },
    };
  }

  function onBgMouseDown(e: React.MouseEvent) {
    // Only handle background empty-area click here. The middle-mouse +
    // space+drag triggers run via a document-level CAPTURE-phase listener
    // (see useEffect below) because cards inside the canvas call
    // stopPropagation on their drag handlers — bubble-phase listeners
    // would never see the event.
    if (e.target === stageRef.current || e.target === e.currentTarget) {
      if (e.button === 0) startPan(e);
    }
  }

  // Document-level capture-phase listener. Fires BEFORE any card's
  // mousedown, so we can intercept middle-mouse / space+left from
  // anywhere on the canvas — including over cards that stopPropagation.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const onCaptureDown = (e: MouseEvent) => {
      // Only intercept events that landed inside the canvas stage
      if (!stage.contains(e.target as Node)) return;
      // Skip if user is interacting with a form input
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" ||
                t.isContentEditable)) return;
      // Pan triggers:
      //   1. Middle-mouse-button (button 1) — always
      //   2. Spacebar held + left-button (button 0) — Figma-style
      const isMiddle = e.button === 1;
      const isSpaceDrag = e.button === 0 && spaceDownRef.current;
      if (!isMiddle && !isSpaceDrag) return;
      // Stop the event so cards don't ALSO start dragging themselves.
      e.stopPropagation();
      e.preventDefault();
      startPan(e);
    };
    document.addEventListener("mousedown", onCaptureDown, { capture: true });
    return () => {
      document.removeEventListener("mousedown", onCaptureDown, { capture: true } as any);
    };
  }, []);

  // Wire pan-active mouse handlers to window so dragging off-canvas keeps tracking
  useEffect(() => {
    if (!panning) return;
    const onMove = (e: MouseEvent) => {
      const start = panMouseStartRef.current;
      if (!start) return;
      const dx = e.clientX - start.mx;
      const dy = e.clientY - start.my;
      // Mutate the ref + DOM transform directly — NO React re-render
      const v = liveViewportRef.current;
      liveViewportRef.current = {
        ...v,
        pan: {
          x: start.pan.x + dx,
          y: start.pan.y + dy,
        },
      };
      applyTransform();
      // Also live-shift the background grid pattern position. We can do
      // this via inline CSS variable so the grid follows without
      // forcing a React re-render.
      const stage = stageRef.current;
      if (stage) {
        stage.style.backgroundPosition =
          `${liveViewportRef.current.pan.x}px ${liveViewportRef.current.pan.y}px`;
      }
    };
    const onUp = () => {
      setPanning(false);
      panMouseStartRef.current = null;
      // Flush final viewport to React state. ONLY happens once at end of
      // drag, not per-pixel.
      p.onViewportChange(liveViewportRef.current);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panning]);

  // Spacebar press = pan-mode override (cursor + drag-from-anywhere)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code === "Space" && !spaceDownRef.current) {
        // Don't capture space when typing in inputs
        const target = e.target as HTMLElement | null;
        if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" ||
                       target.isContentEditable)) return;
        spaceDownRef.current = true;
        const stage = stageRef.current;
        if (stage) stage.style.cursor = panning ? "grabbing" : "grab";
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space") {
        spaceDownRef.current = false;
        const stage = stageRef.current;
        if (stage) stage.style.cursor = panning ? "grabbing" : "default";
      }
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [panning]);

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
      {/* GPU-accelerated transform layer — translate3d + will-change.
          DOM-mutated directly during wheel/drag events for buttery-smooth
          pan/zoom; React state only updates after 80ms of input quiet (zoom)
          or on mouseup (drag). NO CSS transition — every continuous input
          frame would otherwise lag behind by transition-duration. cmd+0/
          cmd+1 jumps; user gets a clean reset rather than a laggy animate. */}
      <div
        ref={transformLayerRef}
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          transform: `translate3d(${p.viewport.pan.x}px, ${p.viewport.pan.y}px, 0) scale(${p.viewport.zoom})`,
          transformOrigin: "0 0",
          willChange: "transform",
          width: "100%",
          height: "100%",
          pointerEvents: "none",
        }}
      >
        {/* Groups mode (preferred): each group is a colored container with cards inside. */}
        {p.groups && p.groupLayout && p.onGroupLayoutChange && p.groups.map((g) => {
          const layout = p.groupLayout![g.id];
          if (!layout) return null;
          return (
            <PlaygroundGroup
              key={g.id}
              id={g.id}
              category={g.category}
              cards={g.cards}
              layout={layout}
              viewport={p.viewport}
              onChange={(next) => p.onGroupLayoutChange!(g.id, next)}
              onFocus={p.onFocus ? () => p.onFocus!(g.id) : undefined}
            />
          );
        })}

        {/* Legacy free-floating windows mode — falls through if no groups */}
        {!p.groups && p.layout && p.windows && p.onLayoutChange && Object.entries(p.layout).map(([id, l]) => {
          if (!l.visible) return null;
          const win = p.windows![id];
          if (!win) return null;
          return (
            <PlaygroundWindow
              key={id}
              id={id}
              layout={l}
              viewport={p.viewport}
              title={win.title}
              category={win.category}
              tone={win.tone ?? (win.category ? CATEGORY_COLOR[win.category] : undefined)}
              onChange={(next) => p.onLayoutChange!(id, next)}
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
  category?: WindowCategory;
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
      {/* Title bar — drag handle. Left edge is a 3px tone bar that reads
          as a category color stripe (chemistry green / scoring amber /
          agents violet / knowledge blue / library slate). */}
      <div
        onMouseDown={startDrag}
        style={{
          height: 30,
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
          position: "relative",
        }}
      >
        {/* Tone stripe along the very left edge of the title bar */}
        <span style={{
          position: "absolute",
          left: 0, top: 0, bottom: 0,
          width: 3,
          background: p.tone ?? "var(--lys-text-faint)",
        }} />
        <Move size={10} style={{ color: p.tone ?? "var(--lys-text-faint)", flexShrink: 0, marginLeft: 4 }} />
        {p.category && (
          <span style={{
            fontSize: 8.5,
            fontWeight: 700,
            padding: "1px 6px",
            borderRadius: 3,
            background: `${p.tone}18`,
            color: p.tone,
            letterSpacing: "0.08em",
            flexShrink: 0,
          }}>
            {p.category}
          </span>
        )}
        <span style={{
          flex: 1,
          minWidth: 0,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          color: "var(--lys-text-dim)",
          textTransform: "none",
          letterSpacing: 0,
          fontFamily: "var(--lys-font-body)",
          fontSize: 11,
          fontWeight: 500,
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
