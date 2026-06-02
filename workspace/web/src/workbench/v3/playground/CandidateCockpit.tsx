/**
 * CandidateCockpit — the dense, aligned "vitals" hero for the loaded
 * candidate. Sits at the very top of the Chemistry column so a chemist
 * sees the molecule + every fast real-engine readout AT A GLANCE, instead
 * of a tiny molecule stranded in white space.
 *
 * Pulls the FAST engines live on SMILES change (activity classifier,
 * SAScore synthesizability, composite score) and shows them as a compact
 * vitals strip with the 2D structure. The heavy engines (dock, ADMET panel,
 * IP) stay in their own cards below — this is the at-a-glance layer.
 *
 * Real models, honest provenance, zero dead space.
 */
import { useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { Mol2DThumb } from "./Mol2DThumb";
import { StatTile, MetricBar, ProvenanceBadge, bandColor } from "./uiPrimitives";

interface Props {
  apiBase: string;
  smiles: string | null;
  pathogen: string | null;
}

interface Vitals {
  activity?: { prob: number; band: string } | null;
  synth?: { sa: number; band: string; ease: number; drivers: string[] } | null;
  score?: { composite: number } | null;
}

const TEAL = { fg: "#0d9488", fgDeep: "#0f766e", border: "rgba(13,148,136,0.25)" } as const;

export function CandidateCockpit({ apiBase, smiles, pathogen }: Props) {
  const [v, setV] = useState<Vitals>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!smiles) { setV({}); return; }
    let cancelled = false;
    setLoading(true);
    const enc = encodeURIComponent(smiles);
    const jget = (u: string) => fetch(u).then(r => r.ok ? r.json() : null).catch(() => null);
    Promise.all([
      jget(`${apiBase}/workbench/chem/activity?smiles=${enc}`),
      jget(`${apiBase}/workbench/chem/synthesizability?smiles=${enc}`),
      fetch(`${apiBase}/workbench/score`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ smiles, target_pathogen: pathogen || "MRSA" }),
      }).then(r => r.ok ? r.json() : null).catch(() => null),
    ]).then(([act, syn, sc]) => {
      if (cancelled) return;
      setV({
        activity: act?.activity_probability != null
          ? { prob: act.activity_probability, band: act.band } : null,
        synth: syn?.sa_score != null
          ? { sa: syn.sa_score, band: syn.band, ease: syn.synth_ease,
              drivers: syn.difficulty_drivers || [] } : null,
        score: sc?.composite != null ? { composite: sc.composite } : null,
      });
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [apiBase, smiles, pathogen]);

  if (!smiles) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 10,
        padding: "14px 16px", color: "var(--lys-text-faint)", fontSize: 12 }}>
        <Activity size={16} style={{ opacity: 0.5 }} />
        <span>Load a candidate to see its live vitals — predicted activity,
          synthesizability, and composite score, computed on the spot.</span>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: 12, padding: "12px 14px",
      alignItems: "stretch", background: "var(--lys-surface)",
      borderBottom: `1px solid ${TEAL.border}` }}>
      {/* structure */}
      <Mol2DThumb apiBase={apiBase} smiles={smiles} w={140} h={108}
        accent={TEAL.fg} caption="candidate" />

      {/* vitals */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column",
        gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, fontFamily: "var(--lys-font-mono)",
            letterSpacing: "0.06em", textTransform: "uppercase",
            color: TEAL.fgDeep, fontWeight: 700 }}>candidate vitals</span>
          <ProvenanceBadge real label="live engines" />
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)", maxWidth: 220, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{smiles}</span>
        </div>

        {/* big-number vitals row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8 }}>
          <StatTile label="composite reward"
            value={v.score ? v.score.composite.toFixed(2) : (loading ? "…" : "—")}
            color={v.score ? bandColor(v.score.composite >= 0.6 ? "good"
              : v.score.composite >= 0.45 ? "moderate" : "poor") : undefined} />
          <StatTile label="antibacterial prior"
            value={v.activity ? v.activity.prob.toFixed(2) : (loading ? "…" : "—")}
            sub={v.activity?.band}
            color={v.activity ? bandColor(v.activity.band) : undefined}
            title="Trained classifier — structural similarity to known antibacterials (a prior, not an MIC)" />
          <StatTile label="synth accessibility"
            value={v.synth ? v.synth.sa.toFixed(1) : (loading ? "…" : "—")}
            sub={v.synth?.band}
            color={v.synth ? bandColor(v.synth.band) : undefined}
            title="SAScore (Ertl & Schuffenhauer): 1 easy → 10 hard" />
        </div>

        {/* synthesizability ease bar + drivers */}
        {v.synth && (
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <MetricBar label="ease of synthesis" value={v.synth.ease}
              band={v.synth.band} valueLabel={`${(v.synth.ease * 100).toFixed(0)}%`} />
            {v.synth.drivers.length > 0 && (
              <div style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)" }}>
                drivers: {v.synth.drivers.join(" · ")}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
