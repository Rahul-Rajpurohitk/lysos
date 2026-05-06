/**
 * PlaygroundGroup — a category container that holds multiple cards.
 *
 * Each group has its own color identity (Chemistry emerald, Scoring amber,
 * Agents violet, Knowledge blue, Library slate). The group is a colored
 * box on the canvas with a header bar (icon + label + card count) and a
 * 2-column flex layout inside for its child cards. The whole group is
 * draggable + resizable as one unit; cards inside it are simple rectangles
 * (no individual drag) — the group is the unit of arrangement.
 *
 * Cards inside expose a tone via the group's color so all cards in a group
 * share visual identity.
 */
import { useEffect, useRef, useState, ReactNode } from "react";
import { Move, Minimize2, Maximize2, Beaker, Target, Brain, BookOpen, Library as LibraryIcon, ChevronDown, Activity } from "lucide-react";

import type { WindowCategory, Viewport } from "./PlaygroundCanvas";

export interface GroupLayout {
  x: number;
  y: number;
  w: number;
  h: number;
  z: number;
  collapsed?: boolean;
}

export interface CardSpec {
  id: string;
  title: string;
  body: ReactNode;
  /** Card width in flex-grid units (1 = half, 2 = full).
   *  Default = 1. Cards with size 2 take a full row. */
  size?: 1 | 2;
}

interface Props {
  id: string;
  category: WindowCategory;
  cards: CardSpec[];
  layout: GroupLayout;
  viewport: Viewport;
  onChange: (next: GroupLayout) => void;
  onFocus?: () => void;
}

const ICONS: Record<WindowCategory, any> = {
  Chemistry: Beaker,
  Scoring:   Target,
  Agents:    Brain,
  Knowledge: BookOpen,
  Library:   LibraryIcon,
  Live:      Activity,
};

const COLORS: Record<WindowCategory, string> = {
  Chemistry: "#10b981",
  Scoring:   "#d97706",
  Agents:    "#8b5cf6",
  Knowledge: "#3b82f6",
  Library:   "#64748b",
  Live:      "#dc2626",
};

const SNAP = 8;
function snap(v: number): number { return Math.round(v / SNAP) * SNAP; }

export function PlaygroundGroup(p: Props) {
  const Icon = ICONS[p.category];
  const tone = COLORS[p.category];
  const [dragging, setDragging] = useState(false);
  const [resizing, setResizing] = useState(false);
  // Per-card collapse state — toggled by clicking the chevron in the card header
  const [collapsedCards, setCollapsedCards] = useState<Set<string>>(new Set());
  const toggleCardCollapsed = (id: string) => {
    setCollapsedCards((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const start = useRef<{ mx: number; my: number; layout: GroupLayout } | null>(null);

  function startDrag(e: React.MouseEvent) {
    e.stopPropagation();
    setDragging(true);
    start.current = { mx: e.clientX, my: e.clientY, layout: { ...p.layout } };
    p.onFocus?.();
  }
  function startResize(e: React.MouseEvent) {
    e.stopPropagation();
    setResizing(true);
    start.current = { mx: e.clientX, my: e.clientY, layout: { ...p.layout } };
    p.onFocus?.();
  }
  useEffect(() => {
    if (!dragging && !resizing) return;
    const onMove = (e: MouseEvent) => {
      if (!start.current) return;
      const dx = (e.clientX - start.current.mx) / p.viewport.zoom;
      const dy = (e.clientY - start.current.my) / p.viewport.zoom;
      if (dragging) {
        p.onChange({
          ...start.current.layout,
          x: snap(start.current.layout.x + dx),
          y: snap(start.current.layout.y + dy),
        });
      } else if (resizing) {
        p.onChange({
          ...start.current.layout,
          w: Math.max(280, snap(start.current.layout.w + dx)),
          h: Math.max(180, snap(start.current.layout.h + dy)),
        });
      }
    };
    const onUp = () => { setDragging(false); setResizing(false); start.current = null; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, resizing, p.viewport.zoom, p.onChange]);

  const collapsed = !!p.layout.collapsed;
  const HEADER_H = 30;

  return (
    <div style={{
      position: "absolute",
      left: p.layout.x,
      top: p.layout.y,
      width: p.layout.w,
      height: collapsed ? HEADER_H : p.layout.h,
      zIndex: p.layout.z,
      background: `${tone}08`,
      border: `1px solid ${tone}22`,
      borderRadius: 12,
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
      pointerEvents: "auto",
      boxShadow: dragging
        ? "0 18px 36px rgba(15,23,42,0.18), 0 4px 8px rgba(15,23,42,0.08)"
        : "0 6px 18px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04)",
      // Force a fresh stacking context so internal cards/popovers cannot
      // escape the group's z bracket and bleed into other overlapping groups.
      isolation: "isolate",
      contain: "layout paint",
      transform: dragging ? "scale(1.005)" : "none",
      transition: dragging ? "transform 80ms ease, box-shadow 80ms ease" : "transform 120ms ease, box-shadow 120ms ease",
    }}
    onMouseDown={(e) => { e.stopPropagation(); p.onFocus?.(); }}
    >
      {/* Group header bar — drag handle + tone stripe along the left */}
      <div
        onMouseDown={startDrag}
        style={{
          height: HEADER_H,
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "0 10px",
          background: `${tone}18`,
          borderBottom: collapsed ? 0 : `1px solid ${tone}22`,
          cursor: dragging ? "grabbing" : "grab",
          userSelect: "none",
          fontSize: 11,
          color: tone,
          position: "relative",
          fontFamily: "var(--lys-font-mono)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          fontWeight: 700,
        }}
      >
        <span style={{
          position: "absolute", left: 0, top: 0, bottom: 0, width: 4, background: tone,
        }} />
        <Move size={11} style={{ color: tone, opacity: 0.6, marginLeft: 6, flexShrink: 0 }} />
        <Icon size={13} style={{ color: tone, flexShrink: 0 }} />
        <span style={{ flexShrink: 0 }}>{p.category}</span>
        <span style={{ color: `${tone}88`, fontWeight: 500, fontSize: 9.5 }}>
          · {p.cards.length} {p.cards.length === 1 ? "card" : "cards"}
        </span>
        <span style={{ flex: 1 }} />
        <button
          type="button"
          title={collapsed ? "Expand" : "Collapse"}
          onClick={(e) => {
            e.stopPropagation();
            p.onChange({ ...p.layout, collapsed: !collapsed });
          }}
          style={{
            border: 0, background: "transparent", cursor: "pointer",
            padding: 2, color: tone, display: "grid", placeItems: "center",
          }}
        >
          {collapsed ? <Maximize2 size={11} /> : <Minimize2 size={11} />}
        </button>
      </div>

      {/* Cards container — 2-col flex grid */}
      {!collapsed && (
        <div style={{
          flex: 1,
          minHeight: 0,
          padding: 8,
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 8,
          overflow: "auto",
        }}>
          {p.cards.map((c) => {
            const cardCollapsed = collapsedCards.has(c.id);
            return (
              <div
                key={c.id}
                style={{
                  gridColumn: c.size === 2 ? "1 / -1" : "auto",
                  background: "var(--lys-bg-2, #ffffff)",
                  borderRadius: 8,
                  border: `1px solid ${tone}1a`,
                  overflow: "hidden",
                  display: "flex",
                  flexDirection: "column",
                  minHeight: cardCollapsed ? 28 : 240,
                  maxHeight: cardCollapsed ? 28 : 480,
                  height: cardCollapsed ? 28 : "auto",
                  isolation: "isolate",
                  transition: "min-height 140ms ease, max-height 140ms ease",
                }}
              >
                {/* Card header — clickable to toggle collapse */}
                <div
                  onClick={(e) => { e.stopPropagation(); toggleCardCollapsed(c.id); }}
                  title={cardCollapsed ? "Expand card" : "Collapse card"}
                  style={{
                    padding: "5px 10px",
                    fontSize: 10,
                    fontFamily: "var(--lys-font-mono)",
                    color: tone,
                    letterSpacing: "0.04em",
                    background: `${tone}06`,
                    borderBottom: cardCollapsed ? 0 : `1px solid ${tone}1a`,
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                    fontWeight: 600,
                    cursor: "pointer",
                    userSelect: "none",
                    flexShrink: 0,
                  }}
                  onMouseOver={(e) => { (e.currentTarget as HTMLElement).style.background = `${tone}12`; }}
                  onMouseOut={(e) => { (e.currentTarget as HTMLElement).style.background = `${tone}06`; }}
                >
                  <ChevronDown
                    size={10}
                    style={{
                      transform: cardCollapsed ? "rotate(-90deg)" : "rotate(0deg)",
                      transition: "transform 120ms ease",
                      flexShrink: 0,
                    }}
                  />
                  <span style={{
                    flex: 1, color: "var(--lys-text)",
                    textTransform: "none", letterSpacing: 0,
                    fontFamily: "var(--lys-font-body)", fontWeight: 500,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>
                    {c.title}
                  </span>
                </div>
                {/* Body — inner card components manage their own internal scroll
                    via flex:1 + overflow:auto on their list/content area. We
                    keep overflow:hidden here so we don't double-scroll. */}
                {!cardCollapsed && (
                  <div style={{
                    flex: 1, minHeight: 0,
                    overflow: "hidden",
                    position: "relative",
                    display: "flex",
                    flexDirection: "column",
                  }}>
                    {c.body}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Resize corner */}
      {!collapsed && (
        <div
          onMouseDown={startResize}
          style={{
            position: "absolute",
            right: 0, bottom: 0,
            width: 14, height: 14,
            cursor: "nwse-resize",
            background:
              "linear-gradient(135deg, transparent 50%, rgba(0,0,0,0.16) 50%, rgba(0,0,0,0.16) 60%, transparent 60%, transparent 75%, rgba(0,0,0,0.16) 75%, rgba(0,0,0,0.16) 85%, transparent 85%)",
          }}
        />
      )}
    </div>
  );
}
