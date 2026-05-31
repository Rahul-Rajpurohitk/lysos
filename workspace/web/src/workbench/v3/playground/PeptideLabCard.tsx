/**
 * PeptideLabCard — the antimicrobial-peptide (AMP) modality frontend.
 *
 * The signature visual is the HELICAL WHEEL: residues plotted around a
 * circle at the α-helix 100°/residue periodicity. When hydrophobic
 * residues cluster on one arc, the peptide is amphipathic — the hallmark
 * of a membrane-active AMP. A peptide chemist reads this instantly.
 *
 * Plus a real descriptor panel (charge / µH / GRAVY / Boman ...),
 * activity + hemolysis + therapeutic-index bars, and AMP sequence
 * generation. Backend: /workbench/chem/peptide/* (chem_peptide.py).
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { Dna, RefreshCw, Sparkles, Trash2 } from "lucide-react";

interface WheelResidue {
  idx: number; aa: string; angle: number; kd: number;
  hydrophobic: boolean; cationic: boolean; anionic: boolean;
}
interface PeptidePanel {
  sequence: string;
  descriptors: {
    length: number; mw: number; net_charge: number; gravy: number;
    hydrophobic_moment: number; boman_index: number;
    aliphatic_index: number; instability_index: number;
    frac_hydrophobic: number; frac_cationic: number;
  };
  activity: { amp_probability: number; band: string };
  hemolysis: { hemolysis_risk: number; band: string };
  therapeutic_index: { therapeutic_index: number; band: string };
  helical_wheel: WheelResidue[];
  composite: number;
  tier: string;
  artifact_id?: string | null;
}
interface GenCandidate {
  sequence: string; composite: number; amp_probability: number;
  hemolysis_risk: number; net_charge: number;
}
interface Props {
  apiBase: string;
  sessionId: string | null;
  onLoadSequence?: (seq: string) => void;
}

const TEAL = {
  bg: "rgba(13,148,136,0.06)", bgStrong: "rgba(13,148,136,0.13)",
  border: "rgba(13,148,136,0.28)", fg: "#0d9488", fgDeep: "#0f766e",
} as const;

// Residue colours: hydrophobic = amber (the "face"), cationic = blue,
// anionic = red, polar/other = grey.
function residueColor(r: WheelResidue): string {
  if (r.cationic) return "#2563eb";
  if (r.anionic) return "#dc2626";
  if (r.hydrophobic) return "#d97706";
  return "#94a3b8";
}
function bandColor(b: string): string {
  if (["active", "selective", "advance", "low"].includes(b)) return "#16a34a";
  if (["moderate", "promising"].includes(b)) return "#d97706";
  return "#dc2626";
}

const EXAMPLES = [
  { name: "magainin-2", seq: "GIGKFLHSAKKFGKAFVGEIMNS" },
  { name: "melittin", seq: "GIGAVLKVLTTGLPALISWIKRKRQQ" },
  { name: "LL-37 frag", seq: "KRIVQRIKDFLRNLV" },
];

export function PeptideLabCard({ apiBase, sessionId, onLoadSequence }: Props) {
  const [seq, setSeq] = useState("");
  const [panel, setPanel] = useState<PeptidePanel | null>(null);
  const [gen, setGen] = useState<GenCandidate[] | null>(null);
  const [busy, setBusy] = useState<"" | "panel" | "gen">("");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const analyze = useCallback(async (sequence: string) => {
    const s = sequence.trim().toUpperCase();
    if (!s) return;
    setError(null); setBusy("panel"); setGen(null);
    try {
      const r = await fetch(`${apiBase}/workbench/chem/peptide/panel`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ sequence: s, session_id: sessionId, save: true }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setError(d.detail || `analysis failed (HTTP ${r.status})`);
        return;
      }
      setPanel(await r.json());
    } catch { setError("analysis error"); }
    finally { setBusy(""); }
  }, [apiBase, sessionId]);

  async function generate(seed: string | null) {
    setError(null); setBusy("gen");
    try {
      const r = await fetch(`${apiBase}/workbench/chem/peptide/generate`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ seed, n: 8, session_id: sessionId, save: true }),
      });
      if (!r.ok) { setError(`generation failed (HTTP ${r.status})`); return; }
      const d = await r.json();
      setGen(d.candidates ?? []);
    } catch { setError("generation error"); }
    finally { setBusy(""); }
  }

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", background: "transparent", overflow: "hidden",
      fontFamily: "var(--lys-font-body)" }}>
      {/* header */}
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: TEAL.fgDeep,
        borderBottom: `1px solid ${TEAL.border}` }}>
        <Dna size={11} style={{ color: TEAL.fg }} />
        <span>peptide lab · AMP modality</span>
      </div>

      {/* input */}
      <div style={{ padding: "8px 10px", display: "flex", flexDirection: "column",
        gap: 6, borderBottom: "1px solid rgba(0,0,0,0.05)" }}>
        <div style={{ display: "flex", gap: 6 }}>
          <input
            value={seq}
            onChange={(e) => setSeq(e.target.value.toUpperCase())}
            onKeyDown={(e) => { if (e.key === "Enter") analyze(seq); }}
            placeholder="AMP sequence (e.g. GIGKFLHSAKKFGKAFVGEIMNS)"
            spellCheck={false}
            style={{ flex: 1, minWidth: 0, padding: "5px 8px", borderRadius: 5,
              border: `1px solid ${TEAL.border}`, fontSize: 10.5,
              fontFamily: "var(--lys-font-mono)", letterSpacing: "0.05em",
              background: "white", color: "var(--lys-text)" }} />
          <button type="button" onClick={() => analyze(seq)} disabled={!!busy || !seq}
            style={{ padding: "5px 11px", borderRadius: 5, border: 0,
              background: !seq ? "rgba(0,0,0,0.05)" : TEAL.fg,
              color: !seq ? "var(--lys-text-faint)" : "white",
              fontSize: 10.5, fontWeight: 600,
              cursor: busy || !seq ? "not-allowed" : "pointer" }}>
            {busy === "panel" ? "…" : "Analyze"}
          </button>
        </div>
        <div style={{ display: "flex", gap: 5, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)" }}>examples:</span>
          {EXAMPLES.map((ex) => (
            <button key={ex.name} type="button"
              onClick={() => { setSeq(ex.seq); analyze(ex.seq); }}
              style={{ padding: "1px 7px", borderRadius: 999, border: `1px solid ${TEAL.border}`,
                background: TEAL.bg, color: TEAL.fgDeep, fontSize: 8.5,
                cursor: "pointer", fontFamily: "var(--lys-font-mono)" }}>
              {ex.name}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <button type="button" onClick={() => generate(null)} disabled={!!busy}
            style={{ display: "inline-flex", alignItems: "center", gap: 4,
              padding: "3px 9px", borderRadius: 5, border: 0, background: TEAL.fgDeep,
              color: "white", fontSize: 9.5, fontWeight: 600,
              cursor: busy ? "not-allowed" : "pointer" }}>
            <Sparkles size={11} />{busy === "gen" ? "Designing…" : "De-novo AMPs"}
          </button>
        </div>
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!panel && !gen && !busy && (
          <Empty msg="Analyze an antimicrobial peptide — real biochemistry descriptors, predicted antibacterial activity + hemolysis + therapeutic index, and the helical-wheel amphipathicity view. Or generate de-novo AMPs." />
        )}
        {panel && <PanelView panel={panel} onLoad={onLoadSequence} />}
        {gen && <GenView gen={gen} onPick={(s) => { setSeq(s); analyze(s); }} />}
      </div>
    </div>
  );
}

function PanelView({ panel, onLoad }: {
  panel: PeptidePanel; onLoad?: (s: string) => void;
}) {
  const d = panel.descriptors;
  const tierCol = bandColor(panel.tier);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* header: composite + sequence */}
      <div style={{ border: `1px solid ${TEAL.border}`, borderRadius: 7,
        background: TEAL.bg, padding: 8 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6,
          fontFamily: "var(--lys-font-mono)" }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: tierCol, lineHeight: 1 }}>
            {panel.composite.toFixed(2)}</span>
          <span style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
            textTransform: "uppercase", letterSpacing: "0.05em" }}>
            composite · {panel.tier}</span>
        </div>
        <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-dim)", marginTop: 4, wordBreak: "break-all" }}>
          {panel.sequence}
        </div>
      </div>

      {/* helical wheel + activity bars side by side */}
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <HelicalWheel residues={panel.helical_wheel} />
        <div style={{ flex: 1, minWidth: 0, display: "flex",
          flexDirection: "column", gap: 5 }}>
          <Bar label="AMP activity" value={panel.activity.amp_probability}
            band={panel.activity.band} />
          <Bar label="hemolysis risk" value={panel.hemolysis.hemolysis_risk}
            band={panel.hemolysis.band} invert />
          <Bar label="therapeutic idx" value={panel.therapeutic_index.therapeutic_index}
            band={panel.therapeutic_index.band} />
        </div>
      </div>

      {/* descriptor tiles */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 5 }}>
        <Tile label="charge" value={`${d.net_charge >= 0 ? "+" : ""}${d.net_charge.toFixed(1)}`}
          color={d.net_charge >= 2 ? "#16a34a" : "#d97706"} />
        <Tile label="µH amphi" value={d.hydrophobic_moment.toFixed(2)}
          color={d.hydrophobic_moment >= 0.35 ? "#16a34a" : "#d97706"} />
        <Tile label="GRAVY" value={d.gravy.toFixed(2)} />
        <Tile label="length" value={`${d.length}aa`} />
        <Tile label="Boman" value={d.boman_index.toFixed(1)} />
        <Tile label="aliphatic" value={d.aliphatic_index.toFixed(0)} />
        <Tile label="instab." value={d.instability_index.toFixed(0)}
          color={d.instability_index <= 40 ? "#16a34a" : "#dc2626"} />
        <Tile label="MW" value={d.mw.toFixed(0)} />
      </div>

      {onLoad && (
        <button type="button" onClick={() => onLoad(panel.sequence)}
          style={{ width: "100%", padding: "6px 0", border: 0, borderRadius: 5,
            background: TEAL.fg, color: "white", fontSize: 10.5, fontWeight: 700,
            cursor: "pointer" }}>
          Use this sequence
        </button>
      )}
    </div>
  );
}

/** The signature visual — residues around a circle at 100°/residue.
 *  Hydrophobic residues clustering on one arc = amphipathic = membrane-active. */
function HelicalWheel({ residues }: { residues: WheelResidue[] }) {
  const size = 150;
  const cx = size / 2, cy = size / 2;
  const R = size / 2 - 18;
  return (
    <svg width={size} height={size} style={{ flexShrink: 0,
      background: "white", borderRadius: 8, border: `1px solid ${TEAL.border}` }}>
      {/* guide circle */}
      <circle cx={cx} cy={cy} r={R} fill="none" stroke="rgba(0,0,0,0.08)" strokeWidth={1} />
      {/* connecting backbone path */}
      <polyline
        points={residues.map((r) => {
          const a = (r.angle - 90) * Math.PI / 180;
          return `${cx + R * Math.cos(a)},${cy + R * Math.sin(a)}`;
        }).join(" ")}
        fill="none" stroke="rgba(13,148,136,0.25)" strokeWidth={1.5} />
      {residues.map((r) => {
        const a = (r.angle - 90) * Math.PI / 180;
        const x = cx + R * Math.cos(a), y = cy + R * Math.sin(a);
        const col = residueColor(r);
        return (
          <g key={r.idx}>
            <circle cx={x} cy={y} r={9} fill={col} opacity={0.9}>
              <title>{`#${r.idx + 1} ${r.aa} · KD ${r.kd}`}</title>
            </circle>
            <text x={x} y={y + 3.2} textAnchor="middle" fontSize={9}
              fontWeight={700} fill="white"
              fontFamily="var(--lys-font-mono)">{r.aa}</text>
          </g>
        );
      })}
      <text x={cx} y={cy - 2} textAnchor="middle" fontSize={7}
        fill="var(--lys-text-faint)" fontFamily="var(--lys-font-mono)">helical</text>
      <text x={cx} y={cy + 7} textAnchor="middle" fontSize={7}
        fill="var(--lys-text-faint)" fontFamily="var(--lys-font-mono)">wheel</text>
    </svg>
  );
}

function Bar({ label, value, band, invert }: {
  label: string; value: number; band: string; invert?: boolean;
}) {
  const col = bandColor(band);
  const pct = Math.round(value * 100);
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between",
        fontSize: 8.5, fontFamily: "var(--lys-font-mono)", marginBottom: 2 }}>
        <span style={{ color: "var(--lys-text-faint)", textTransform: "uppercase" }}>
          {label}{invert ? " ↓" : ""}</span>
        <span style={{ color: col, fontWeight: 700 }}>
          {value.toFixed(2)} {band}</span>
      </div>
      <div style={{ height: 7, borderRadius: 4, background: "rgba(0,0,0,0.06)",
        overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: col }} />
      </div>
    </div>
  );
}

function Tile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: "rgba(255,255,255,0.6)", border: `1px solid ${TEAL.border}`,
      borderRadius: 4, padding: "3px 4px", textAlign: "center" }}>
      <div style={{ fontSize: 7, fontFamily: "var(--lys-font-mono)",
        textTransform: "uppercase", color: "var(--lys-text-faint)" }}>{label}</div>
      <div style={{ fontSize: 12, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
        color: color ?? "var(--lys-text)" }}>{value}</div>
    </div>
  );
}

function GenView({ gen, onPick }: {
  gen: GenCandidate[]; onPick: (s: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase",
        color: TEAL.fgDeep }}>de-novo AMP designs · ranked</div>
      {gen.map((c, i) => {
        const col = c.composite >= 0.6 ? "#16a34a" : c.composite >= 0.45 ? "#d97706" : "#dc2626";
        return (
          <button key={i} type="button" onClick={() => onPick(c.sequence)}
            style={{ display: "flex", alignItems: "center", gap: 7, textAlign: "left",
              padding: "5px 8px", borderRadius: 5, border: `1px solid ${TEAL.border}`,
              background: TEAL.bg, cursor: "pointer" }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: col,
              fontFamily: "var(--lys-font-mono)", minWidth: 32 }}>
              {c.composite.toFixed(2)}</span>
            <span style={{ flex: 1, minWidth: 0, fontSize: 9,
              fontFamily: "var(--lys-font-mono)", color: "var(--lys-text-dim)",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {c.sequence}</span>
            <span style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-faint)" }}>
              chg {c.net_charge >= 0 ? "+" : ""}{c.net_charge.toFixed(0)} · hemo {c.hemolysis_risk.toFixed(2)}</span>
          </button>
        );
      })}
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6,
      alignItems: "center", justifyContent: "center", padding: 20,
      textAlign: "center", color: "var(--lys-text-faint)", fontSize: 11 }}>
      <Dna size={22} style={{ opacity: 0.4 }} />
      <div>{msg}</div>
    </div>
  );
}
