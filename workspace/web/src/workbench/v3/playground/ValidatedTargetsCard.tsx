/**
 * ValidatedTargetsCard — Knowledge-side counterpart to the 3D Theater
 * target picker. Lists the curated PDB targets per pathogen with full
 * metadata: mechanism, clinical context, drug-class examples, default
 * status. Reads from /workbench/chem/targets/{pathogen}.
 *
 * Click a target → could potentially fire an event to switch the 3D
 * theater's selection (future work; for now informational).
 */
import { useEffect, useState } from "react";
import { Crosshair } from "lucide-react";

interface CuratedTarget {
  pdb_id: string;
  name: string;
  short_name: string;
  mechanism: string;
  clinical_note: string;
  drug_class_examples: string[];
  preferred_default: boolean;
}

interface Props {
  apiBase: string;
  pathogen: string;
}

export function ValidatedTargetsCard({ apiBase, pathogen }: Props) {
  const [targets, setTargets] = useState<CuratedTarget[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/chem/targets/${encodeURIComponent(pathogen)}`);
        if (!r.ok) { setTargets([]); return; }
        const d = await r.json();
        if (!cancelled) setTargets(d.targets || []);
      } catch {
        if (!cancelled) setTargets([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [apiBase, pathogen]);

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
        <Crosshair size={11} style={{ color: "#0891b2" }} />
        <span>validated targets · {pathogen}</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 9 }}>
          {targets.length}
        </span>
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: 6, display: "flex",
        flexDirection: "column", gap: 5 }}>
        {loading && (
          <div style={{ textAlign: "center", padding: 8, fontSize: 10,
            color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)" }}>
            loading…
          </div>
        )}
        {!loading && targets.length === 0 && (
          <div style={{ textAlign: "center", padding: 12, fontSize: 10,
            color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)" }}>
            no curated targets for this pathogen
          </div>
        )}
        {targets.map((t) => (
          <div key={t.pdb_id}
            title={t.clinical_note}
            style={{
              padding: "6px 8px", borderRadius: 5,
              background: t.preferred_default ? "rgba(8,145,178,0.04)" : "rgba(0,0,0,0.01)",
              border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
              borderLeft: `3px solid ${t.preferred_default ? "#0891b2" : "rgba(0,0,0,0.10)"}`,
              display: "flex", flexDirection: "column", gap: 3,
            }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 700,
                fontFamily: "var(--lys-font-body)", color: "var(--lys-text)" }}>
                {t.short_name}
              </span>
              <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 9,
                color: "var(--lys-text-faint)" }}>
                {t.pdb_id}
              </span>
              {t.preferred_default && (
                <span style={{
                  fontSize: 8, padding: "0 5px", borderRadius: 999,
                  background: "rgba(8,145,178,0.10)", color: "#0891b2",
                  fontWeight: 700, marginLeft: "auto",
                }}>default</span>
              )}
            </div>
            <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)",
              fontFamily: "var(--lys-font-body)", lineHeight: 1.4 }}>
              {t.name}
            </div>
            <div style={{ fontSize: 9, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)" }}>
              {t.mechanism}
            </div>
            {t.drug_class_examples.length > 0 && (
              <div style={{ display: "flex", gap: 3, flexWrap: "wrap", marginTop: 2 }}>
                {t.drug_class_examples.map((d) => (
                  <span key={d} style={{
                    fontSize: 8.5, padding: "1px 5px", borderRadius: 999,
                    background: "rgba(0,0,0,0.04)",
                    color: "var(--lys-text-dim)",
                    fontFamily: "var(--lys-font-mono)",
                  }}>{d}</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
