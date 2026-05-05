import { useEffect, useState } from "react";

interface Mol2DProps {
  apiBase: string;
  smiles: string | null;
}

export function Mol2D({ apiBase, smiles }: Mol2DProps) {
  const [svg, setSvg] = useState<string | null>(null);
  const [props, setProps] = useState<{ formula?: string; mw?: number; logp?: number; n_atoms?: number; n_bonds?: number } | null>(null);

  useEffect(() => {
    if (!smiles) {
      setSvg(null);
      setProps(null);
      return;
    }
    // 1) Render via NCI/CACTUS as SVG (free, no auth)
    const src = `https://cactus.nci.nih.gov/chemical/structure/${encodeURIComponent(smiles)}/file?format=svg&width=600&height=240`;
    setSvg(src);

    // 2) Pull props from our /workbench/molecule/3d (which also returns mw/logp/formula)
    fetch(`${apiBase}/workbench/molecule/3d`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ smiles, optimize: false, add_hydrogens: false }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d) {
          setProps({
            formula: d.formula,
            mw: d.mw,
            logp: d.logp,
            n_atoms: d.n_atoms,
            n_bonds: d.n_bonds,
          });
        }
      })
      .catch(() => {});
  }, [apiBase, smiles]);

  if (!smiles) {
    return (
      <div style={{
        padding: 24, textAlign: "center", color: "var(--lys-text-faint)", fontSize: 12,
        flex: 1, minHeight: 0, display: "grid", placeItems: "center",
      }}>
        no candidate yet
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, overflow: "hidden" }}>
      {svg && (
        <div style={{
          flex: 1,
          minHeight: 0,
          background: "white",
          margin: "8px 12px",
          borderRadius: 8,
          overflow: "hidden",
          display: "grid",
          placeItems: "center",
          border: "1px solid var(--lys-border)",
        }}>
          <img
            src={svg}
            alt={smiles}
            style={{ maxHeight: "100%", maxWidth: "100%" }}
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
          />
        </div>
      )}
      {props && (
        <div style={{
          padding: "6px 12px",
          fontFamily: "var(--lys-font-mono)",
          fontSize: 11,
          color: "var(--lys-text-dim)",
          borderTop: "1px solid var(--lys-border)",
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
        }}>
          <Stat label="formula" value={props.formula} accent />
          <Stat label="MW" value={props.mw?.toFixed(2)} />
          <Stat label="logP" value={props.logp?.toFixed(2)} />
          <Stat label="atoms" value={props.n_atoms} />
          <Stat label="bonds" value={props.n_bonds} />
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: any; accent?: boolean }) {
  if (value === undefined || value === null) return null;
  return (
    <span>
      <span style={{ color: "var(--lys-text-faint)" }}>{label}: </span>
      <span style={{ color: accent ? "var(--lys-accent)" : "var(--lys-text)" }}>{value}</span>
    </span>
  );
}
