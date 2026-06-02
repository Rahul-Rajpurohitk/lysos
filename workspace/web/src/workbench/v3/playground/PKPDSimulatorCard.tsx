/**
 * PKPDSimulatorCard — "does the dose actually cure it?"
 *
 * The layer a generic chem platform never has: turn a molecule + a dosing
 * regimen into the pharmacodynamic answer. Live regimen controls drive a
 * one-compartment population-PK simulation; the steady-state concentration-
 * time curve is drawn with the MIC line and the shaded time-above-MIC band;
 * the governing PK/PD index (chosen by antibiotic class) reads out as
 * attained / stasis / missed; and a Monte-Carlo Probability-of-Target-
 * Attainment curve gives the PK/PD susceptibility breakpoint a clinical
 * micro lab would report.
 *
 * Everything is interactive — change the dose, interval, route, infusion
 * time, class, or MIC and the curves + PTA re-compute live (debounced).
 * Backend: /workbench/chem/pkpd/*.
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { Activity, RefreshCw, Syringe } from "lucide-react";
import { StatTile, BandPill, ProvenanceBadge, SectionLabel, EmptyState } from "./uiPrimitives";

const TEAL = { fg: "#0d9488", fgDeep: "#0f766e", border: "rgba(13,148,136,0.28)",
  bg: "rgba(13,148,136,0.06)" } as const;

interface ClassRow {
  key: string; label: string; index: string; index_raw: string;
  target_stasis: number; target_cidal: number; cl_l_h: number; v_l: number;
  fu: number; default_route: string; note: string; examples: string[];
}
interface CurvePt { t: number; total: number; free: number; }
interface PtaPt { mic: number; pta: number; }
interface SimResult {
  smiles: string; pathogen: string; drug_class: string; class_label: string;
  pk: { cl_l_h: number; v_l: number; ke_h: number; thalf_h: number;
        fu: number; fu_source: string; ka_h: number };
  exposure: { cmax_mg_l: number; cmin_mg_l: number; auc24_mg_h_l: number; fauc24_mg_h_l: number };
  index: string; index_label: string;
  target_stasis: number; target_cidal: number;
  mic_mg_l: number | null; mic_source: string; index_at_mic: number | null;
  attained_cidal: boolean; attained_stasis: boolean; band: string;
  curve: CurvePt[]; pta_curve: PtaPt[]; pkpd_breakpoint_mg_l: number | null;
  n_patients: number; class_note: string; class_examples: string[];
  elapsed_s: number; engine: string; provenance: string;
}
interface Props {
  apiBase: string; smiles: string | null; pathogen: string | null;
  sessionId?: string | null;
}

const INTERVALS = [6, 8, 12, 24];
const ROUTES: { key: string; label: string }[] = [
  { key: "infusion", label: "IV infusion" },
  { key: "bolus", label: "IV bolus" },
  { key: "oral", label: "Oral" },
];
const BAND_LABEL: Record<string, string> = {
  "attained-cidal": "cidal target met", "attained-stasis": "stasis only",
  "not-attained": "target missed", "no-mic": "no MIC",
};
const BAND_WORD: Record<string, string> = {
  "attained-cidal": "strong", "attained-stasis": "moderate",
  "not-attained": "poor", "no-mic": "n/a",
};

export function PKPDSimulatorCard({ apiBase, smiles, pathogen, sessionId }: Props) {
  const [classes, setClasses] = useState<ClassRow[]>([]);
  const [drugClass, setDrugClass] = useState<string>("");
  const [dose, setDose] = useState(1000);
  const [interval, setIntervalH] = useState(8);
  const [route, setRoute] = useState("infusion");
  const [infusionH, setInfusionH] = useState(1);
  const [mic, setMic] = useState<string>("");   // blank → estimate
  const [result, setResult] = useState<SimResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const debRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load the PK/PD class reference once; seed the default from the pathogen.
  useEffect(() => {
    let live = true;
    fetch(`${apiBase}/workbench/chem/pkpd/classes?pathogen=${encodeURIComponent(pathogen || "")}`)
      .then((r) => r.json())
      .then((d) => {
        if (!live) return;
        setClasses(d.classes || []);
        setDrugClass((prev) => prev || d.default_class || (d.classes?.[0]?.key ?? ""));
      })
      .catch(() => {});
    return () => { live = false; };
  }, [apiBase, pathogen]);

  const simulate = useCallback(async () => {
    if (!smiles || !drugClass) return;
    setError(null); setRunning(true);
    abortRef.current?.abort();
    const ac = new AbortController(); abortRef.current = ac;
    try {
      const body: Record<string, unknown> = {
        smiles, pathogen: pathogen || "MRSA", drug_class: drugClass,
        regimen: { dose_mg: dose, interval_h: interval, route,
          infusion_h: route === "infusion" ? infusionH : 0, weight_kg: 70 },
        n_patients: 1500, save: true, session_id: sessionId || undefined,
      };
      const micN = parseFloat(mic);
      if (!Number.isNaN(micN) && micN > 0) body.mic_mg_l = micN;
      const r = await fetch(`${apiBase}/workbench/chem/pkpd/simulate`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(body), signal: ac.signal,
      });
      if (!r.ok) { setError(`simulation failed (HTTP ${r.status})`); return; }
      setResult(await r.json());
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("simulator error");
    } finally { setRunning(false); }
  }, [apiBase, smiles, pathogen, drugClass, dose, interval, route, infusionH, mic, sessionId]);

  // Live, debounced re-simulate whenever any input changes.
  useEffect(() => {
    if (!smiles || !drugClass) { setResult(null); return; }
    if (debRef.current) clearTimeout(debRef.current);
    debRef.current = setTimeout(simulate, 350);
    return () => { if (debRef.current) clearTimeout(debRef.current); };
  }, [simulate, smiles, drugClass]);

  const cls = classes.find((c) => c.key === drugClass);

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", overflow: "hidden", fontFamily: "var(--lys-font-body)" }}>
      {/* header */}
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: TEAL.fgDeep,
        borderBottom: `1px solid ${TEAL.border}` }}>
        <Activity size={11} style={{ color: TEAL.fg }} />
        <span>PK/PD simulator · target attainment</span>
        <span style={{ flex: 1 }} />
        {running && <RefreshCw size={10} style={{ animation: "spin 1s linear infinite", color: TEAL.fg }} />}
        <ProvenanceBadge real label="popPK + MC-PTA" />
      </div>

      {/* regimen control toolbar */}
      <div style={{ padding: "7px 10px", display: "flex", flexWrap: "wrap",
        alignItems: "center", gap: 7, borderBottom: "1px solid rgba(0,0,0,0.05)" }}>
        {/* class */}
        <select value={drugClass} onChange={(e) => setDrugClass(e.target.value)}
          style={selStyle} title="antibiotic class → governing PK/PD index">
          {classes.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        {/* dose */}
        <label style={ctrlWrap}>
          <span style={ctrlLbl}>dose</span>
          <input type="number" value={dose} min={50} step={50}
            onChange={(e) => setDose(Math.max(1, Number(e.target.value) || 0))}
            style={{ ...numStyle, width: 56 }} /><span style={unitStyle}>mg</span>
        </label>
        {/* interval chips */}
        <div style={{ display: "inline-flex", gap: 2 }}>
          {INTERVALS.map((iv) => (
            <button key={iv} type="button" onClick={() => setIntervalH(iv)}
              style={chip(interval === iv)}>q{iv}h</button>
          ))}
        </div>
        {/* route */}
        <div style={{ display: "inline-flex", gap: 2 }}>
          {ROUTES.map((r) => (
            <button key={r.key} type="button" onClick={() => setRoute(r.key)}
              style={chip(route === r.key)}>{r.label}</button>
          ))}
        </div>
        {/* infusion duration (only for infusion) */}
        {route === "infusion" && (
          <label style={ctrlWrap}>
            <span style={ctrlLbl}>inf</span>
            <input type="number" value={infusionH} min={0.25} step={0.25}
              onChange={(e) => setInfusionH(Math.max(0.25, Number(e.target.value) || 0.5))}
              style={{ ...numStyle, width: 44 }} /><span style={unitStyle}>h</span>
          </label>
        )}
        {/* MIC */}
        <label style={ctrlWrap}>
          <span style={ctrlLbl}>MIC</span>
          <input type="number" value={mic} placeholder="est" min={0} step={0.25}
            onChange={(e) => setMic(e.target.value)}
            style={{ ...numStyle, width: 50 }} /><span style={unitStyle}>mg/L</span>
        </label>
      </div>

      {cls && (
        <div style={{ padding: "3px 10px", fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)", borderBottom: "1px solid rgba(0,0,0,0.04)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          index <b style={{ color: TEAL.fgDeep }}>{cls.index}</b> · cidal ≥ {cls.target_cidal}
          {cls.index_raw !== "fT>MIC" ? "" : "%"} · e.g. {cls.examples.join(", ")}
        </div>
      )}

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!result && !running && (
          <EmptyState icon={<Syringe size={22} style={{ opacity: 0.4 }} />}
            msg="Pick a class and a regimen — the simulator builds the steady-state concentration-time curve, computes the class's governing PK/PD index against the MIC, and runs a Monte-Carlo PTA across the MIC range to find the breakpoint. Binding tells you it can kill; this tells you whether the dose will." />
        )}
        {!result && running && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 24,
            color: TEAL.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Simulating regimen + Monte-Carlo PTA…</div>
          </div>
        )}

        {result && (
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {/* attainment hero */}
            <div style={{ display: "flex", alignItems: "center", gap: 10,
              padding: "9px 11px", borderRadius: 8,
              background: TEAL.bg, border: `1px solid ${TEAL.border}` }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)", textTransform: "uppercase",
                  letterSpacing: "0.05em" }}>{result.index_label} @ MIC {result.mic_mg_l ?? "—"} mg/L</div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 1 }}>
                  <span style={{ fontSize: 28, fontWeight: 800,
                    fontFamily: "var(--lys-font-mono)", color: TEAL.fgDeep, lineHeight: 1 }}>
                    {result.index_at_mic ?? "—"}{result.index === "fT>MIC" ? "%" : ""}
                  </span>
                  <BandPill band={BAND_WORD[result.band] || "n/a"}>
                    {BAND_LABEL[result.band] || result.band}
                  </BandPill>
                </div>
                <div style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)", marginTop: 3 }}>
                  stasis ≥ {result.target_stasis} · cidal ≥ {result.target_cidal}
                  {result.index === "fT>MIC" ? "%" : ""} · MIC {result.mic_source}
                </div>
              </div>
              {/* breakpoint */}
              <div style={{ textAlign: "center", paddingLeft: 10,
                borderLeft: `1px solid ${TEAL.border}` }}>
                <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)", textTransform: "uppercase" }}>PK/PD breakpoint</div>
                <div style={{ fontSize: 20, fontWeight: 800, fontFamily: "var(--lys-font-mono)",
                  color: result.pkpd_breakpoint_mg_l ? TEAL.fgDeep : "var(--lys-text-faint)" }}>
                  {result.pkpd_breakpoint_mg_l ?? "<0.03"}
                </div>
                <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)" }}>mg/L · PTA ≥ 90%</div>
              </div>
            </div>

            {/* concentration-time curve */}
            <div>
              <SectionLabel color={TEAL.fgDeep}>
                steady-state exposure · free drug vs MIC</SectionLabel>
              <ConcTimeChart curve={result.curve} mic={result.mic_mg_l}
                interval={interval} index={result.index} />
            </div>

            {/* PK stat tiles */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 6 }}>
              <StatTile label="Cmax" value={result.exposure.cmax_mg_l} sub="mg/L"
                color={TEAL.fgDeep} />
              <StatTile label="Cmin" value={result.exposure.cmin_mg_l} sub="mg/L"
                color={TEAL.fgDeep} />
              <StatTile label="fAUC₂₄" value={result.exposure.fauc24_mg_h_l} sub="mg·h/L"
                color={TEAL.fgDeep} />
              <StatTile label="t½" value={result.pk.thalf_h} sub="h"
                color={TEAL.fgDeep} title={`CL ${result.pk.cl_l_h} L/h · V ${result.pk.v_l} L · fu ${result.pk.fu} (${result.pk.fu_source})`} />
            </div>

            {/* PTA-vs-MIC */}
            <div>
              <SectionLabel color={TEAL.fgDeep}>
                Monte-Carlo PTA · {result.n_patients.toLocaleString()} virtual patients</SectionLabel>
              <PtaChart pta={result.pta_curve} breakpoint={result.pkpd_breakpoint_mg_l}
                mic={result.mic_mg_l} />
            </div>

            <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", lineHeight: 1.45 }}>
              {result.provenance}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Concentration-time chart (steady-state interval) ───────────────── */
function ConcTimeChart({ curve, mic, interval, index }: {
  curve: CurvePt[]; mic: number | null; interval: number; index: string;
}) {
  if (!curve.length) return null;
  const W = 760, H = 150, PL = 34, PR = 10, PT = 10, PB = 20;
  const iw = W - PL - PR, ih = H - PT - PB;
  const tMax = interval;
  const cMax = Math.max(...curve.map((p) => p.total), mic ?? 0) * 1.12 || 1;
  const x = (t: number) => PL + (t / tMax) * iw;
  const y = (c: number) => PT + ih - (c / cMax) * ih;
  const line = (key: "total" | "free") =>
    curve.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(" ");
  // shaded free>MIC band (where the time-dependent index "counts")
  const aboveArea = mic != null ? (() => {
    const segs: string[] = [];
    curve.forEach((p, i) => {
      if (p.free >= mic) {
        const xx = x(p.t).toFixed(1);
        segs.push(`${segs.length ? "L" : "M"}${xx} ${y(p.free).toFixed(1)}`);
        if (i === curve.length - 1 || curve[i + 1].free < mic)
          segs.push(`L${xx} ${y(mic).toFixed(1)}`);
        if (i > 0 && curve[i - 1].free < mic)
          segs.unshift(`M${xx} ${y(mic).toFixed(1)} `);
      }
    });
    return segs.join(" ");
  })() : "";
  const micY = mic != null ? y(mic) : null;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto",
      display: "block", background: "var(--lys-surface)", borderRadius: 6,
      border: "1px solid var(--lys-border)" }}>
      {/* y grid + labels */}
      {[0, 0.5, 1].map((f) => {
        const yy = PT + ih - f * ih;
        return <g key={f}>
          <line x1={PL} y1={yy} x2={W - PR} y2={yy} stroke="rgba(0,0,0,0.06)" strokeWidth={0.5} />
          <text x={PL - 4} y={yy + 3} textAnchor="end" fontSize={7}
            fontFamily="var(--lys-font-mono)" fill="var(--lys-text-faint)">
            {(cMax * f).toFixed(cMax < 4 ? 1 : 0)}</text>
        </g>;
      })}
      {/* x labels */}
      {[0, interval / 2, interval].map((t) => (
        <text key={t} x={x(t)} y={H - 5} textAnchor="middle" fontSize={7}
          fontFamily="var(--lys-font-mono)" fill="var(--lys-text-faint)">{t}h</text>
      ))}
      {/* fT>MIC shaded region */}
      {aboveArea && index === "fT>MIC" && (
        <path d={aboveArea} fill="rgba(13,148,136,0.16)" stroke="none" />
      )}
      {/* MIC line */}
      {micY != null && <>
        <line x1={PL} y1={micY} x2={W - PR} y2={micY} stroke="#dc2626"
          strokeWidth={1} strokeDasharray="4 3" />
        <text x={W - PR} y={micY - 3} textAnchor="end" fontSize={7}
          fontFamily="var(--lys-font-mono)" fill="#dc2626">MIC</text>
      </>}
      {/* total + free lines */}
      <path d={line("total")} fill="none" stroke={TEAL.fg} strokeWidth={1}
        strokeOpacity={0.35} />
      <path d={line("free")} fill="none" stroke={TEAL.fgDeep} strokeWidth={1.6} />
      <text x={W - PR} y={PT + 8} textAnchor="end" fontSize={7}
        fontFamily="var(--lys-font-mono)" fill={TEAL.fgDeep}>free drug</text>
    </svg>
  );
}

/* ── PTA-vs-MIC chart (log-dilution x) ──────────────────────────────── */
function PtaChart({ pta, breakpoint, mic }: {
  pta: PtaPt[]; breakpoint: number | null; mic: number | null;
}) {
  if (!pta.length) return null;
  const W = 760, H = 140, PL = 30, PR = 10, PT = 10, PB = 20;
  const iw = W - PL - PR, ih = H - PT - PB;
  const n = pta.length;
  const x = (i: number) => PL + (n === 1 ? 0 : (i / (n - 1)) * iw);
  const y = (p: number) => PT + ih - p * ih;
  const path = pta.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.pta).toFixed(1)}`).join(" ");
  const area = `M${x(0).toFixed(1)} ${(PT + ih).toFixed(1)} ` +
    pta.map((p, i) => `L${x(i).toFixed(1)} ${y(p.pta).toFixed(1)}`).join(" ") +
    ` L${x(n - 1).toFixed(1)} ${(PT + ih).toFixed(1)} Z`;
  const bpIdx = breakpoint != null ? pta.findIndex((p) => p.mic === breakpoint) : -1;
  const micIdx = mic != null ? pta.reduce((best, p, i) =>
    Math.abs(p.mic - mic) < Math.abs(pta[best].mic - mic) ? i : best, 0) : -1;
  const y90 = y(0.9);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto",
      display: "block", background: "var(--lys-surface)", borderRadius: 6,
      border: "1px solid var(--lys-border)" }}>
      {/* y grid */}
      {[0, 0.5, 1].map((f) => {
        const yy = y(f);
        return <g key={f}>
          <line x1={PL} y1={yy} x2={W - PR} y2={yy} stroke="rgba(0,0,0,0.06)" strokeWidth={0.5} />
          <text x={PL - 4} y={yy + 3} textAnchor="end" fontSize={7}
            fontFamily="var(--lys-font-mono)" fill="var(--lys-text-faint)">{f * 100}</text>
        </g>;
      })}
      {/* x ticks (every other MIC) */}
      {pta.map((p, i) => (i % 2 === 0 ? (
        <text key={i} x={x(i)} y={H - 5} textAnchor="middle" fontSize={6.5}
          fontFamily="var(--lys-font-mono)" fill="var(--lys-text-faint)">
          {p.mic < 1 ? p.mic : p.mic}</text>
      ) : null))}
      {/* 90% target line */}
      <line x1={PL} y1={y90} x2={W - PR} y2={y90} stroke="#d97706"
        strokeWidth={1} strokeDasharray="4 3" />
      <text x={PL + 2} y={y90 - 3} fontSize={7} fontFamily="var(--lys-font-mono)"
        fill="#d97706">90% target</text>
      {/* area + line */}
      <path d={area} fill="rgba(13,148,136,0.12)" stroke="none" />
      <path d={path} fill="none" stroke={TEAL.fgDeep} strokeWidth={1.6} />
      {/* breakpoint marker */}
      {bpIdx >= 0 && <>
        <line x1={x(bpIdx)} y1={PT} x2={x(bpIdx)} y2={PT + ih} stroke={TEAL.fg}
          strokeWidth={1} strokeDasharray="2 2" />
        <circle cx={x(bpIdx)} cy={y(pta[bpIdx].pta)} r={2.6} fill={TEAL.fgDeep} />
      </>}
      {/* current MIC marker */}
      {micIdx >= 0 && (
        <circle cx={x(micIdx)} cy={y(pta[micIdx].pta)} r={3} fill="none"
          stroke="#dc2626" strokeWidth={1.4} />
      )}
      <text x={W - PR} y={H - 5} textAnchor="end" fontSize={6.5}
        fontFamily="var(--lys-font-mono)" fill="var(--lys-text-faint)">MIC mg/L →</text>
    </svg>
  );
}

/* ── control styles ─────────────────────────────────────────────────── */
const selStyle: React.CSSProperties = {
  fontSize: 9.5, fontFamily: "var(--lys-font-mono)", padding: "3px 5px",
  borderRadius: 5, border: "1px solid var(--lys-border)",
  background: "var(--lys-surface)", color: "var(--lys-text)", maxWidth: 200 };
const ctrlWrap: React.CSSProperties = { display: "inline-flex", alignItems: "center", gap: 3 };
const ctrlLbl: React.CSSProperties = { fontSize: 8, fontFamily: "var(--lys-font-mono)",
  textTransform: "uppercase", color: "var(--lys-text-faint)", letterSpacing: "0.04em" };
const numStyle: React.CSSProperties = { fontSize: 10, fontFamily: "var(--lys-font-mono)",
  padding: "2px 4px", borderRadius: 4, border: "1px solid var(--lys-border)",
  background: "var(--lys-surface)", color: "var(--lys-text)", textAlign: "right" };
const unitStyle: React.CSSProperties = { fontSize: 8, fontFamily: "var(--lys-font-mono)",
  color: "var(--lys-text-faint)" };
function chip(active: boolean): React.CSSProperties {
  return { fontSize: 9, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
    padding: "3px 7px", borderRadius: 5, cursor: "pointer",
    border: `1px solid ${active ? TEAL.border : "var(--lys-border)"}`,
    background: active ? TEAL.fg : "transparent",
    color: active ? "white" : "var(--lys-text-dim)" };
}
