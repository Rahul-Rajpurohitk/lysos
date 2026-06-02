/**
 * ResistomeCard — the AMR population/resistance-landscape view.
 *
 * Population-level complement to the per-molecule resistance map: for the
 * selected pathogen, which drug classes are already resistance-SATURATED in
 * the clinic vs which still have HEADROOM, plus the cross-class mutation
 * hotspots a chemist must not depend on. Real CARD data.
 *
 * Backend: /workbench/chem/resistome/{pathogen} (chem_resistome.py).
 */
import { useEffect, useState } from "react";
import { ShieldAlert, RefreshCw } from "lucide-react";
import { StatTile, MetricBar, BandPill, ProvenanceBadge, SectionLabel, EmptyState }
  from "./uiPrimitives";

interface ClassRow {
  drug_class: string;
  n_determinants: number;
  n_targets: number;
  resistance_pressure: number;
  band: "saturated" | "pressured" | "headroom";
  top_determinants: { target: string; mutation: string; frequency: string; note: string }[];
}
interface Hotspot {
  pdb_id: string; target: string; position: number; wt: string;
  n_classes_defeated: number; classes: string[]; max_clinical_freq_weight: number;
}
interface Resistome {
  pathogen: string; scope: string;
  n_targets: number; n_drug_classes: number; n_determinants: number;
  n_saturated_classes: number;
  drug_class_landscape: ClassRow[];
  mutation_hotspots: Hotspot[];
  summary: string; source: string;
}
interface Props { apiBase: string; pathogen: string | null; }

const ROSE = { fg: "#e11d48", fgDeep: "#9f1239", border: "rgba(225,29,72,0.28)" } as const;

export function ResistomeCard({ apiBase, pathogen }: Props) {
  const [data, setData] = useState<Resistome | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    const p = pathogen || "MRSA";
    let cancelled = false;
    setLoading(true);
    fetch(`${apiBase}/workbench/chem/resistome/${encodeURIComponent(p)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setData(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [apiBase, pathogen]);

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", overflow: "hidden", fontFamily: "var(--lys-font-body)" }}>
      {/* header */}
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: ROSE.fgDeep,
        borderBottom: `1px solid ${ROSE.border}` }}>
        <ShieldAlert size={11} style={{ color: ROSE.fg }} />
        <span>resistome · AMR landscape</span>
        <span style={{ flex: 1 }} />
        <ProvenanceBadge real label="CARD" />
        {loading && <RefreshCw size={11} style={{ animation: "spin 1s linear infinite",
          color: "var(--lys-text-faint)" }} />}
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!data && !loading && (
          <EmptyState icon={<ShieldAlert size={22} style={{ opacity: 0.4 }} />}
            msg="The clinical resistance landscape for this pathogen — which drug classes are already saturated with resistance vs which still have headroom, from real CARD data." />
        )}
        {data && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {/* rollup tiles */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 5 }}>
              <StatTile label="targets" value={data.n_targets} />
              <StatTile label="classes" value={data.n_drug_classes} />
              <StatTile label="determinants" value={data.n_determinants} />
              <StatTile label="saturated" value={data.n_saturated_classes}
                color={data.n_saturated_classes > 0 ? "#dc2626" : "#16a34a"} />
            </div>

            <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)", lineHeight: 1.45 }}>
              {data.summary}
            </div>

            {/* drug-class pressure bars — the strategic core */}
            <div>
              <SectionLabel color={ROSE.fgDeep}>drug-class resistance pressure</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {data.drug_class_landscape.map((c) => (
                  <div key={c.drug_class}
                    onClick={() => setExpanded(expanded === c.drug_class ? null : c.drug_class)}
                    style={{ cursor: "pointer", padding: "6px 8px", borderRadius: 6,
                      border: "1px solid var(--lys-border)", background: "var(--lys-surface)" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6,
                      marginBottom: 4 }}>
                      <span style={{ fontSize: 10.5, fontWeight: 700,
                        color: "var(--lys-text)" }}>{c.drug_class.replace(/_/g, " ")}</span>
                      <BandPill band={c.band} />
                      <span style={{ flex: 1 }} />
                      <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                        color: "var(--lys-text-faint)" }}>
                        {c.n_determinants} det · {c.n_targets} tgt</span>
                    </div>
                    <MetricBar label="clinical pressure" value={c.resistance_pressure}
                      band={c.band} />
                    {expanded === c.drug_class && (
                      <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 3 }}>
                        {c.top_determinants.map((m, i) => (
                          <div key={i} style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                            color: "var(--lys-text-dim)", display: "flex", gap: 6 }}>
                            <span style={{ color: ROSE.fg, fontWeight: 700, minWidth: 54 }}>
                              {m.mutation}</span>
                            <span style={{ color: "var(--lys-text-faint)" }}>{m.frequency}</span>
                            <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden",
                              textOverflow: "ellipsis" }}>{m.note}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* cross-class hotspots */}
            {data.mutation_hotspots.length > 0 && (
              <div>
                <SectionLabel color={ROSE.fgDeep}>cross-class mutation hotspots</SectionLabel>
                <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                  {data.mutation_hotspots.map((h, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "baseline", gap: 6,
                      padding: "3px 7px", borderRadius: 4, fontSize: 9.5,
                      background: "rgba(225,29,72,0.05)", border: `1px solid ${ROSE.border}` }}>
                      <span style={{ fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                        color: ROSE.fg }}>{h.wt}{h.position}</span>
                      <span style={{ fontSize: 8.5, color: "var(--lys-text-faint)" }}>
                        {h.target}</span>
                      <span style={{ flex: 1 }} />
                      <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                        color: ROSE.fgDeep, fontWeight: 700 }}>
                        defeats {h.n_classes_defeated} classes</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", textAlign: "right" }}>
              {data.source}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
