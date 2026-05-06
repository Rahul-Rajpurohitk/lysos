/**
 * ChemistryNavbar — left sidebar for the Chemistry container.
 *
 * Power-BI-style strip with launchers, quick scaffolds, and a pathogen
 * swatch. Lives in the slot:"nav" of PlaygroundGroup. 130px wide.
 *
 * "All scaffolds" button is the SOLE scaffold entry — clicking it opens
 * a portal-rendered dropdown with search + 21-scaffold list (no duplicate
 * card in the main grid).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Sparkles, RefreshCw, Trash2, Bug, Search, X, ChevronRight } from "lucide-react";

interface Props {
  apiBase: string;
  pathogen: string;
  onLoadSmiles: (smi: string, name: string) => void;
  onClearCanvas?: () => void;
}

interface Scaffold {
  id: string;
  name: string;
  category: string;
  smiles: string;
  tag: string;
}

// Curated quick-pick set — must match scaffold names from /scaffolds endpoint
const QUICK_PICKS = [
  { name: "Benzene",            label: "Benzene",      sub: "6-ring", symbol: "⌬" },
  { name: "β-Lactam (penam core)", label: "β-Lactam",  sub: "penicillin",  symbol: "□" },
  { name: "Pyridine",           label: "Pyridine",     sub: "6-ring + N", symbol: "⬡" },
  { name: "Imidazole",          label: "Imidazole",    sub: "5-ring + 2N", symbol: "⬠" },
  { name: "Cyclohexane",        label: "Cyclohex.",    sub: "saturated", symbol: "⬢" },
];

const CAT_COLOR: Record<string, string> = {
  ring:       "#3b82f6",
  antibiotic: "#10b981",
  drug:       "#f59e0b",
  scratch:    "#94a3b8",
};

export function ChemistryNavbar({ apiBase, pathogen, onLoadSmiles, onClearCanvas }: Props) {
  const [scaffolds, setScaffolds] = useState<Scaffold[]>([]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeCat, setActiveCat] = useState<string>("");
  const [popPos, setPopPos] = useState<{ left: number; top: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    fetch(`${apiBase}/workbench/playground/scaffolds`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.scaffolds) setScaffolds(d.scaffolds); })
      .catch(() => {});
  }, [apiBase]);

  // Position popover next to navbar button when open
  useEffect(() => {
    if (!open) { setPopPos(null); return; }
    const update = () => {
      if (!triggerRef.current) return;
      const r = triggerRef.current.getBoundingClientRect();
      setPopPos({ left: r.right + 6, top: r.top });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open]);

  // Click-outside + Esc close
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
        s.smiles.toLowerCase().includes(q));
    }
    return arr;
  }, [scaffolds, query, activeCat]);

  const distinctCats = useMemo(() => {
    const counts: Record<string, number> = {};
    scaffolds.forEach((s) => { counts[s.category] = (counts[s.category] ?? 0) + 1; });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [scaffolds]);

  function pick(name: string) {
    const s = scaffolds.find((x) => x.name === name);
    if (s) onLoadSmiles(s.smiles, s.name);
  }
  function pickFromList(s: Scaffold) {
    onLoadSmiles(s.smiles, s.name);
    setOpen(false);
  }

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 6,
      fontFamily: "var(--lys-font-mono)",
    }}>
      {/* Section: launcher */}
      <NavSectionHeader icon={<Sparkles size={10} />} label="Library" />
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        title="Open the full scaffold library with search + filters"
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center", gap: 8, padding: "7px 8px",
          borderRadius: 6,
          border: `1px solid ${open ? "#10b981" : "var(--lys-border-faint, rgba(0,0,0,0.05))"}`,
          background: open ? "rgba(16,185,129,0.08)" : "var(--lys-bg-2, #ffffff)",
          cursor: "pointer", fontFamily: "var(--lys-font-body)",
          transition: "background 100ms, border-color 100ms",
          textAlign: "left", width: "100%",
        }}
        onMouseOver={(e) => { if (!open) {
          (e.currentTarget as HTMLElement).style.background = "rgba(16,185,129,0.08)";
          (e.currentTarget as HTMLElement).style.borderColor = "#10b98140";
        }}}
        onMouseOut={(e) => { if (!open) {
          (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-2, #ffffff)";
          (e.currentTarget as HTMLElement).style.borderColor = "var(--lys-border-faint, rgba(0,0,0,0.05))";
        }}}
      >
        <span style={{
          width: 22, height: 22,
          display: "flex", alignItems: "center", justifyContent: "center",
          flexShrink: 0,
        }}><Sparkles size={15} style={{ color: "#10b981" }} /></span>
        <span style={{ display: "flex", flexDirection: "column",
          gap: 1, minWidth: 0, flex: 1 }}>
          <span style={{
            fontSize: 11, fontWeight: 600,
            color: "var(--lys-text)",
          }}>All scaffolds</span>
          <span style={{
            fontSize: 8.5, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)",
          }}>{scaffolds.length} · search + filter</span>
        </span>
        <ChevronRight size={11} style={{
          color: "var(--lys-text-faint)",
          transform: open ? "rotate(90deg)" : "none",
          transition: "transform 120ms",
        }} />
      </button>

      {/* Section: quick picks — top molecular scaffolds */}
      <NavSectionHeader icon={<RefreshCw size={10} />} label="Quick load" />
      {QUICK_PICKS.map((q) => {
        const found = scaffolds.find((s) => s.name === q.name);
        return (
          <NavButton
            key={q.name}
            icon={<span style={{ fontSize: 16, lineHeight: 1, fontFamily: "ui-monospace, monospace" }}>{q.symbol}</span>}
            label={q.label}
            sub={q.sub}
            title={q.name + (found ? ` · ${found.smiles}` : " (loading...)")}
            disabled={!found}
            onClick={() => pick(q.name)}
            accent="#0891b2"
          />
        );
      })}

      {/* Section: tools */}
      <NavSectionHeader icon={<Trash2 size={10} />} label="Tools" />
      <NavButton
        icon={<Trash2 size={14} style={{ color: "#dc2626" }} />}
        label="Clear canvas"
        title="Remove the current molecule from the workspace"
        onClick={() => onClearCanvas?.()}
        accent="#dc2626"
      />

      {/* Section: pathogen context (shown but not editable here — change in Knowledge nav) */}
      <NavSectionHeader icon={<Bug size={10} />} label="Target pathogen" />
      <div title={`Currently designing for: ${pathogen}`}
        style={{
          display: "flex", flexDirection: "column",
          alignItems: "center", gap: 3,
          padding: "6px 4px",
          borderRadius: 5,
          background: "rgba(220,38,38,0.06)",
          border: "1px solid rgba(220,38,38,0.18)",
          fontFamily: "var(--lys-font-mono)",
        }}>
        <Bug size={14} style={{ color: "#dc2626" }} />
        <span style={{
          fontSize: 10, fontWeight: 700,
          color: "#dc2626", letterSpacing: "0.02em",
        }}>{pathogen}</span>
        <span style={{ fontSize: 8, color: "var(--lys-text-faint)" }}>active target</span>
      </div>

      {/* Portal popover — full scaffold library, opens to RIGHT of the
          navbar button so it appears next to the trigger */}
      {open && popPos && createPortal(
        <div data-scaffold-pop style={{
          position: "fixed", left: popPos.left, top: popPos.top,
          width: 480, maxHeight: "70vh",
          background: "var(--lys-bg-2, #ffffff)",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
          borderRadius: 10,
          boxShadow: "0 14px 40px rgba(15,23,42,0.18), 0 2px 8px rgba(15,23,42,0.10)",
          zIndex: 5000, display: "flex", flexDirection: "column",
          overflow: "hidden", fontFamily: "var(--lys-font-body)",
        }}>
          <div style={{
            padding: "8px 10px",
            borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
            display: "flex", flexDirection: "column", gap: 6,
            background: "var(--lys-bg, #fafafa)",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Search size={12} style={{ color: "var(--lys-text-faint)" }} />
              <input
                autoFocus value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="search scaffolds · name, tag, SMILES"
                style={{
                  flex: 1, fontSize: 12, fontFamily: "var(--lys-font-mono)",
                  padding: "5px 8px", borderRadius: 5,
                  border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
                  background: "var(--lys-bg-2, #ffffff)",
                  color: "var(--lys-text)", outline: "none",
                }} />
              <button type="button" onClick={() => setOpen(false)}
                style={{ border: 0, background: "transparent", cursor: "pointer",
                  padding: 4, color: "var(--lys-text-faint)",
                }}><X size={14} /></button>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
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
          <div className="lys-card-body" style={{
            flex: 1, overflow: "auto", padding: 6,
            display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4,
          }}>
            {filtered.length === 0 && (
              <div style={{
                gridColumn: "1 / -1", textAlign: "center", padding: 16,
                fontSize: 11, color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-mono)",
              }}>no matches</div>
            )}
            {filtered.map((s) => {
              const c = CAT_COLOR[s.category] ?? "#94a3b8";
              return (
                <button key={s.id} type="button"
                  onClick={() => pickFromList(s)}
                  title={s.smiles}
                  style={{
                    border: 0,
                    background: "var(--lys-bg, #fafafa)",
                    borderLeft: `3px solid ${c}`,
                    padding: "6px 10px", borderRadius: 4,
                    cursor: "pointer", fontFamily: "inherit",
                    textAlign: "left",
                    display: "flex", flexDirection: "column", gap: 2,
                    transition: "background 0.12s",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = `${c}12`)}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "var(--lys-bg, #fafafa)")}
                >
                  <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
                    <span style={{
                      fontSize: 8, padding: "1px 4px", borderRadius: 2,
                      background: `${c}18`, color: c, fontWeight: 700,
                      fontFamily: "var(--lys-font-mono)",
                      textTransform: "uppercase", letterSpacing: "0.05em",
                    }}>{s.category[0]}</span>
                    <span style={{
                      fontSize: 12, color: "var(--lys-text)", fontWeight: 600,
                      flex: 1, minWidth: 0,
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    }}>{s.name}</span>
                  </div>
                  <div style={{
                    fontSize: 10, color: "var(--lys-text-faint)",
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
    padding: "2px 7px", borderRadius: 999, fontSize: 9.5,
    fontFamily: "var(--lys-font-mono)",
    border: `1px solid ${active ? color : "var(--lys-border-faint, rgba(0,0,0,0.08))"}`,
    background: active ? `${color}15` : "var(--lys-bg-2, #ffffff)",
    color: active ? color : "var(--lys-text-dim)",
    cursor: "pointer", fontWeight: active ? 700 : 400,
    textTransform: "lowercase",
  };
}

function NavSectionHeader({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 4,
      fontSize: 9, color: "var(--lys-text-faint)",
      fontFamily: "var(--lys-font-mono)",
      letterSpacing: "0.06em", textTransform: "uppercase",
      padding: "4px 6px 2px 6px",
      marginTop: 4,
      borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
      fontWeight: 600,
    }}>
      {icon}
      <span>{label}</span>
    </div>
  );
}

function NavButton({ icon, label, sub, title, onClick, disabled, accent = "#94a3b8" }: {
  icon: React.ReactNode;
  label: string;
  sub?: string;
  title?: string;
  onClick: () => void;
  disabled?: boolean;
  accent?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "center", gap: 8,
        padding: "7px 8px",
        borderRadius: 6,
        border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
        background: "var(--lys-bg-2, #ffffff)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.45 : 1,
        fontFamily: "var(--lys-font-body)",
        transition: "background 100ms, border-color 100ms",
        textAlign: "left",
        width: "100%",
      }}
      onMouseOver={(e) => {
        if (disabled) return;
        (e.currentTarget as HTMLElement).style.background = `${accent}10`;
        (e.currentTarget as HTMLElement).style.borderColor = `${accent}40`;
      }}
      onMouseOut={(e) => {
        (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-2, #ffffff)";
        (e.currentTarget as HTMLElement).style.borderColor = "var(--lys-border-faint, rgba(0,0,0,0.05))";
      }}
    >
      <span style={{
        width: 22, height: 22,
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0,
      }}>{icon}</span>
      <span style={{ display: "flex", flexDirection: "column",
        gap: 1, minWidth: 0, flex: 1 }}>
        <span style={{
          fontSize: 11, fontWeight: 600,
          color: "var(--lys-text)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{label}</span>
        {sub && (
          <span style={{
            fontSize: 8.5, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>{sub}</span>
        )}
      </span>
    </button>
  );
}
