/**
 * PropertiesCard — live medchem property dashboard.
 *
 * Computes the full RDKit descriptor stack for the current SMILES via
 * GET /workbench/molecule/properties?smiles=… and renders it as
 * scannable medchem-grade panels:
 *
 *   1. Hero — MW · logP · TPSA · QED  (4 big tiles)
 *   2. Lipinski Ro5 — 4-component check (MW < 500, logP < 5, HBD ≤ 5, HBA ≤ 10)
 *   3. Veber rules — rot. bonds ≤ 10 AND TPSA ≤ 140
 *   4. Atom composition — element counts (C / N / O / S / F / Cl / etc.)
 *   5. Rings + sp3 fraction
 *   6. Drug-class detector — SMARTS-matched class hints (β-lactam, quinolone, etc.)
 *
 * Auto-refreshes whenever the SMILES prop changes.
 */
import { useEffect, useState } from "react";
import { FlaskConical, AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";

interface MolProps {
  smiles: string;
  canonical_smiles: string;
  inchi_key: string;
  n_atoms: number;
  n_heavy_atoms: number;
  n_bonds: number;
  n_rings: number;
  n_aromatic_rings: number;
  n_rotatable_bonds: number;
  molecular_weight: number;
  logp: number;
  h_bond_donors: number;
  h_bond_acceptors: number;
  lipinski_violations: number;
  lipinski_pass: boolean;
  qed: number;
  sa_score: number;
  tpsa: number;
  fsp3: number;
  formal_charge: number;
  element_counts: Record<string, number>;
  veber_pass: boolean;
  detected_classes: string[];
}

interface Props {
  apiBase: string;
  smiles: string | null;
}

const ELEMENT_COLOR: Record<string, string> = {
  C: "#374151", N: "#2563eb", O: "#dc2626", S: "#ca8a04",
  F: "#16a34a", Cl: "#16a34a", Br: "#9a3412", I: "#7c3aed",
  P: "#ea580c", H: "#9ca3af",
};

export function PropertiesCard({ apiBase, smiles }: Props) {
  const [data, setData] = useState<MolProps | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  async function refresh() {
    if (!smiles) {
      setData(null);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/workbench/molecule/properties?smiles=${encodeURIComponent(smiles)}`);
      if (!r.ok) throw new Error(`http ${r.status}`);
      const d = await r.json();
      setData(d);
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [smiles, apiBase]);

  if (!smiles) {
    return (
      <div style={containerStyle}>
        <Header title="properties · live medchem stack" iconColor="#9ca3af" onRefresh={refresh} loading={false} />
        <div style={emptyStateStyle}>
          <FlaskConical size={20} style={{ opacity: 0.4 }} />
          <div>Pick or design a candidate to see Lipinski / QED / TPSA live</div>
        </div>
      </div>
    );
  }

  if (loading && !data) {
    return (
      <div style={containerStyle}>
        <Header title="properties · computing..." iconColor="#9ca3af" onRefresh={refresh} loading={true} />
        <div style={emptyStateStyle}>computing descriptors…</div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={containerStyle}>
        <Header title="properties · error" iconColor="#dc2626" onRefresh={refresh} loading={false} />
        <div style={{ padding: 12, fontSize: 10, color: "#dc2626" }}>{error}</div>
      </div>
    );
  }

  const lipChecks = [
    { name: "MW < 500", pass: data.molecular_weight < 500, value: data.molecular_weight.toFixed(0), unit: "Da" },
    { name: "logP < 5",  pass: data.logp < 5, value: data.logp.toFixed(2), unit: "" },
    { name: "HBD ≤ 5",  pass: data.h_bond_donors <= 5, value: String(data.h_bond_donors), unit: "" },
    { name: "HBA ≤ 10", pass: data.h_bond_acceptors <= 10, value: String(data.h_bond_acceptors), unit: "" },
  ];

  return (
    <div style={containerStyle}>
      <Header
        title={`properties · ${data.n_heavy_atoms} heavy · ${data.n_bonds} bonds`}
        iconColor={data.lipinski_pass ? "var(--lys-accent, #10b981)" : "#d97706"}
        onRefresh={refresh}
        loading={loading}
      />
      <div style={{ flex: 1, overflow: "auto", padding: 8, display: "flex",
        flexDirection: "column", gap: 8 }}>

        {/* HERO: 4 big tiles */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 4 }}>
          <Tile label="MW" value={data.molecular_weight.toFixed(0)} unit="Da"
            color={data.molecular_weight < 500 ? "#10b981" : "#d97706"} />
          <Tile label="logP" value={data.logp.toFixed(2)} unit=""
            color={data.logp < 5 && data.logp > -2 ? "#10b981" : "#d97706"} />
          <Tile label="TPSA" value={data.tpsa.toFixed(0)} unit="Å²"
            color={data.tpsa <= 140 ? "#10b981" : "#d97706"} />
          <Tile label="QED" value={data.qed.toFixed(2)} unit=""
            color={data.qed >= 0.67 ? "#10b981" : data.qed >= 0.4 ? "#d97706" : "#dc2626"} />
        </div>

        {/* LIPINSKI Ro5 */}
        <Section title={`lipinski Ro5 · ${data.lipinski_pass ? "PASS" : `${data.lipinski_violations} viol`}`}
                 iconColor={data.lipinski_pass ? "#10b981" : "#d97706"}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 3 }}>
            {lipChecks.map((c) => (
              <RuleCheck key={c.name} {...c} />
            ))}
          </div>
        </Section>

        {/* VEBER */}
        <Section title={`veber · ${data.veber_pass ? "PASS" : "FAIL"}`}
                 iconColor={data.veber_pass ? "#10b981" : "#d97706"}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 3 }}>
            <RuleCheck name="rot bonds ≤ 10" pass={data.n_rotatable_bonds <= 10}
              value={String(data.n_rotatable_bonds)} unit="" />
            <RuleCheck name="TPSA ≤ 140" pass={data.tpsa <= 140}
              value={data.tpsa.toFixed(0)} unit="Å²" />
          </div>
        </Section>

        {/* ATOM COMPOSITION */}
        <Section title="composition" iconColor="#6366f1">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {Object.entries(data.element_counts).map(([sym, n]) => {
              const c = ELEMENT_COLOR[sym] ?? "#374151";
              return (
                <div key={sym} style={{
                  padding: "2px 7px", borderRadius: 999,
                  background: `${c}10`, border: `1px solid ${c}30`,
                  fontSize: 10, fontFamily: "var(--lys-font-mono)",
                  display: "flex", alignItems: "center", gap: 3,
                }}>
                  <span style={{ fontWeight: 700, color: c }}>{sym}</span>
                  <span style={{ color: "var(--lys-text-faint)" }}>×{n}</span>
                </div>
              );
            })}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginTop: 6 }}>
            <Stat label="rings" value={`${data.n_rings} (${data.n_aromatic_rings}ar)`} />
            <Stat label="fsp3" value={data.fsp3.toFixed(2)} />
            <Stat label="charge" value={data.formal_charge === 0 ? "neutral" : data.formal_charge.toString()} />
          </div>
        </Section>

        {/* DRUG-CLASS DETECTOR */}
        {data.detected_classes.length > 0 && (
          <Section title={`drug-class hits · ${data.detected_classes.length}`} iconColor="#a855f7">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {data.detected_classes.map((c) => (
                <span key={c} style={{
                  padding: "2px 8px", borderRadius: 999,
                  background: "rgba(168,85,247,0.10)",
                  color: "#a855f7", fontSize: 10,
                  fontFamily: "var(--lys-font-mono)", fontWeight: 600,
                }}>{c}</span>
              ))}
            </div>
          </Section>
        )}

        {/* IDENTIFIERS */}
        <Section title="identifiers" iconColor="#6b7280">
          <div style={{ fontSize: 9.5, fontFamily: "var(--lys-font-mono)", lineHeight: 1.5 }}>
            <div style={{ display: "flex", gap: 4 }}>
              <span style={{ color: "var(--lys-text-faint)", minWidth: 50 }}>SMILES:</span>
              <span style={{ wordBreak: "break-all", color: "var(--lys-text-dim)" }}>{data.canonical_smiles}</span>
            </div>
            {data.inchi_key && (
              <div style={{ display: "flex", gap: 4 }}>
                <span style={{ color: "var(--lys-text-faint)", minWidth: 50 }}>InChIKey:</span>
                <span style={{ color: "var(--lys-text-dim)" }}>{data.inchi_key}</span>
              </div>
            )}
            {data.sa_score > 0 && (
              <div style={{ display: "flex", gap: 4 }}>
                <span style={{ color: "var(--lys-text-faint)", minWidth: 50 }}>SAscore:</span>
                <span style={{ color: "var(--lys-text-dim)" }}>
                  {data.sa_score.toFixed(2)} {data.sa_score < 4 ? "(easy)" : data.sa_score < 6 ? "(moderate)" : "(hard)"}
                </span>
              </div>
            )}
          </div>
        </Section>
      </div>
    </div>
  );
}

const containerStyle: React.CSSProperties = {
  width: "100%", height: "100%", display: "flex", flexDirection: "column",
  background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
};

const emptyStateStyle: React.CSSProperties = {
  flex: 1, display: "flex", flexDirection: "column", gap: 6,
  alignItems: "center", justifyContent: "center",
  padding: 16, textAlign: "center",
  color: "var(--lys-text-faint)", fontSize: 11, fontFamily: "var(--lys-font-mono)",
};

function Header({ title, iconColor, onRefresh, loading }: { title: string; iconColor: string; onRefresh: () => void; loading: boolean }) {
  return (
    <div style={{
      padding: "5px 10px",
      fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
      color: "var(--lys-text-faint)", letterSpacing: "0.06em",
      textTransform: "uppercase",
      borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      display: "flex", alignItems: "center", gap: 6,
    }}>
      <FlaskConical size={11} style={{ color: iconColor }} />
      <span>{title}</span>
      <span style={{ flex: 1 }} />
      <button type="button" onClick={onRefresh} disabled={loading}
        style={{ border: 0, background: "transparent", cursor: loading ? "wait" : "pointer", padding: 2, color: "var(--lys-text-faint)" }}>
        <RefreshCw size={11} />
      </button>
    </div>
  );
}

function Tile({ label, value, unit, color }: { label: string; value: string; unit: string; color: string }) {
  return (
    <div style={{
      padding: "8px 6px", borderRadius: 6,
      background: `${color}10`, borderLeft: `3px solid ${color}`,
      display: "flex", flexDirection: "column", gap: 1,
    }}>
      <div style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
        fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
        textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color, lineHeight: 1,
        fontFamily: "var(--lys-font-mono)" }}>
        {value}
        {unit && <span style={{ fontSize: 9, fontWeight: 500, color: "var(--lys-text-faint)", marginLeft: 2 }}>{unit}</span>}
      </div>
    </div>
  );
}

function Section({ title, iconColor, children }: { title: string; iconColor: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{
        fontSize: 9, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", letterSpacing: "0.04em",
        textTransform: "uppercase", marginBottom: 4,
        display: "flex", alignItems: "center", gap: 4,
        borderLeft: `2px solid ${iconColor}`, paddingLeft: 6,
      }}>{title}</div>
      {children}
    </div>
  );
}

function RuleCheck({ name, pass, value, unit }: { name: string; pass: boolean; value: string; unit: string }) {
  const color = pass ? "#10b981" : "#d97706";
  return (
    <div style={{
      padding: "3px 6px", borderRadius: 4,
      background: `${color}10`,
      display: "flex", alignItems: "center", gap: 4,
      fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
    }}>
      {pass
        ? <CheckCircle2 size={10} style={{ color, flexShrink: 0 }} />
        : <AlertTriangle size={10} style={{ color, flexShrink: 0 }} />}
      <span style={{ color: "var(--lys-text-dim)", flex: 1, minWidth: 0 }}>{name}</span>
      <span style={{ fontWeight: 700, color }}>{value}{unit}</span>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      padding: "3px 6px", borderRadius: 4,
      background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
      fontSize: 10, fontFamily: "var(--lys-font-mono)",
    }}>
      <div style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
        textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
      <div style={{ color: "var(--lys-text)", fontWeight: 600 }}>{value}</div>
    </div>
  );
}
