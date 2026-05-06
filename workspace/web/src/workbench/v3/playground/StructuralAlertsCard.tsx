/**
 * StructuralAlertsCard — DB-backed PAINS / toxicophore detection.
 *
 * Sends the active SMILES to /workbench/playground/knowledge/alerts and
 * renders any hits with severity-coded badges. Empty state shows the
 * registered alert library so the user can browse before any candidate
 * is loaded.
 */
import { useEffect, useState } from "react";
import { ShieldAlert, BookOpen, RefreshCw } from "lucide-react";

interface AlertHit {
  name: string;
  smarts: string;
  severity: string;
  category?: string;
  note?: string;
}

interface Props {
  apiBase: string;
  smiles: string | null;
}

const SEVERITY_COLOR: Record<string, string> = {
  high: "#dc2626",
  medium: "#d97706",
  low: "#65a30d",
  info: "#3b82f6",
};

export function StructuralAlertsCard({ apiBase, smiles }: Props) {
  const [hits, setHits] = useState<AlertHit[]>([]);
  const [library, setLibrary] = useState<AlertHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      if (smiles) {
        const r = await fetch(`${apiBase}/workbench/playground/knowledge/alerts?smiles=${encodeURIComponent(smiles)}`);
        if (!r.ok) throw new Error(`http ${r.status}`);
        const d = await r.json();
        setHits(d.hits ?? []);
      } else {
        const r = await fetch(`${apiBase}/workbench/playground/knowledge/alerts`);
        if (!r.ok) throw new Error(`http ${r.status}`);
        const d = await r.json();
        setLibrary(d.alerts ?? []);
        setHits([]);
      }
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [smiles, apiBase]);

  const showHits = !!smiles && hits.length > 0;
  const showClear = !!smiles && hits.length === 0 && !loading;
  const showLib = !smiles && library.length > 0;

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
        {showHits ? <ShieldAlert size={11} style={{ color: "#dc2626" }} /> : <BookOpen size={11} />}
        <span>{showHits ? `alerts · ${hits.length} hit` : `alerts · library · ${library.length}`}</span>
        <span style={{ flex: 1 }} />
        <button
          type="button" onClick={refresh}
          style={{ border: 0, background: "transparent", cursor: "pointer", padding: 2, color: "var(--lys-text-faint)" }}
          title="Refresh"
        ><RefreshCw size={11} /></button>
      </div>
      {error && <div style={{ padding: 8, color: "#dc2626", fontSize: 10, fontFamily: "var(--lys-font-mono)" }}>{error}</div>}
      {showClear && (
        <div style={{
          flex: 1, display: "grid", placeItems: "center",
          color: "#10b981", fontSize: 11, padding: 10, gap: 4, textAlign: "center",
        }}>
          <span style={{ fontSize: 18 }}>✓</span>
          <span>no PAINS / toxicophore hits</span>
          <span style={{ color: "var(--lys-text-faint)", fontSize: 10 }}>scanned against {library.length || "20"} alerts</span>
        </div>
      )}
      <div style={{ flex: 1, overflow: "auto" }}>
        {(showHits ? hits : showLib ? library : []).map((a, i) => {
          const sev = (a.severity ?? "medium").toLowerCase();
          const color = SEVERITY_COLOR[sev] ?? "#9ca3af";
          return (
            <div key={i} style={{
              padding: "5px 10px",
              borderLeft: `3px solid ${color}`,
              borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
              display: "flex", flexDirection: "column", gap: 2,
              fontSize: 10.5,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontWeight: 600, color: "var(--lys-text)", flex: 1 }}>{a.name}</span>
                <span style={{
                  fontSize: 8, fontFamily: "var(--lys-font-mono)",
                  padding: "1px 5px", borderRadius: 3,
                  background: `${color}18`, color, fontWeight: 700,
                  letterSpacing: "0.06em",
                }}>
                  {sev.toUpperCase()}
                </span>
                {a.category && (
                  <span style={{ fontSize: 8, color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)" }}>
                    {a.category}
                  </span>
                )}
              </div>
              {a.note && (
                <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)", lineHeight: 1.35 }}>
                  {a.note}
                </div>
              )}
              <div style={{ fontSize: 9, color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)" }}>
                {a.smarts}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
