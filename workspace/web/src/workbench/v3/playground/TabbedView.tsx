/**
 * TabbedView — Claude-style one-container-at-a-time mode.
 *
 * Same data + same cards as PlaygroundCanvas, just laid out in a tabbed
 * UI: 5 tabs across the top (Chemistry / Knowledge / Scoring / Agents /
 * Report), one tab visible at a time, cards inside arranged in a
 * responsive 2-column grid based on each card's `size` prop.
 *
 * The user can toggle between this and the whiteboard via a button in
 * the top header. Both modes render the SAME WindowGroup[] config —
 * no data duplication, just two ways of arranging it.
 *
 * Why this exists: the whiteboard is great for power-users who arrange
 * their own workspace, but for first-time visits and demos a tabbed UI
 * is faster to read. Both modes useful, both shipped.
 */
import { useState } from "react";
import type { WindowCategory } from "./PlaygroundCanvas";
import { CATEGORY_COLOR } from "./PlaygroundCanvas";
import {
  Beaker, Target, Brain, BookOpen, Activity, Library as LibraryIcon, FileText,
} from "lucide-react";

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
}

const ICONS: Record<WindowCategory, any> = {
  Chemistry: Beaker,
  Scoring:   Target,
  Agents:    Brain,
  Knowledge: BookOpen,
  Library:   LibraryIcon,
  Live:      Activity,
  Report:    FileText,
};

export function TabbedView({ groups }: Props) {
  const visible = groups.filter((g) => g.cards.length > 0);
  const [activeId, setActiveId] = useState<string>(visible[0]?.id ?? "");
  const active = visible.find((g) => g.id === activeId) ?? visible[0];

  return (
    <div style={{
      width: "100%", height: "100%",
      display: "flex", flexDirection: "column",
      background: "var(--lys-bg, #fafafa)",
      overflow: "hidden",
      fontFamily: "var(--lys-font-body)",
    }}>
      {/* Tab strip */}
      <div role="tablist" style={{
        display: "flex", alignItems: "stretch",
        background: "var(--lys-bg-2, #ffffff)",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
        flexShrink: 0,
        overflowX: "auto",
      }}>
        {visible.map((g) => {
          const isActive = g.id === active?.id;
          const c = CATEGORY_COLOR[g.category] ?? "#6b7280";
          const Icon = ICONS[g.category] ?? Beaker;
          return (
            <button
              key={g.id}
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveId(g.id)}
              type="button"
              style={{
                position: "relative",
                padding: "10px 16px",
                background: "transparent",
                border: 0,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 7,
                fontFamily: "var(--lys-font-mono)",
                fontSize: 11,
                fontWeight: isActive ? 700 : 500,
                color: isActive ? c : "var(--lys-text-faint)",
                letterSpacing: "0.04em",
                textTransform: "uppercase",
                transition: "color 100ms",
                whiteSpace: "nowrap",
              }}
              onMouseOver={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.color = c; }}
              onMouseOut={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.color = "var(--lys-text-faint)"; }}
            >
              <Icon size={13} />
              <span>{g.category}</span>
              {/* Active underline */}
              {isActive && (
                <span style={{
                  position: "absolute", left: 0, right: 0, bottom: -1, height: 2,
                  background: c,
                }} />
              )}
            </button>
          );
        })}
      </div>

      {/* Active tab body */}
      <div style={{
        flex: 1, overflow: "auto", padding: 16,
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
            accent={CATEGORY_COLOR[active.category] ?? "#6b7280"}
          />
        )}
      </div>
    </div>
  );
}

function CardsGrid({ cards, accent }: { cards: CardSpec[]; accent: string }) {
  return (
    <div style={{
      display: "grid",
      // 2-column responsive grid; cards with size:2 span full width
      gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))",
      gap: 12,
      maxWidth: 1600,
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
              borderRadius: 8,
              boxShadow: "0 1px 3px rgba(15,23,42,0.05)",
              display: "flex",
              flexDirection: "column",
              minHeight: Math.min(minH, 720),
              overflow: "hidden",
            }}
          >
            {/* Card header — title + colored accent dot */}
            <header style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "8px 12px",
              borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
              background: "var(--lys-bg, #fafafa)",
              flexShrink: 0,
            }}>
              <span style={{
                width: 6, height: 6, borderRadius: 6,
                background: accent, flexShrink: 0,
              }} />
              <span style={{
                fontSize: 10.5, fontFamily: "var(--lys-font-mono)",
                fontWeight: 700, color: "var(--lys-text-dim)",
                letterSpacing: "0.04em", textTransform: "uppercase",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {c.title || c.id}
              </span>
            </header>
            {/* Card body — same React components used in whiteboard mode */}
            <div className="lys-card-body" style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
              {c.body}
            </div>
          </section>
        );
      })}
    </div>
  );
}
