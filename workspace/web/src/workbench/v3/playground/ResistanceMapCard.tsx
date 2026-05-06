/**
 * ResistanceMapCard — pathogen × gene × defeated-class lookups.
 *
 * Reads /workbench/playground/knowledge/resistance?pathogen=… and renders
 * a curated list of resistance facts: gene name, encoded protein, mechanism,
 * defeated drug classes, escape exceptions, MIC shift, citation.
 *
 * Pulls from the curated rules/resistance_facts.json (17 entries across
 * MRSA, EColi-CRE, Abaum, Paer, VRE, Mtb, NGono).
 */
import { useEffect, useState } from "react";
import { Shield, RefreshCw } from "lucide-react";

interface ResistanceFact {
  pathogen: string;
  gene: string;
  encodes: string;
  mechanism: string;
  defeats: string[];
  exceptions: string[];
  MIC_shift: string;
  citation: string;
}

interface Props {
  apiBase: string;
  pathogen: string;
}

export function ResistanceMapCard({ apiBase, pathogen }: Props) {
  const [facts, setFacts] = useState<ResistanceFact[]>([]);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/workbench/playground/knowledge/resistance?pathogen=${encodeURIComponent(pathogen)}`);
      if (!r.ok) return;
      const d = await r.json();
      setFacts(d.facts ?? []);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [pathogen]);

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
        <Shield size={11} style={{ color: "#dc2626" }} />
        <span>resistance · {pathogen} · {facts.length} fact{facts.length !== 1 ? "s" : ""}</span>
        <span style={{ flex: 1 }} />
        <button
          type="button" onClick={refresh}
          disabled={loading}
          style={{ border: 0, background: "transparent", cursor: "pointer", padding: 2, color: "var(--lys-text-faint)" }}
          title="Refresh"
        ><RefreshCw size={11} /></button>
      </div>
      <div style={{ flex: 1, overflow: "auto" }}>
        {facts.length === 0 && !loading && (
          <div style={{
            color: "var(--lys-text-faint)", fontSize: 10.5, padding: 10,
            textAlign: "center", fontFamily: "var(--lys-font-mono)",
          }}>
            no curated facts for {pathogen}
          </div>
        )}
        {facts.map((f, i) => (
          <div key={i} style={{
            padding: "6px 10px",
            borderLeft: "3px solid #dc2626",
            borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
            display: "flex", flexDirection: "column", gap: 3,
            fontSize: 10.5,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{
                fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                color: "#dc2626", fontSize: 11,
              }}>
                {f.gene}
              </span>
              <span style={{ color: "var(--lys-text-dim)", fontSize: 10 }}>
                → {f.encodes}
              </span>
            </div>
            <div style={{ fontSize: 10, color: "var(--lys-text)", lineHeight: 1.4 }}>
              {f.mechanism}
            </div>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {(f.defeats ?? []).map((d) => (
                <span key={d} style={{
                  fontSize: 9, padding: "1px 5px", borderRadius: 999,
                  background: "rgba(220,38,38,0.10)", color: "#dc2626",
                  fontFamily: "var(--lys-font-mono)",
                }}>
                  ✗ {d}
                </span>
              ))}
              {(f.exceptions ?? []).map((e) => (
                <span key={e} style={{
                  fontSize: 9, padding: "1px 5px", borderRadius: 999,
                  background: "rgba(16,185,129,0.10)", color: "var(--lys-accent)",
                  fontFamily: "var(--lys-font-mono)",
                }}>
                  ✓ {e}
                </span>
              ))}
            </div>
            <div style={{ fontSize: 9.5, color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)" }}>
              {f.MIC_shift} · {f.citation}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
