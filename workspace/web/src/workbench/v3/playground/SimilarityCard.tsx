/**
 * SimilarityCard — Tanimoto similarity vs. canonical antibiotics corpus.
 *
 * POSTs to /workbench/molecule/similarity → top-K closest known antibiotics
 * by Morgan fingerprint Tanimoto. Each hit shows:
 *   - drug name + class (color-coded)
 *   - Tanimoto bar (0-1) with numeric value
 *   - target pathogens
 *   - clickable → load that drug into canvas (if onLoad provided)
 *
 * Filter toggle: "only drugs targeting this pathogen" — narrows comparator
 * to the relevant SoC (standard of care) for the active pathogen.
 */
import { useEffect, useState } from "react";
import { GitCompare, RefreshCw, Filter } from "lucide-react";

interface Hit {
  drug_name: string;
  smiles: string;
  drug_class: string;
  target_pathogens: string[];
  tanimoto: number;
  common_atoms: number;
}

interface Resp {
  smiles: string;
  n_corpus: number;
  top: Hit[];
}

interface Props {
  apiBase: string;
  smiles: string | null;
  pathogen?: string;
  onLoad?: (smiles: string, name: string) => void;
}

const CLASS_COLOR: Record<string, string> = {
  "β-lactam": "#10b981", "beta-lactam": "#10b981",
  "cephalosporin": "#0891b2", "carbapenem": "#7c3aed",
  "fluoroquinolone": "#ea580c", "macrolide": "#dc2626",
  "tetracycline": "#ca8a04", "aminoglycoside": "#2563eb",
  "glycopeptide": "#a855f7", "oxazolidinone": "#0d9488",
};

function classColor(c: string): string {
  const lc = (c || "").toLowerCase();
  for (const k of Object.keys(CLASS_COLOR)) if (lc.includes(k)) return CLASS_COLOR[k];
  return "#6b7280";
}

export function SimilarityCard({ apiBase, smiles, pathogen, onLoad }: Props) {
  const [data, setData] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);
  const [filterByPath, setFilterByPath] = useState(false);

  async function refresh() {
    if (!smiles) { setData(null); return; }
    setLoading(true);
    try {
      const body: any = { smiles, top_k: 10 };
      if (filterByPath && pathogen) body.pathogen = pathogen;
      const r = await fetch(`${apiBase}/workbench/molecule/similarity`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) return;
      setData(await r.json());
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [smiles, filterByPath, apiBase]);

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
        <GitCompare size={11} style={{ color: "#7c3aed" }} />
        <span>similarity · {data ? `${data.top.length} hits / ${data.n_corpus} corpus` : "Tanimoto"}</span>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={refresh} disabled={loading}
          style={{ border: 0, background: "transparent", cursor: "pointer", padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      {pathogen && smiles && (
        <div style={{ padding: "3px 8px", borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 4,
            fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-dim)", cursor: "pointer" }}>
            <input type="checkbox" checked={filterByPath} onChange={(e) => setFilterByPath(e.target.checked)} />
            <Filter size={9} />
            only drugs treating {pathogen}
          </label>
        </div>
      )}

      <div style={{ flex: 1, overflow: "auto", padding: "4px 0" }}>
        {!smiles && (
          <div style={{ padding: "20px 10px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 10.5,
            fontFamily: "var(--lys-font-mono)" }}>
            no candidate · pick or design one
          </div>
        )}
        {smiles && loading && !data && (
          <div style={{ padding: "20px 10px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 10.5,
            fontFamily: "var(--lys-font-mono)" }}>
            computing Morgan fingerprints…
          </div>
        )}
        {smiles && data && data.top.length === 0 && (
          <div style={{ padding: "20px 10px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 10.5,
            fontFamily: "var(--lys-font-mono)" }}>
            no similar drugs in corpus
          </div>
        )}
        {smiles && data && data.top.map((h, i) => {
          const c = classColor(h.drug_class);
          const tanPct = Math.max(0, Math.min(1, h.tanimoto));
          return (
            <div key={`${h.drug_name}-${i}`}
              style={{
                padding: "5px 8px", display: "flex", flexDirection: "column", gap: 2,
                borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
                borderLeft: `3px solid ${c}`,
                cursor: onLoad && h.smiles ? "pointer" : "default",
              }}
              onClick={() => h.smiles && onLoad?.(h.smiles, h.drug_name)}
              onMouseOver={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-3, rgba(0,0,0,0.02))"; }}
              onMouseOut={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 10.5, fontWeight: 700,
                  color: "var(--lys-text)", fontFamily: "var(--lys-font-mono)" }}>
                  #{i+1} {h.drug_name}
                </span>
                <span style={{ fontSize: 8.5, padding: "1px 5px", borderRadius: 4,
                  background: `${c}15`, color: c, fontWeight: 600,
                  fontFamily: "var(--lys-font-mono)" }}>
                  {h.drug_class || "—"}
                </span>
                <span style={{ flex: 1 }} />
                <span style={{ fontSize: 11, fontWeight: 700, color: "#7c3aed",
                  fontFamily: "var(--lys-font-mono)" }}>
                  {h.tanimoto.toFixed(3)}
                </span>
              </div>
              {/* Tanimoto bar */}
              <div style={{ height: 4, borderRadius: 2,
                background: "var(--lys-border-faint, rgba(0,0,0,0.04))",
                overflow: "hidden" }}>
                <div style={{
                  height: "100%", width: `${tanPct * 100}%`,
                  background: "linear-gradient(90deg, #7c3aed 0%, #a855f7 100%)",
                  transition: "width 200ms ease",
                }} />
              </div>
              {h.target_pathogens.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                  {h.target_pathogens.slice(0, 5).map((p) => (
                    <span key={p} style={{
                      fontSize: 8.5, padding: "0 4px", borderRadius: 999,
                      background: pathogen && p.toLowerCase() === pathogen.toLowerCase() ? "#dc2626" : "rgba(0,0,0,0.05)",
                      color: pathogen && p.toLowerCase() === pathogen.toLowerCase() ? "white" : "var(--lys-text-dim)",
                      fontFamily: "var(--lys-font-mono)",
                    }}>{p}</span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
