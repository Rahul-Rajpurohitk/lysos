/**
 * AntibioticReferenceCard — searchable reference of known antibiotics.
 *
 * Reads /workbench/antibiotics (canonical parquet, hundreds of drugs)
 * with filters by pathogen target. Click a row → loads that drug's
 * SMILES into the canvas (if onLoad is provided).
 *
 * Provides DEEP value with NO loaded candidate — pure reference look-up.
 * Examples of common queries:
 *   - "show me all β-lactams"
 *   - "what's active against MRSA"
 *   - "sort by drug class"
 */
import { useEffect, useMemo, useState } from "react";
import { Pill, Search, RefreshCw, Filter } from "lucide-react";

interface Antibiotic {
  name: string;
  smiles: string;
  drug_class: string;
  target_pathogens: string[];
}

interface Props {
  apiBase: string;
  pathogen?: string;        // pre-filter to this pathogen if set
  onLoad?: (smiles: string, name: string) => void;
}

const DRUG_CLASS_COLOR: Record<string, string> = {
  "β-lactam":            "#10b981",
  "beta-lactam":         "#10b981",
  "cephalosporin":       "#0891b2",
  "carbapenem":          "#7c3aed",
  "fluoroquinolone":     "#ea580c",
  "macrolide":           "#dc2626",
  "tetracycline":        "#ca8a04",
  "aminoglycoside":      "#2563eb",
  "glycopeptide":        "#a855f7",
  "oxazolidinone":       "#0d9488",
  "polymyxin":           "#9a3412",
  "sulfonamide":         "#9333ea",
  "rifamycin":           "#be185d",
  "lipopeptide":         "#1e40af",
};

function classColor(cls: string): string {
  const lc = cls.toLowerCase();
  for (const k of Object.keys(DRUG_CLASS_COLOR)) {
    if (lc.includes(k)) return DRUG_CLASS_COLOR[k];
  }
  return "#6b7280";
}

export function AntibioticReferenceCard({ apiBase, pathogen, onLoad }: Props) {
  const [drugs, setDrugs] = useState<Antibiotic[]>([]);
  const [query, setQuery] = useState("");
  const [activeClass, setActiveClass] = useState<string>("");
  const [filterByPath, setFilterByPath] = useState(false);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (query) params.set("q", query);
      if (filterByPath && pathogen) params.set("pathogen", pathogen);
      params.set("limit", "200");
      const r = await fetch(`${apiBase}/workbench/antibiotics?${params.toString()}`);
      if (!r.ok) return;
      const d = await r.json();
      setDrugs(d.antibiotics ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [query, filterByPath, pathogen, apiBase]);

  // Derive distinct drug classes for chip filters
  const classOpts = useMemo(() => {
    const counts: Record<string, number> = {};
    drugs.forEach((d) => {
      const c = d.drug_class || "—";
      counts[c] = (counts[c] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [drugs]);

  const visible = useMemo(() => {
    if (!activeClass) return drugs;
    return drugs.filter((d) => (d.drug_class || "").toLowerCase().includes(activeClass.toLowerCase()));
  }, [drugs, activeClass]);

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
    }}>
      <div style={{
        padding: "5px 10px",
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", letterSpacing: "0.06em",
        textTransform: "uppercase",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <Pill size={11} style={{ color: "#0891b2" }} />
        <span>antibiotics · {visible.length}{drugs.length !== visible.length ? `/${drugs.length}` : ""}</span>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={refresh} disabled={loading}
          style={{ border: 0, background: "transparent", cursor: "pointer", padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      {/* Search + filters */}
      <div style={{ padding: "5px 8px", display: "flex", flexDirection: "column", gap: 4,
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Search size={10} style={{ color: "var(--lys-text-faint)" }} />
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="search · name, class, pathogen"
            style={{
              flex: 1, fontSize: 10, fontFamily: "var(--lys-font-mono)",
              padding: "2px 6px", borderRadius: 4,
              border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
              background: "var(--lys-bg-1, #ffffff)", color: "var(--lys-text)",
              outline: "none",
            }} />
        </div>
        {pathogen && (
          <label style={{ display: "flex", alignItems: "center", gap: 4,
            fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-dim)", cursor: "pointer" }}>
            <input type="checkbox" checked={filterByPath} onChange={(e) => setFilterByPath(e.target.checked)} />
            <Filter size={9} />
            target {pathogen} only
          </label>
        )}
        {classOpts.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
            <button type="button" onClick={() => setActiveClass("")}
              style={chipStyle(activeClass === "")}>all · {drugs.length}</button>
            {classOpts.slice(0, 12).map(([c, n]) => (
              <button key={c} type="button" onClick={() => setActiveClass(c === activeClass ? "" : c)}
                style={chipStyle(c === activeClass, classColor(c))}>{c} · {n}</button>
            ))}
          </div>
        )}
      </div>

      {/* Drug list */}
      <div style={{ flex: 1, overflow: "auto" }}>
        {visible.length === 0 && !loading && (
          <div style={{ padding: "20px 10px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 10.5,
            fontFamily: "var(--lys-font-mono)" }}>
            {query ? "no matches" : "loading antibiotic corpus…"}
          </div>
        )}
        {visible.map((d, i) => {
          const c = classColor(d.drug_class);
          return (
            <div key={`${d.name}-${i}`}
              style={{
                padding: "5px 8px", display: "flex", flexDirection: "column", gap: 2,
                borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
                borderLeft: `3px solid ${c}`,
                cursor: onLoad && d.smiles ? "pointer" : "default",
                background: "var(--lys-bg-2, #ffffff)",
              }}
              onClick={() => d.smiles && onLoad?.(d.smiles, d.name)}
              onMouseOver={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-3, rgba(0,0,0,0.02))"; }}
              onMouseOut={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-2, #ffffff)"; }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: "var(--lys-text)",
                  fontFamily: "var(--lys-font-mono)" }}>{d.name}</span>
                <span style={{ fontSize: 8.5, padding: "1px 5px", borderRadius: 4,
                  background: `${c}15`, color: c, fontWeight: 600,
                  fontFamily: "var(--lys-font-mono)" }}>{d.drug_class || "—"}</span>
              </div>
              {d.target_pathogens.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                  {d.target_pathogens.slice(0, 6).map((p) => (
                    <span key={p} style={{
                      fontSize: 8.5, padding: "0 4px", borderRadius: 999,
                      background: pathogen && p.toLowerCase() === pathogen.toLowerCase() ? "#dc2626" : "rgba(0,0,0,0.05)",
                      color: pathogen && p.toLowerCase() === pathogen.toLowerCase() ? "white" : "var(--lys-text-dim)",
                      fontFamily: "var(--lys-font-mono)",
                    }}>{p}</span>
                  ))}
                </div>
              )}
              {d.smiles && (
                <div style={{ fontSize: 9, color: "var(--lys-text-faint)",
                  fontFamily: "var(--lys-font-mono)", wordBreak: "break-all" }}>
                  {d.smiles.length > 65 ? d.smiles.slice(0, 62) + "…" : d.smiles}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function chipStyle(active: boolean, color: string = "#0891b2"): React.CSSProperties {
  return {
    padding: "1px 6px", borderRadius: 999, fontSize: 9,
    fontFamily: "var(--lys-font-mono)",
    border: `1px solid ${active ? color : "var(--lys-border-faint, rgba(0,0,0,0.08))"}`,
    background: active ? `${color}15` : "var(--lys-bg-3, rgba(0,0,0,0.02))",
    color: active ? color : "var(--lys-text-dim)",
    cursor: "pointer", fontWeight: active ? 700 : 400,
  };
}
