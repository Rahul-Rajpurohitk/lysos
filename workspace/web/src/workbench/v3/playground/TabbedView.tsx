/**
 * TabbedView — Claude-style one-container-at-a-time mode.
 *
 * Same data + same cards as PlaygroundCanvas, just laid out in a tabbed
 * UI: subtle horizontal tab strip across the top, one tab visible at a
 * time, cards inside arranged in a responsive grid based on each card's
 * `size` prop.
 *
 * Design: minimal Claude-style — no boxy borders, no bulky uppercase
 * labels, no per-tab icons that clutter the strip. Just clean text +
 * subtle 2px accent underline on the active tab + a light hover bg.
 */
import { useState } from "react";
import type { WindowCategory } from "./PlaygroundCanvas";
import { CATEGORY_COLOR } from "./PlaygroundCanvas";

interface CardSpec {
  id: string;
  title: string;
  body: React.ReactNode;
  size?: 1 | 2;
  slot?: "nav" | "topnav";
  expandedH?: number;
}

interface WindowGroup {
  id: string;
  category: WindowCategory;
  cards: CardSpec[];
}

interface Props {
  groups: WindowGroup[];
  /** Optional actions slot rendered at left edge of tab strip. */
  actions?: React.ReactNode;
}

export function TabbedView({ groups, actions }: Props) {
  const visible = groups.filter((g) => g.cards.length > 0);
  const [activeId, setActiveId] = useState<string>(visible[0]?.id ?? "");
  const [hoverId, setHoverId] = useState<string | null>(null);
  const active = visible.find((g) => g.id === activeId) ?? visible[0];

  return (
    <div style={{
      width: "100%", height: "100%",
      display: "flex", flexDirection: "column",
      background: "var(--lys-bg, #fafafa)",
      overflow: "hidden",
      fontFamily: "var(--lys-font-body)",
    }}>
      {/* Tab strip — clean, 36px tall, subtle separator below */}
      <div role="tablist" style={{
        display: "flex", alignItems: "stretch", height: 36,
        background: "var(--lys-bg-2, #ffffff)",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
        flexShrink: 0,
        overflowX: "auto",
        overflowY: "hidden",
      }}>
        {actions && (
          <div style={{
            display: "flex", alignItems: "center",
            padding: "0 10px",
            flexShrink: 0,
          }}>
            {actions}
          </div>
        )}
        {visible.map((g) => {
          const isActive = g.id === active?.id;
          const isHover = g.id === hoverId;
          const c = CATEGORY_COLOR[g.category] ?? "#6b7280";
          return (
            <button
              key={g.id}
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveId(g.id)}
              onMouseEnter={() => setHoverId(g.id)}
              onMouseLeave={() => setHoverId(null)}
              type="button"
              style={{
                position: "relative",
                padding: "0 16px",
                background: isActive
                  ? "var(--lys-bg, #fafafa)"
                  : isHover
                    ? "rgba(0,0,0,0.025)"
                    : "transparent",
                border: 0,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                fontFamily: "var(--lys-font-body)",
                fontSize: 12,
                fontWeight: isActive ? 600 : 500,
                color: isActive
                  ? "var(--lys-text, #0f172a)"
                  : "var(--lys-text-faint, #94a3b8)",
                letterSpacing: 0,
                textTransform: "none",
                transition: "color 120ms, background 120ms",
                whiteSpace: "nowrap",
              }}
            >
              {g.category}
              {isActive && (
                <span style={{
                  position: "absolute", left: 8, right: 8, bottom: -1, height: 2,
                  background: c, borderRadius: 1,
                }} />
              )}
            </button>
          );
        })}
        <div style={{ flex: 1 }} />
      </div>

      {/* Active tab body */}
      <div style={{
        flex: 1, overflow: "auto", padding: 14,
        background: "var(--lys-bg, #fafafa)",
      }}>
        {!active && (
          <div style={{ padding: 32, textAlign: "center", color: "var(--lys-text-faint)" }}>
            no tabs available
          </div>
        )}
        {active && (
          <CardsGrid
            cards={active.cards.filter((c) => c.slot !== "nav" && c.slot !== "topnav")}
          />
        )}
      </div>
    </div>
  );
}

function CardsGrid({ cards }: { cards: CardSpec[] }) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(440px, 1fr))",
      gap: 12,
      maxWidth: 1700,
      margin: "0 auto",
    }}>
      {cards.map((c) => {
        const span = c.size === 2 ? "1 / -1" : "auto";
        const minH = c.expandedH ?? 360;
        return (
          <section
            key={c.id}
            style={{
              gridColumn: span,
              background: "var(--lys-bg-2, #ffffff)",
              border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
              borderRadius: 6,
              display: "flex",
              flexDirection: "column",
              minHeight: Math.min(minH, 720),
              overflow: "hidden",
            }}
          >
            {/* Card header — minimal, just title text */}
            <header style={{
              display: "flex", alignItems: "center",
              padding: "8px 12px",
              borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
              flexShrink: 0,
            }}>
              <span style={{
                fontSize: 11.5, fontFamily: "var(--lys-font-body)",
                fontWeight: 600, color: "var(--lys-text, #0f172a)",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {c.title || c.id}
              </span>
            </header>
            <div className="lys-card-body" style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
              {c.body}
            </div>
          </section>
        );
      })}
    </div>
  );
}
