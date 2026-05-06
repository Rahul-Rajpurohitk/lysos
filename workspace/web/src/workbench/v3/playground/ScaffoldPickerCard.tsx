/**
 * ScaffoldPickerCard — start-from-template launcher.
 *
 * Pulls /workbench/playground/scaffolds and renders 21 curated starting
 * molecules (rings, antibiotic cores, FDA drugs, blank-canvas). Click
 * a card → loads that SMILES into the canvas state via onLoadSmiles.
 *
 * Categories show as colored tags. Search filter at top.
 */
import { useEffect, useMemo, useState } from "react";
import { Search, Sparkles } from "lucide-react";

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

export function ScaffoldPickerCard({ apiBase, onLoadSmiles }: Props) {
  const [scaffolds, setScaffolds] = useState<Scaffold[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${apiBase}/workbench/playground/scaffolds`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => { setScaffolds(d.scaffolds ?? []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [apiBase]);

  const filtered = useMemo(() => {
    if (!query.trim()) return scaffolds;
    const q = query.toLowerCase();
    return scaffolds.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.tag.toLowerCase().includes(q) ||
        s.smiles.toLowerCase().includes(q) ||
        s.category.includes(q)
    );
  }, [scaffolds, query]);

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
    }}>
      <div style={{
        padding: "5px 10px",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 9.5,
        fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)",
        letterSpacing: "0.06em",
        textTransform: "uppercase",
      }}>
        <Sparkles size={11} />
        <span>start from · {filtered.length}/{scaffolds.length}</span>
        <span style={{ flex: 1 }} />
        <Search size={10} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="search…"
          style={{
            border: 0, background: "transparent", outline: 0,
            font: "inherit", textTransform: "none", letterSpacing: 0,
            color: "var(--lys-text)", width: 90,
          }}
        />
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: 6 }}>
        {loading && <div style={{ color: "var(--lys-text-faint)", fontSize: 10.5, padding: 8 }}>loading…</div>}
        {!loading && filtered.length === 0 && (
          <div style={{ color: "var(--lys-text-faint)", fontSize: 10.5, padding: 8 }}>no matches</div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
          {filtered.map((s) => {
            const color = CAT_COLOR[s.category] ?? "#94a3b8";
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => onLoadSmiles?.(s.smiles, s.name)}
                title={s.smiles}
                style={{
                  border: 0,
                  background: "var(--lys-bg, #fafafa)",
                  borderLeft: `3px solid ${color}`,
                  padding: "4px 7px",
                  borderRadius: 4,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  textAlign: "left",
                  display: "flex", flexDirection: "column", gap: 1,
                  transition: "background 0.12s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = `${color}10`)}
                onMouseLeave={(e) => (e.currentTarget.style.background = "var(--lys-bg, #fafafa)")}
              >
                <div style={{
                  display: "flex", alignItems: "baseline", gap: 4,
                }}>
                  <span style={{
                    fontSize: 8, padding: "0 4px", borderRadius: 2,
                    background: `${color}18`, color, fontWeight: 700,
                    fontFamily: "var(--lys-font-mono)",
                    textTransform: "uppercase", letterSpacing: "0.05em",
                  }}>
                    {s.category[0]}
                  </span>
                  <span style={{
                    fontSize: 11, color: "var(--lys-text)", fontWeight: 600,
                    flex: 1, minWidth: 0,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>
                    {s.name}
                  </span>
                </div>
                <div style={{
                  fontSize: 9, color: "var(--lys-text-faint)",
                  fontFamily: "var(--lys-font-mono)",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>
                  {s.tag}
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
