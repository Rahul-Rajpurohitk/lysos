/**
 * ChemistryTopNav — compact horizontal toolbar for the Chemistry container.
 *
 * Replaces the left sidebar with a 44-px horizontal strip containing:
 *   [✦ All scaffolds ▾]  [Bnz][β-L][Pyr][Imd][Cyc]   |   [Clear]   [🦠 MRSA ▾]
 *
 * "All scaffolds" opens a portal-rendered popover (same as before) with
 * search + 21-scaffold list. Pathogen pill is a dropdown trigger that
 * opens a small popover for switching active pathogen.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Sparkles, Trash2, Bug, Search, X, ChevronDown } from "lucide-react";

interface Scaffold { id: string; name: string; category: string; smiles: string; tag: string; }

interface Props {
  apiBase: string;
  pathogen: string;
  onPathogenChange?: (code: string) => void;
  onLoadSmiles: (smi: string, name: string) => void;
  onClearCanvas?: () => void;
}

const CAT_COLOR: Record<string, string> = {
  ring:       "#3b82f6",
  antibiotic: "#10b981",
  drug:       "#f59e0b",
  scratch:    "#94a3b8",
};

const QUICK_PICKS = [
  { name: "Benzene",                 label: "Benzene",     symbol: "⌬" },
  { name: "β-Lactam (penam core)",   label: "β-Lactam",    symbol: "□" },
  { name: "Pyridine",                label: "Pyridine",    symbol: "⬡" },
  { name: "Imidazole",               label: "Imidazole",   symbol: "⬠" },
  { name: "Cyclohexane",             label: "Cyclohex.",   symbol: "⬢" },
];

const PATHOGENS = [
  { code: "MRSA",        label: "MRSA · S. aureus" },
  { code: "Mtb",         label: "TB · M. tuberculosis" },
  { code: "EColi-CRE",   label: "E. coli (carbapenem-R)" },
  { code: "KpneuCRE",    label: "Klebsiella (carbapenem-R)" },
  { code: "Abaum",       label: "A. baumannii" },
  { code: "Paer",        label: "P. aeruginosa" },
  { code: "VRE",         label: "VRE · vanco-R" },
  { code: "NGono",       label: "N. gonorrhoeae" },
];

export function ChemistryTopNav({ apiBase, pathogen, onPathogenChange, onLoadSmiles, onClearCanvas }: Props) {
  const [scaffolds, setScaffolds] = useState<Scaffold[]>([]);
  const [scaffoldOpen, setScaffoldOpen] = useState(false);
  const [pathogenOpen, setPathogenOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeCat, setActiveCat] = useState("");
  const [scaffoldPos, setScaffoldPos] = useState<{ left: number; top: number } | null>(null);
  const [pathogenPos, setPathogenPos] = useState<{ left: number; top: number } | null>(null);
  const scaffoldRef = useRef<HTMLButtonElement | null>(null);
  const pathogenRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    fetch(`${apiBase}/workbench/playground/scaffolds`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.scaffolds) setScaffolds(d.scaffolds); })
      .catch(() => {});
  }, [apiBase]);

  useEffect(() => {
    if (!scaffoldOpen) { setScaffoldPos(null); return; }
    const update = () => {
      if (!scaffoldRef.current) return;
      const r = scaffoldRef.current.getBoundingClientRect();
      setScaffoldPos({ left: r.left, top: r.bottom + 4 });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [scaffoldOpen]);

  useEffect(() => {
    if (!pathogenOpen) { setPathogenPos(null); return; }
    const update = () => {
      if (!pathogenRef.current) return;
      const r = pathogenRef.current.getBoundingClientRect();
      setPathogenPos({ left: r.right - 240, top: r.bottom + 4 });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [pathogenOpen]);

  // Click-outside / Esc close
  useEffect(() => {
    if (!scaffoldOpen && !pathogenOpen) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("[data-scaffold-pop]")) return;
      if (t.closest("[data-pathogen-pop]")) return;
      if (scaffoldRef.current?.contains(t)) return;
      if (pathogenRef.current?.contains(t)) return;
      setScaffoldOpen(false);
      setPathogenOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setScaffoldOpen(false); setPathogenOpen(false); } };
    setTimeout(() => document.addEventListener("mousedown", onDoc), 0);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [scaffoldOpen, pathogenOpen]);

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

  return (
    <>
      {/* All scaffolds dropdown */}
      <button ref={scaffoldRef} type="button"
        onClick={() => setScaffoldOpen((o) => !o)}
        title="Open the full scaffold library with search + filters"
        style={{
          display: "flex", alignItems: "center", gap: 6, padding: "6px 10px",
          borderRadius: 6,
          border: `1px solid ${scaffoldOpen ? "#10b981" : "var(--lys-border-faint, rgba(0,0,0,0.10))"}`,
          background: scaffoldOpen ? "rgba(16,185,129,0.08)" : "var(--lys-bg-2, #ffffff)",
          cursor: "pointer", fontFamily: "var(--lys-font-body)",
          fontSize: 11, fontWeight: 600, color: "var(--lys-text)",
          flexShrink: 0,
        }}>
        <Sparkles size={13} style={{ color: "#10b981" }} />
        <span>All scaffolds</span>
        <span style={{
          fontSize: 9, padding: "1px 6px", borderRadius: 999,
          background: "rgba(16,185,129,0.12)", color: "#10b981",
          fontFamily: "var(--lys-font-mono)", fontWeight: 700,
        }}>{scaffolds.length}</span>
        <ChevronDown size={11} style={{
          color: "var(--lys-text-faint)",
          transform: scaffoldOpen ? "rotate(180deg)" : "none",
          transition: "transform 120ms",
        }} />
      </button>

      {/* Vertical divider */}
      <div style={{ width: 1, height: 24, background: "var(--lys-border-faint, rgba(0,0,0,0.10))", flexShrink: 0 }} />

      {/* Quick picks */}
      <span style={{ fontSize: 9, color: "var(--lys-text-faint)",
        fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase",
        flexShrink: 0,
      }}>quick</span>
      {QUICK_PICKS.map((q) => {
        const found = scaffolds.find((s) => s.name === q.name);
        return (
          <button key={q.name} type="button"
            onClick={() => pick(q.name)}
            disabled={!found}
            title={q.name + (found ? ` · ${found.smiles}` : " (loading...)")}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "5px 9px", borderRadius: 999,
              border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
              background: "var(--lys-bg-2, #ffffff)",
              cursor: found ? "pointer" : "not-allowed",
              opacity: found ? 1 : 0.45,
              fontSize: 11, fontFamily: "var(--lys-font-body)",
              color: "var(--lys-text)", flexShrink: 0,
              transition: "background 100ms, border-color 100ms",
            }}
            onMouseOver={(e) => { if (found) {
              (e.currentTarget as HTMLElement).style.background = "rgba(8,145,178,0.08)";
              (e.currentTarget as HTMLElement).style.borderColor = "#0891b240";
            }}}
            onMouseOut={(e) => {
              (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-2, #ffffff)";
              (e.currentTarget as HTMLElement).style.borderColor = "var(--lys-border-faint, rgba(0,0,0,0.08))";
            }}>
            <span style={{ fontSize: 13, lineHeight: 1, fontFamily: "ui-monospace, monospace" }}>{q.symbol}</span>
            <span style={{ fontWeight: 500 }}>{q.label}</span>
          </button>
        );
      })}

      <span style={{ flex: 1 }} />

      {/* Clear canvas */}
      <button type="button" onClick={() => onClearCanvas?.()}
        title="Remove the current molecule from the workspace"
        style={{
          display: "flex", alignItems: "center", gap: 5, padding: "5px 9px",
          borderRadius: 6,
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
          background: "var(--lys-bg-2, #ffffff)",
          cursor: "pointer", fontFamily: "var(--lys-font-body)",
          fontSize: 11, color: "var(--lys-text-dim)", flexShrink: 0,
        }}
        onMouseOver={(e) => {
          (e.currentTarget as HTMLElement).style.background = "rgba(220,38,38,0.06)";
          (e.currentTarget as HTMLElement).style.borderColor = "rgba(220,38,38,0.3)";
        }}
        onMouseOut={(e) => {
          (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-2, #ffffff)";
          (e.currentTarget as HTMLElement).style.borderColor = "var(--lys-border-faint, rgba(0,0,0,0.08))";
        }}>
        <Trash2 size={12} />
        <span>Clear</span>
      </button>

      {/* Pathogen pill */}
      <button ref={pathogenRef} type="button"
        onClick={() => setPathogenOpen((o) => !o)}
        title="Switch active target pathogen"
        style={{
          display: "flex", alignItems: "center", gap: 5, padding: "5px 9px",
          borderRadius: 999,
          border: `1px solid ${pathogenOpen ? "#dc2626" : "rgba(220,38,38,0.20)"}`,
          background: pathogenOpen ? "rgba(220,38,38,0.10)" : "rgba(220,38,38,0.06)",
          cursor: "pointer", fontFamily: "var(--lys-font-body)",
          fontSize: 11, fontWeight: 700, color: "#dc2626", flexShrink: 0,
        }}>
        <Bug size={12} />
        <span>{pathogen}</span>
        <ChevronDown size={11} style={{
          transform: pathogenOpen ? "rotate(180deg)" : "none",
          transition: "transform 120ms",
        }} />
      </button>

      {/* Scaffold popover */}
      {scaffoldOpen && scaffoldPos && createPortal(
        <div data-scaffold-pop style={{
          position: "fixed", left: scaffoldPos.left, top: scaffoldPos.top,
          width: 480, maxHeight: "60vh",
          background: "var(--lys-bg-2, #ffffff)",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
          borderRadius: 10,
          boxShadow: "0 14px 40px rgba(15,23,42,0.18), 0 2px 8px rgba(15,23,42,0.10)",
          zIndex: 5000, display: "flex", flexDirection: "column",
          overflow: "hidden", fontFamily: "var(--lys-font-body)",
        }}>
          <div style={{ padding: "8px 10px",
            borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
            display: "flex", flexDirection: "column", gap: 6,
            background: "var(--lys-bg, #fafafa)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Search size={12} style={{ color: "var(--lys-text-faint)" }} />
              <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder="search scaffolds · name, tag, SMILES"
                style={{ flex: 1, fontSize: 12, fontFamily: "var(--lys-font-mono)",
                  padding: "5px 8px", borderRadius: 5,
                  border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
                  background: "var(--lys-bg-2, #ffffff)",
                  color: "var(--lys-text)", outline: "none" }} />
              <button type="button" onClick={() => setScaffoldOpen(false)}
                style={{ border: 0, background: "transparent", cursor: "pointer",
                  padding: 4, color: "var(--lys-text-faint)" }}><X size={14} /></button>
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
            display: "grid", gridTemplateColumns: "1fr 1fr", gap: 3 }}>
            {filtered.length === 0 && (
              <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: 16,
                fontSize: 11, color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-mono)" }}>no matches</div>
            )}
            {filtered.map((s) => {
              const c = CAT_COLOR[s.category] ?? "#94a3b8";
              return (
                <button key={s.id} type="button"
                  onClick={() => { onLoadSmiles(s.smiles, s.name); setScaffoldOpen(false); }}
                  title={s.smiles}
                  style={{ border: 0, background: "var(--lys-bg, #fafafa)",
                    borderLeft: `3px solid ${c}`, padding: "5px 9px", borderRadius: 4,
                    cursor: "pointer", fontFamily: "inherit", textAlign: "left",
                    display: "flex", flexDirection: "column", gap: 1 }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = `${c}12`)}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "var(--lys-bg, #fafafa)")}>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
                    <span style={{ fontSize: 8, padding: "1px 4px", borderRadius: 2,
                      background: `${c}18`, color: c, fontWeight: 700,
                      fontFamily: "var(--lys-font-mono)",
                      textTransform: "uppercase", letterSpacing: "0.05em" }}>{s.category[0]}</span>
                    <span style={{ fontSize: 11, color: "var(--lys-text)", fontWeight: 600,
                      flex: 1, minWidth: 0,
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    }}>{s.name}</span>
                  </div>
                  <div style={{ fontSize: 9, color: "var(--lys-text-faint)",
                    fontFamily: "var(--lys-font-mono)",
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>{s.tag}</div>
                </button>
              );
            })}
          </div>
        </div>, document.body)}

      {/* Pathogen popover */}
      {pathogenOpen && pathogenPos && createPortal(
        <div data-pathogen-pop style={{
          position: "fixed", left: Math.max(8, pathogenPos.left), top: pathogenPos.top,
          width: 240,
          background: "var(--lys-bg-2, #ffffff)",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
          borderRadius: 8,
          boxShadow: "0 12px 32px rgba(15,23,42,0.18), 0 2px 6px rgba(15,23,42,0.10)",
          zIndex: 5000, display: "flex", flexDirection: "column",
          overflow: "hidden", fontFamily: "var(--lys-font-body)",
        }}>
          {PATHOGENS.map((pg) => {
            const active = pg.code === pathogen;
            return (
              <button key={pg.code} type="button"
                onClick={() => { onPathogenChange?.(pg.code); setPathogenOpen(false); }}
                style={{
                  border: 0, padding: "6px 10px",
                  borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
                  background: active ? "#dc2626" : "var(--lys-bg-2, #ffffff)",
                  color: active ? "white" : "var(--lys-text)",
                  cursor: "pointer", fontFamily: "inherit",
                  fontSize: 11, fontWeight: active ? 700 : 500,
                  textAlign: "left", display: "flex", alignItems: "center", gap: 6,
                }}
                onMouseEnter={(e) => { if (!active) (e.currentTarget as HTMLElement).style.background = "rgba(220,38,38,0.06)"; }}
                onMouseLeave={(e) => { if (!active) (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-2, #ffffff)"; }}>
                <Bug size={11} style={{ color: active ? "white" : "#dc2626" }} />
                <span>{pg.label}</span>
              </button>
            );
          })}
        </div>, document.body)}
    </>
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
