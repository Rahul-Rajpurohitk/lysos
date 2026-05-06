/**
 * ScaffoldPickerCard — compact dropdown launcher.
 *
 * The card body itself is a small "Pick a scaffold ▾" trigger button
 * plus 4 quick-pick chips for the most common starting points (Benzene,
 * β-Lactam, Imidazole, Pyridine).
 *
 * Clicking the button opens a portal-rendered popover containing:
 *   - Search input (filters live as user types)
 *   - Category chip filters (ring · antibiotic · drug · scratch)
 *   - Scrollable 2-col grid of all 21 scaffolds
 *
 * The popover is positioned underneath the trigger button via
 * getBoundingClientRect, anchored to escape the card's overflow:hidden.
 * Click outside or Esc → closes.
 *
 * Selecting a scaffold → onLoadSmiles → closes popover.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Search, Sparkles, ChevronDown, X } from "lucide-react";

interface Scaffold {
  id: string;
  name: string;
  category: string;
  smiles: string;
  tag: string;
}

interface Props {
  apiBase: string;
  onLoadSmiles?: (smiles: string, name?: string) => void;
}

const CAT_COLOR: Record<string, string> = {
  ring:       "#3b82f6",
  antibiotic: "#10b981",
  drug:       "#f59e0b",
  scratch:    "#94a3b8",
};

// Quick-pick chip names — must exist in the scaffolds list (matched by name)
const QUICK_PICKS = ["Benzene", "β-Lactam (penam core)", "Imidazole", "Pyridine"];

export function ScaffoldPickerCard({ apiBase, onLoadSmiles }: Props) {
  const [scaffolds, setScaffolds] = useState<Scaffold[]>([]);
  const [query, setQuery] = useState("");
  const [activeCat, setActiveCat] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [popPos, setPopPos] = useState<{ left: number; top: number; width: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    fetch(`${apiBase}/workbench/playground/scaffolds`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => { setScaffolds(d.scaffolds ?? []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [apiBase]);

  // Recompute popover position whenever it opens or window resizes/scrolls
  useEffect(() => {
    if (!open) { setPopPos(null); return; }
    const update = () => {
      if (!triggerRef.current) return;
      const r = triggerRef.current.getBoundingClientRect();
      setPopPos({
        left: r.left,
        top: r.bottom + 4,
        width: Math.max(r.width, 360),
      });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open]);

  // Click-outside + Esc
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("[data-scaffold-pop]")) return;
      if (triggerRef.current && triggerRef.current.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    setTimeout(() => document.addEventListener("mousedown", onDoc), 0);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const filtered = useMemo(() => {
    let arr = scaffolds;
    if (activeCat) arr = arr.filter((s) => s.category === activeCat);
    if (query.trim()) {
      const q = query.toLowerCase();
      arr = arr.filter((s) =>
        s.name.toLowerCase().includes(q) ||
        s.tag.toLowerCase().includes(q) ||
        s.smiles.toLowerCase().includes(q) ||
        s.category.includes(q)
      );
    }
    return arr;
  }, [scaffolds, query, activeCat]);

  const distinctCats = useMemo(() => {
    const counts: Record<string, number> = {};
    scaffolds.forEach((s) => { counts[s.category] = (counts[s.category] ?? 0) + 1; });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [scaffolds]);

  function pick(s: Scaffold) {
    onLoadSmiles?.(s.smiles, s.name);
    setOpen(false);
  }

  const quickChips = QUICK_PICKS
    .map((qn) => scaffolds.find((s) => s.name === qn))
    .filter((s): s is Scaffold => !!s);

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
      padding: 8, gap: 6,
    }}>
      {/* Compact dropdown trigger */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 12px",
          borderRadius: 6,
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
          background: open ? "rgba(16,185,129,0.06)" : "var(--lys-bg, #fafafa)",
          color: "var(--lys-text)",
          cursor: "pointer",
          fontSize: 12,
          fontFamily: "inherit",
          transition: "background 120ms",
          flexShrink: 0,
        }}
        onMouseEnter={(e) => { if (!open) (e.currentTarget as HTMLElement).style.background = "rgba(16,185,129,0.05)"; }}
        onMouseLeave={(e) => { if (!open) (e.currentTarget as HTMLElement).style.background = "var(--lys-bg, #fafafa)"; }}
      >
        <Sparkles size={13} style={{ color: "#10b981", flexShrink: 0 }} />
        <span style={{ fontWeight: 600, color: "var(--lys-text)" }}>Pick a scaffold</span>
        <span style={{
          fontSize: 9.5, padding: "1px 6px", borderRadius: 999,
          background: "rgba(16,185,129,0.10)", color: "#10b981",
          fontFamily: "var(--lys-font-mono)", fontWeight: 700,
        }}>{scaffolds.length} starting points</span>
        <span style={{ flex: 1 }} />
        <ChevronDown size={13} style={{
          transform: open ? "rotate(180deg)" : "none",
          transition: "transform 120ms", color: "var(--lys-text-faint)",
        }} />
      </button>

      {/* Quick-pick row */}
      {quickChips.length > 0 && (
        <div style={{
          display: "flex", flexWrap: "wrap", gap: 4,
          fontSize: 10, fontFamily: "var(--lys-font-mono)",
        }}>
          <span style={{ fontSize: 9, color: "var(--lys-text-faint)",
            letterSpacing: "0.04em", textTransform: "uppercase",
            alignSelf: "center", marginRight: 2 }}>quick:</span>
          {quickChips.map((s) => {
            const c = CAT_COLOR[s.category] ?? "#94a3b8";
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => pick(s)}
                style={{
                  fontSize: 10, padding: "2px 8px", borderRadius: 999,
                  border: `1px solid ${c}30`,
                  background: `${c}10`, color: c,
                  fontFamily: "inherit", cursor: "pointer", fontWeight: 600,
                }}
              >{s.name.split(" ")[0].replace("(", "")}</button>
            );
          })}
        </div>
      )}

      {/* Status hint */}
      <div style={{
        fontSize: 9.5, color: "var(--lys-text-faint)",
        fontFamily: "var(--lys-font-mono)",
        marginTop: "auto",
      }}>
        {loading
          ? "loading scaffolds…"
          : `${scaffolds.length} curated · rings, antibiotic cores, FDA drugs`}
      </div>

      {/* Popover dropdown — rendered to body via portal so it escapes
          the card's overflow:hidden bracket */}
      {open && popPos && createPortal(
        <div
          data-scaffold-pop
          style={{
            position: "fixed",
            left: popPos.left,
            top: popPos.top,
            width: popPos.width,
            maxWidth: 520,
            maxHeight: "60vh",
            background: "var(--lys-bg-2, #ffffff)",
            border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
            borderRadius: 8,
            boxShadow: "0 12px 32px rgba(15,23,42,0.18), 0 2px 6px rgba(15,23,42,0.10)",
            zIndex: 5000,
            display: "flex", flexDirection: "column",
            overflow: "hidden",
          }}>
          {/* Header */}
          <div style={{
            padding: "6px 8px",
            borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
            display: "flex", flexDirection: "column", gap: 5,
            background: "var(--lys-bg, #fafafa)",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Search size={11} style={{ color: "var(--lys-text-faint)" }} />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="search scaffolds · name, tag, SMILES"
                style={{
                  flex: 1, fontSize: 11, fontFamily: "var(--lys-font-mono)",
                  padding: "3px 6px", borderRadius: 4,
                  border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
                  background: "var(--lys-bg-2, #ffffff)",
                  color: "var(--lys-text)", outline: "none",
                }} />
              <button type="button" onClick={() => setOpen(false)}
                style={{
                  border: 0, background: "transparent", cursor: "pointer",
                  padding: 2, color: "var(--lys-text-faint)",
                }}><X size={12} /></button>
            </div>
            {/* Category filters */}
            <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
              <button type="button" onClick={() => setActiveCat("")}
                style={catChip(!activeCat, "#10b981")}>all · {scaffolds.length}</button>
              {distinctCats.map(([cat, n]) => (
                <button key={cat} type="button"
                  onClick={() => setActiveCat(cat === activeCat ? "" : cat)}
                  style={catChip(cat === activeCat, CAT_COLOR[cat] ?? "#94a3b8")}>
                  {cat} · {n}
                </button>
              ))}
            </div>
          </div>
          {/* Result count */}
          <div style={{
            padding: "3px 8px", fontSize: 9,
            color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)",
            letterSpacing: "0.04em", textTransform: "uppercase",
          }}>
            {filtered.length} of {scaffolds.length}
          </div>
          {/* Scrollable list */}
          <div className="lys-card-body" style={{
            flex: 1, overflow: "auto", padding: "0 6px 6px 6px",
            display: "grid", gridTemplateColumns: "1fr 1fr", gap: 3,
          }}>
            {filtered.length === 0 && (
              <div style={{
                gridColumn: "1 / -1", textAlign: "center", padding: 12,
                fontSize: 10.5, color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-mono)",
              }}>no matches</div>
            )}
            {filtered.map((s) => {
              const color = CAT_COLOR[s.category] ?? "#94a3b8";
              return (
                <button
                  key={s.id} type="button"
                  onClick={() => pick(s)}
                  title={s.smiles}
                  style={{
                    border: 0,
                    background: "var(--lys-bg, #fafafa)",
                    borderLeft: `3px solid ${color}`,
                    padding: "4px 8px",
                    borderRadius: 4,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    textAlign: "left",
                    display: "flex", flexDirection: "column", gap: 1,
                    transition: "background 0.12s",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = `${color}12`)}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "var(--lys-bg, #fafafa)")}
                >
                  <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                    <span style={{
                      fontSize: 8, padding: "0 4px", borderRadius: 2,
                      background: `${color}18`, color, fontWeight: 700,
                      fontFamily: "var(--lys-font-mono)",
                      textTransform: "uppercase", letterSpacing: "0.05em",
                    }}>{s.category[0]}</span>
                    <span style={{
                      fontSize: 11, color: "var(--lys-text)", fontWeight: 600,
                      flex: 1, minWidth: 0,
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    }}>{s.name}</span>
                  </div>
                  <div style={{
                    fontSize: 9, color: "var(--lys-text-faint)",
                    fontFamily: "var(--lys-font-mono)",
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>{s.tag}</div>
                </button>
              );
            })}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

function catChip(active: boolean, color: string): React.CSSProperties {
  return {
    padding: "1px 6px", borderRadius: 999, fontSize: 9,
    fontFamily: "var(--lys-font-mono)",
    border: `1px solid ${active ? color : "var(--lys-border-faint, rgba(0,0,0,0.08))"}`,
    background: active ? `${color}15` : "var(--lys-bg-2, #ffffff)",
    color: active ? color : "var(--lys-text-dim)",
    cursor: "pointer", fontWeight: active ? 700 : 400,
    textTransform: "lowercase",
  };
}
