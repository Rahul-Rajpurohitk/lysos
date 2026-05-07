/**
 * Mol3DTheaterWindow — wraps the existing Mol3D viewer as a playground
 * window. The chrome (title, drag, resize, close) is provided by the
 * parent <PlaygroundWindow>; this component just owns the body.
 *
 * Adds a tag-detection overlay that polls /molecule/match-known whenever
 * the SMILES changes and shows the closest known antibiotic. As the user
 * builds atom-by-atom, the overlay updates with the live similarity
 * score — turns green when ≥0.95 (effectively "you've built X").
 */
import { useEffect, useState } from "react";
import { Mol3D } from "../components/Mol3D";

interface Props {
  apiBase: string;
  smiles: string | null;
  pathogen: string;
  onMoleculeEdit?: (newSmiles: string, op: any) => void;
}

interface MatchResult {
  matches: {
    name: string;
    drug_class: string;
    mechanism: string;
    targets: string[];
    year: number;
    similarity: number;
    is_exact: boolean;
  }[];
  best: {
    name: string;
    drug_class: string;
    mechanism: string;
    targets: string[];
    year: number;
    similarity: number;
    is_exact: boolean;
  } | null;
  is_known: boolean;
}

export function Mol3DTheaterWindow(p: Props) {
  const [match, setMatch] = useState<MatchResult | null>(null);
  const [matchExpanded, setMatchExpanded] = useState(false);

  // Poll match-known whenever the SMILES updates. Debounced 250ms so
  // rapid atom edits don't flood the backend.
  useEffect(() => {
    if (!p.smiles) { setMatch(null); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const url = `${p.apiBase}/workbench/molecule/match-known?smiles=${encodeURIComponent(p.smiles!)}&top_k=3`;
        const r = await fetch(url);
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled) setMatch(d);
      } catch {/*noop*/}
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [p.smiles, p.apiBase]);

  // Tag color/label — three states
  const sim = match?.best?.similarity ?? 0;
  const tier = sim >= 0.95 ? "exact" : sim >= 0.65 ? "close" : sim >= 0.30 ? "weak" : "novel";
  const TIER_COLORS = {
    exact:  { fg: "#10b981", bg: "rgba(16,185,129,0.10)", border: "rgba(16,185,129,0.35)", label: "EXACT" },
    close:  { fg: "#0891b2", bg: "rgba(8,145,178,0.10)",  border: "rgba(8,145,178,0.35)",  label: "CLOSE" },
    weak:   { fg: "#ca8a04", bg: "rgba(202,138,4,0.10)",  border: "rgba(202,138,4,0.35)",  label: "WEAK" },
    novel:  { fg: "#7c3aed", bg: "rgba(124,58,237,0.10)", border: "rgba(124,58,237,0.35)", label: "NOVEL" },
  } as const;
  const tc = TIER_COLORS[tier];

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <Mol3D
        apiBase={p.apiBase}
        smiles={p.smiles}
        pathogen={p.pathogen}
        onMoleculeEdit={p.onMoleculeEdit}
      />
      {/* Tag-detection overlay — auto-detects which known antibiotic the
          user (or agent) is converging toward as atoms are added. */}
      {p.smiles && match?.best && (
        <div
          onClick={() => setMatchExpanded((e) => !e)}
          title="Click to expand · top-k known antibiotic matches"
          style={{
            position: "absolute", top: 8, left: 8,
            padding: "5px 10px",
            background: tc.bg,
            border: `1px solid ${tc.border}`,
            borderRadius: 6,
            cursor: "pointer",
            display: "flex", flexDirection: "column", gap: 2,
            fontFamily: "var(--lys-font-body)",
            fontSize: 10.5,
            color: tc.fg,
            backdropFilter: "blur(8px)",
            zIndex: 50,
            maxWidth: matchExpanded ? 320 : 230,
            transition: "max-width 0.20s",
            boxShadow: "0 4px 12px rgba(15,23,42,0.10)",
          }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{
              fontFamily: "var(--lys-font-mono)", fontWeight: 800,
              fontSize: 8.5, letterSpacing: "0.08em",
              padding: "1px 4px", borderRadius: 2,
              background: tc.fg, color: "white",
            }}>{tc.label}</span>
            <span style={{ fontWeight: 700 }}>≈ {match.best.name}</span>
            <span style={{ marginLeft: "auto", fontFamily: "var(--lys-font-mono)",
              fontWeight: 700 }}>
              {(sim * 100).toFixed(0)}%
            </span>
          </div>
          <div style={{ fontSize: 9, opacity: 0.85,
            fontFamily: "var(--lys-font-body)" }}>
            {match.best.drug_class}
          </div>
          {matchExpanded && (
            <>
              <div style={{ fontSize: 9, opacity: 0.85,
                marginTop: 3, paddingTop: 3,
                borderTop: `1px solid ${tc.border}` }}>
                <span style={{ fontWeight: 700 }}>Mechanism:</span> {match.best.mechanism}
              </div>
              <div style={{ fontSize: 9, opacity: 0.85 }}>
                <span style={{ fontWeight: 700 }}>Targets:</span> {match.best.targets.join(", ")}
              </div>
              {match.matches.length > 1 && (
                <div style={{ fontSize: 9, marginTop: 3,
                  paddingTop: 3, borderTop: `1px solid ${tc.border}` }}>
                  <div style={{ opacity: 0.65, fontFamily: "var(--lys-font-mono)",
                    fontSize: 8, letterSpacing: "0.04em",
                    textTransform: "uppercase" }}>also close</div>
                  {match.matches.slice(1).map((m) => (
                    <div key={m.name} style={{ display: "flex", gap: 4 }}>
                      <span style={{ flex: 1 }}>{m.name}</span>
                      <span style={{ fontFamily: "var(--lys-font-mono)" }}>
                        {(m.similarity * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
