/**
 * ADMETObservatoryCard — Service 3 frontend: 5-axis PK panel.
 *
 * Same agentic pattern as Synthesis + IP/FTO: the card doesn't just
 * grade a candidate — it identifies the worst-scoring axis and the
 * agent designs ONE structural fix that proves an improvement on that
 * axis, ready to apply with one tap.
 *
 * Backend: /workbench/chem/admet/* (chem_admet.py).
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { Activity, RefreshCw, Trash2, Sparkles, ArrowRight } from "lucide-react";
import { Mol2DThumb } from "./Mol2DThumb";
import { isLikelyNonDrug } from "./chemUtils";

// ── Type contract — mirrors chem_admet.py output ─────────────────────
interface AxisDetail {
  score: number;
  band: "good" | "moderate" | "poor" | "unknown";
  notes?: string[];
  // A
  f_percent?: number;
  caco2_papp_1e6?: number;
  hia_percent?: number;
  veber_ok?: boolean;
  // D
  ppb_percent?: number;
  free_fraction_percent?: number;
  bbb_class?: "permeable" | "limited";
  bbb_permeable?: boolean;
  vd_lpkg?: number;          // heuristic
  vd_percentile?: number;    // real model (vs approved drugs)
  // M
  cyp3a4_inhib_risk?: number;
  cyp2d6_inhib_risk?: number;
  cyp2c9_inhib_risk?: number;
  hlm_stability?: number;
  hlm_band?: "stable" | "moderate" | "labile";
  // E
  clearance_mlminkg?: number;       // heuristic
  clearance_percentile?: number;    // real model
  renal_fraction?: number;
  t_half_hours?: number;            // heuristic
  t_half_percentile?: number;       // real model (vs approved drugs)
  dose_interval?: string;
  // T
  herg_risk?: string; hepatotox_risk?: string; ames_risk?: string;
  skin_sens_risk?: string;
}
interface ADMETFix {
  variant_smiles: string;
  modification: string;
  rationale: string;
  axis: "A" | "D" | "M" | "E" | "T";
  axis_label: string;
  score_before: number; score_after: number;
  composite_before: number; composite_after: number;
  improved: boolean;
  axes_after?: Record<string, number>;
}
interface ADMETPanel {
  smiles: string;
  physchem?: Record<string, number> | null;
  axes: Record<string, AxisDetail>;
  composite: number;
  tier: "advance" | "promising" | "early" | "weak" | "n/a";
  worst: { axis: string | null; score: number; band: string };
  fix?: ADMETFix | null;
  non_drug_reason?: string | null;
  source?: "admet-ai" | "heuristic";
  artifact_id?: string | null;
}
interface SavedPanel {
  id: string; title: string | null; payload: ADMETPanel;
}

interface Props {
  apiBase: string;
  sessionId: string | null;
  smiles: string | null;
  onLoad?: (smiles: string) => void;
}

// Cobalt/teal "vitals" accent — distinguishes this service from
// amber-synthesis, slate-IP, lavender-resistance.
const COBALT = {
  bg: "rgba(8,145,178,0.06)",
  bgStrong: "rgba(8,145,178,0.14)",
  border: "rgba(8,145,178,0.28)",
  fg: "#0891b2",
  fgDeep: "#0e7490",
} as const;

const ACT = { bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.4)",
  fg: "#059669", fgDeep: "#047857" } as const;

const BAND_COLOR: Record<string, string> = {
  good: "#16a34a", moderate: "#d97706", poor: "#dc2626",
  unknown: "#94a3b8", "n/a": "#94a3b8",
};
const TIER_COLOR: Record<string, string> = {
  advance: "#16a34a", promising: "#65a30d",
  early: "#d97706", weak: "#dc2626", "n/a": "#94a3b8",
};
const AXIS_NAMES: Record<string, string> = {
  A: "Absorption", D: "Distribution",
  M: "Metabolism", E: "Excretion", T: "Toxicity",
};

export function ADMETObservatoryCard({ apiBase, sessionId, smiles, onLoad }: Props) {
  const [panel, setPanel] = useState<ADMETPanel | null>(null);
  const [saved, setSaved] = useState<SavedPanel[]>([]);
  const [computing, setComputing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const refreshSaved = useCallback(async (): Promise<SavedPanel[]> => {
    if (!sessionId) return [];
    try {
      const r = await fetch(`${apiBase}/workbench/chem/admet/panels?session_id=${sessionId}`);
      if (!r.ok) return [];
      const d = await r.json();
      setSaved(d.items ?? []);
      return d.items ?? [];
    } catch { return []; }
  }, [apiBase, sessionId]);

  useEffect(() => { void refreshSaved(); }, [refreshSaved]);
  useEffect(() => () => { if (pollRef.current) window.clearTimeout(pollRef.current); }, []);

  function runPanel() {
    if (!smiles || !sessionId) return;
    setError(null);
    setComputing(true);
    window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
      detail: { text: `/wf admet_panel ${JSON.stringify({ smiles, session_id: sessionId })}` },
    }));
    let elapsed = 0;
    const poll = async () => {
      elapsed += 2800;
      const items = await refreshSaved();
      const fresh = items.find(it => it.payload.smiles === smiles);
      if (fresh) {
        setPanel({ ...fresh.payload, artifact_id: fresh.id });
        setComputing(false);
        return;
      }
      if (elapsed > 45000) { setComputing(false); return; }
      pollRef.current = window.setTimeout(() => { void poll(); }, 2800);
    };
    pollRef.current = window.setTimeout(() => { void poll(); }, 3200);
  }

  async function deletePanel(id: string) {
    await fetch(`${apiBase}/workbench/chem/admet/panels/${id}`, { method: "DELETE" });
    await refreshSaved();
    if (panel?.artifact_id === id) setPanel(null);
  }

  function applyFix(smi: string) {
    if (onLoad) onLoad(smi);
    else window.dispatchEvent(new CustomEvent("lysos:auto-slash",
      { detail: { text: `/load ${smi}` } }));
  }

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "transparent", overflow: "hidden", fontFamily: "var(--lys-font-body)",
    }}>
      <div style={{
        padding: "6px 10px", display: "flex", alignItems: "center", gap: 6,
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
        textTransform: "uppercase", color: COBALT.fgDeep,
        borderBottom: `1px solid ${COBALT.border}`,
      }}>
        <Activity size={11} style={{ color: COBALT.fg }} />
        <span>admet observatory · 5-axis pk</span>
        <span style={{ flex: 1 }} />
        {saved.length > 0 && (
          <span style={{ padding: "1px 6px", borderRadius: 999, background: COBALT.bgStrong,
            border: `1px solid ${COBALT.border}`, color: COBALT.fgDeep, fontSize: 9 }}>
            {saved.length} saved</span>
        )}
        <button type="button" onClick={() => void refreshSaved()}
          style={{ border: 0, background: "transparent", cursor: "pointer",
            padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      <div style={{
        padding: "8px 10px", display: "flex", alignItems: "center", gap: 8,
        borderBottom: "1px solid rgba(0,0,0,0.05)",
      }}>
        <button type="button" onClick={runPanel} disabled={computing || !smiles}
          style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "5px 11px", borderRadius: 5, border: 0,
            background: !smiles ? "rgba(0,0,0,0.05)" : COBALT.fg,
            color: !smiles ? "var(--lys-text-faint)" : "white",
            fontSize: 11, fontWeight: 600, cursor: !smiles || computing ? "not-allowed" : "pointer",
          }}>
          <Activity size={12} />
          {computing ? "Computing panel + designing fix…" : "Run ADMET panel"}
        </button>
        <span style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
          {computing ? "5-axis predictions → agent designs a fix for the worst axis"
            : smiles ? smiles : "no candidate loaded"}
        </span>
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!panel && !computing && (
          <Empty msg="Run an ADMET panel — five PK axes scored from RDKit physchem, with the agent designing a structural fix for the weakest one. Ready to apply in one tap." />
        )}
        {computing && !panel && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 20,
            textAlign: "center", color: COBALT.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Computing the 5-axis ADMET panel + the agent's fix —
              streaming in chat.</div>
          </div>
        )}

        {panel && <PanelView apiBase={apiBase} panel={panel} onApply={applyFix} />}

        {saved.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
              letterSpacing: "0.06em", textTransform: "uppercase",
              color: "var(--lys-text-faint)", padding: "0 2px 4px" }}>saved admet panels</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {saved.map((p) => {
                const nd = p.payload.non_drug_reason ?? isLikelyNonDrug(p.payload.smiles);
                const isStale = !!nd;
                const dotCol = isStale ? "#94a3b8"
                  : (TIER_COLOR[p.payload.tier] ?? "#9ca3af");
                return (
                  <div key={p.id} style={{
                    display: "flex", alignItems: "center", gap: 6, padding: "5px 7px",
                    borderRadius: 5,
                    background: panel?.artifact_id === p.id ? COBALT.bgStrong : COBALT.bg,
                    border: `1px solid ${COBALT.border}`,
                    opacity: isStale ? 0.55 : 1,
                  }}>
                    <span style={{ width: 7, height: 7, borderRadius: 7, flexShrink: 0,
                      background: dotCol }} />
                    <button type="button"
                      onClick={() => setPanel({ ...p.payload, artifact_id: p.id })}
                      style={{ flex: 1, minWidth: 0, textAlign: "left", border: 0,
                        background: "transparent", cursor: "pointer", padding: 0,
                        display: "flex", alignItems: "baseline", gap: 6 }}>
                      {isStale && (
                        <span title={nd ?? ""} style={{
                          fontSize: 8, fontFamily: "var(--lys-font-mono)",
                          padding: "1px 5px", borderRadius: 3, flexShrink: 0,
                          background: "rgba(148,163,184,0.20)",
                          color: "#64748b", fontWeight: 700,
                        }}>n/a</span>
                      )}
                      <span style={{ fontSize: 10.5, fontWeight: 600,
                        color: "var(--lys-text)", whiteSpace: "nowrap",
                        overflow: "hidden", textOverflow: "ellipsis" }}>
                        {p.title || "ADMET"}
                      </span>
                    </button>
                    <button type="button" onClick={() => void deletePanel(p.id)}
                      style={{ border: 0, background: "transparent", cursor: "pointer",
                        padding: 0, color: "var(--lys-text-faint)" }}>
                      <Trash2 size={11} />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PanelView({ apiBase, panel, onApply }: {
  apiBase: string; panel: ADMETPanel; onApply: (s: string) => void;
}) {
  // Client-side gate — catches old saved panels for non-drug inputs.
  const heuristicNonDrug = panel.non_drug_reason ?? isLikelyNonDrug(panel.smiles);
  if (heuristicNonDrug) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10,
        padding: 12, alignItems: "center", textAlign: "center",
        background: COBALT.bg, border: `1px solid ${COBALT.border}`,
        borderRadius: 7 }}>
        <Mol2DThumb apiBase={apiBase} smiles={panel.smiles}
          w={160} h={120} caption="candidate" accent={COBALT.fg} />
        <div style={{ fontSize: 11, fontWeight: 700, color: COBALT.fgDeep,
          lineHeight: 1.3 }}>ADMET panel not applicable</div>
        <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)",
          lineHeight: 1.45, maxWidth: 360 }}>
          {heuristicNonDrug}
        </div>
      </div>
    );
  }

  const tierCol = TIER_COLOR[panel.tier] ?? "#9ca3af";
  const fix = panel.fix;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Structure-forward header — candidate + composite + tier */}
      <div style={{ border: `1px solid ${COBALT.border}`, borderRadius: 7,
        background: COBALT.bg, padding: 8,
        display: "flex", alignItems: "center", gap: 10 }}>
        <Mol2DThumb apiBase={apiBase} smiles={panel.smiles} w={120} h={90}
          caption="candidate" accent={tierCol} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6,
            fontFamily: "var(--lys-font-mono)" }}>
            <span style={{ fontSize: 18, fontWeight: 700, color: tierCol,
              lineHeight: 1 }}>{panel.composite.toFixed(2)}</span>
            <span style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
              textTransform: "uppercase", letterSpacing: "0.05em" }}>
              composite · {panel.tier}
            </span>
          </div>
          <div style={{ fontSize: 9.5, color: "var(--lys-text-faint)", marginTop: 4,
            fontFamily: "var(--lys-font-mono)" }}>
            weakest: <span style={{ color: BAND_COLOR[panel.worst.band] ?? "#9ca3af",
              fontWeight: 700 }}>
              {panel.worst.axis} ({panel.worst.score.toFixed(2)} · {panel.worst.band})
            </span>
          </div>
          {panel.physchem && (
            <div style={{ fontSize: 9, color: "var(--lys-text-faint)",
              marginTop: 4, fontFamily: "var(--lys-font-mono)" }}>
              MW {panel.physchem.mw.toFixed(0)} · LogP {panel.physchem.logp.toFixed(2)} ·
              {" "}TPSA {panel.physchem.tpsa.toFixed(0)} · RotB {panel.physchem.rotb}
            </div>
          )}
        </div>
      </div>

      {/* Agent fix hero — original ↔ fix structures + axis delta */}
      {fix && fix.improved && (
        <div style={{ border: `1.5px solid ${ACT.border}`, borderRadius: 7,
          background: ACT.bg, padding: "8px 9px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5,
            fontSize: 10, fontWeight: 700, color: ACT.fgDeep, marginBottom: 6 }}>
            <Sparkles size={12} />
            <span>Agent designed an ADMET-fix analog ({fix.axis_label})</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
            gap: 6, padding: "2px 0 6px" }}>
            <Mol2DThumb apiBase={apiBase} smiles={panel.smiles} w={130} h={100}
              caption="original" accent="rgba(71,85,105,0.35)" />
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center",
              gap: 2 }}>
              <ArrowRight size={18} style={{ color: ACT.fg }} />
              <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                color: ACT.fg, fontWeight: 700 }}>
                {fix.score_before.toFixed(2)}→{fix.score_after.toFixed(2)}
              </span>
            </div>
            <Mol2DThumb apiBase={apiBase} smiles={fix.variant_smiles} w={130} h={100}
              caption="fix" accent={ACT.fg} />
          </div>
          <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)", lineHeight: 1.4,
            textAlign: "center" }}>
            <strong style={{ color: ACT.fgDeep }}>{fix.modification}</strong>
          </div>
          <div style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)", marginTop: 4, textAlign: "center" }}>
            composite {fix.composite_before.toFixed(2)} → {fix.composite_after.toFixed(2)}
          </div>
          <button type="button" onClick={() => onApply(fix.variant_smiles)}
            style={{ marginTop: 6, width: "100%", padding: "6px 0", border: 0,
              borderRadius: 5, background: ACT.fg, color: "white",
              fontSize: 10.5, fontWeight: 700, cursor: "pointer" }}>
            Apply this fix → load + re-panel
          </button>
        </div>
      )}
      {fix && !fix.improved && (
        <div style={{ fontSize: 9.5, color: "#16a34a", background: "rgba(22,163,74,0.06)",
          border: "1px solid rgba(22,163,74,0.22)", borderRadius: 4, padding: "4px 7px" }}>
          Already healthy across all five axes — no fix needed.
        </div>
      )}

      {/* 5-axis bars — the visual core */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {(["A", "D", "M", "E", "T"] as const).map(k => (
          <AxisRow key={k} axis={k} detail={panel.axes[k] ?? null}
            isWorst={panel.worst.axis === k} />
        ))}
      </div>
    </div>
  );
}

function AxisRow({ axis, detail, isWorst }: {
  axis: "A" | "D" | "M" | "E" | "T";
  detail: AxisDetail | null; isWorst: boolean;
}) {
  if (!detail) return null;
  const col = BAND_COLOR[detail.band] ?? "#9ca3af";
  const pct = Math.round(detail.score * 100);
  // Per-axis headline value
  let headline = "";
  if (axis === "A") headline = `F% ${detail.f_percent ?? "—"} · HIA ${detail.hia_percent ?? "—"}`;
  else if (axis === "D") headline = `PPB ${detail.ppb_percent ?? "—"}% · BBB ${detail.bbb_class ?? "—"}`;
  else if (axis === "M") headline = `HLM ${detail.hlm_band ?? "—"} · CYP3A4 ${(detail.cyp3a4_inhib_risk ?? 0).toFixed(2)}`;
  else if (axis === "E") headline = detail.t_half_hours != null
    ? `t½ ${detail.t_half_hours}h · ${detail.dose_interval ?? "—"}`
    : `t½ ${detail.t_half_percentile ?? "—"}ᵖᶜ · ${detail.dose_interval ?? "—"}`;
  else if (axis === "T") headline = `hERG ${detail.herg_risk ?? "—"} · hepato ${detail.hepatotox_risk ?? "—"}`;
  return (
    <div title={(detail.notes ?? []).join(" · ") || undefined}
      style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "5px 8px", borderRadius: 6,
        background: isWorst ? "rgba(220,38,38,0.06)" : COBALT.bg,
        border: `1px solid ${isWorst ? "rgba(220,38,38,0.30)" : COBALT.border}`,
      }}>
      <span style={{
        width: 18, height: 18, borderRadius: 4, background: COBALT.fg,
        color: "white", fontSize: 11, fontWeight: 700,
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0, fontFamily: "var(--lys-font-mono)",
      }}>{axis}</span>
      <div style={{ minWidth: 90, flexShrink: 0 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--lys-text)",
          lineHeight: 1.2 }}>{AXIS_NAMES[axis]}</div>
        <div style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
          color: col, fontWeight: 700 }}>{detail.band}</div>
      </div>
      {/* Bar */}
      <div style={{ flex: 1, minWidth: 60, height: 8, borderRadius: 4,
        background: "rgba(0,0,0,0.06)", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: col,
          transition: "width 0.3s" }} />
      </div>
      <span style={{ fontSize: 10, fontFamily: "var(--lys-font-mono)",
        color: col, fontWeight: 700, minWidth: 32, textAlign: "right",
        flexShrink: 0 }}>{detail.score.toFixed(2)}</span>
      <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", flex: "0 1 auto",
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        maxWidth: 200 }}>{headline}</span>
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "center",
      justifyContent: "center", padding: 20, textAlign: "center",
      color: "var(--lys-text-faint)", fontSize: 11 }}>
      <Activity size={22} style={{ opacity: 0.4 }} />
      <div>{msg}</div>
    </div>
  );
}
