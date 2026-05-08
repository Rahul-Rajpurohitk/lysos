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

      {/* Active tab body — vertical scroll, sub-containers stack full-width */}
      <div style={{
        flex: 1, overflowY: "auto", overflowX: "hidden",
        padding: "0 28px 32px",
        background: "var(--lys-bg, #fafafa)",
      }}>
        {!active && (
          <div style={{ padding: 32, textAlign: "center", color: "var(--lys-text-faint)" }}>
            no tabs available
          </div>
        )}
        {active && (
          <CardsStack
            cards={active.cards.filter((c) => c.slot !== "nav" && c.slot !== "topnav")}
          />
        )}
      </div>
    </div>
  );
}

/**
 * CardsStack — borderless vertical flow.
 *
 * Each sub-container is its own full-width section, no card chrome (no
 * border, no rounded corners, no shadow). Just a small header strip +
 * content. Sub-containers are sized to fit their natural content (no
 * clipping). Bulky business sub-containers like the 3D theater respect
 * their `expandedH` so the user can see them at-a-glance, then scrolls
 * down to reach the next sub-container.
 *
 * For pairs of compact (size:1) cards we drop into a 2-column grid so
 * they share a row instead of stacking awkwardly.
 */
function CardsStack({ cards }: { cards: CardSpec[] }) {
  // Walk cards and group consecutive size:1 into 2-col rows.
  const rows: Array<{ kind: "single" | "pair"; cards: CardSpec[] }> = [];
  let i = 0;
  while (i < cards.length) {
    const c = cards[i];
    if (c.size !== 2) {
      const next = cards[i + 1];
      if (next && next.size !== 2) {
        rows.push({ kind: "pair", cards: [c, next] });
        i += 2;
        continue;
      }
    }
    rows.push({ kind: "single", cards: [c] });
    i += 1;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24, paddingTop: 20 }}>
      {rows.map((row, idx) => (
        <div
          key={idx}
          style={row.kind === "pair" ? {
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 24,
          } : undefined}
        >
          {row.cards.map((c) => <CardSection key={c.id} card={c} />)}
        </div>
      ))}
    </div>
  );
}

function CardSection({ card }: { card: CardSpec }) {
  // Heuristic: bulky containers (3D theater, builder, scoring radar)
  // have expandedH ≥ 480. Use that as their natural height so they're
  // visible at a glance. Smaller cards size to content.
  const naturalH = card.expandedH ?? 320;
  const isBulky = naturalH >= 460;
  return (
    <section
      style={{
        background: "transparent",
        // Borderless — no box around the section. Just header + content.
        // The hairline below the header gives visual rhythm without a
        // boxy frame around every panel.
        display: "flex",
        flexDirection: "column",
        height: isBulky ? naturalH : "auto",
        minHeight: isBulky ? 360 : undefined,
        // overflow visible so child diagrams can render without clipping
        // their own internal toolbars/legends.
        overflow: "visible",
      }}
    >
      <header style={{
        display: "flex", alignItems: "center",
        paddingBottom: 8,
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
        marginBottom: 10,
        flexShrink: 0,
      }}>
        <span style={{
          fontSize: 12.5, fontFamily: "var(--lys-font-body)",
          fontWeight: 600, color: "var(--lys-text, #0f172a)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          {card.title || card.id}
        </span>
      </header>
      <div
        className="lys-card-body lys-tab-card-body"
        style={{
          flex: isBulky ? 1 : undefined,
          minHeight: 0,
          // Bulky panels manage their own internal scroll. Compact ones
          // grow naturally.
          overflow: isBulky ? "hidden" : "visible",
        }}
      >
        {card.body}
      </div>
    </section>
  );
}
