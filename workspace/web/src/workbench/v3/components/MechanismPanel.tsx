import { useEffect, useState } from "react";
import { Brain, X, ExternalLink } from "lucide-react";

interface MechanismResponse {
  smiles: string;
  target: string;
  functional_groups: string[];
  nearest_known: { name: string; class: string; similarity: number };
  first_line_targets: any[];
  paragraphs: string[];
}

interface MechanismPanelProps {
  apiBase: string;
  smiles: string | null;
  target: string;
  open: boolean;
  onClose: () => void;
}

export function MechanismPanel(p: MechanismPanelProps) {
  const [data, setData] = useState<MechanismResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!p.open || !p.smiles) {
      setData(null);
      return;
    }
    setLoading(true);
    fetch(`${p.apiBase}/workbench/sandbox/mechanism/${encodeURIComponent(p.smiles)}?target=${p.target}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [p.apiBase, p.smiles, p.target, p.open]);

  if (!p.open) return null;

  return (
    <div style={{
      position: "absolute",
      inset: 0,
      background: "rgba(13, 17, 23, 0.92)",
      backdropFilter: "blur(8px)",
      zIndex: 50,
      padding: 16,
      overflowY: "auto",
    }}>
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Brain size={16} color="var(--lys-accent)" />
          <span style={{
            fontSize: 12,
            color: "var(--lys-accent)",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            fontWeight: 600,
          }}>
            mechanism · {p.target}
          </span>
        </div>
        <button
          onClick={p.onClose}
          style={{
            background: "transparent",
            border: 0,
            color: "var(--lys-text-dim)",
            cursor: "pointer",
            padding: 4,
          }}
        >
          <X size={16} />
        </button>
      </div>

      {loading && <div style={{ color: "var(--lys-text-faint)" }}>analyzing…</div>}

      {data && (
        <>
          <div style={{
            fontFamily: "var(--lys-font-mono)",
            fontSize: 11,
            color: "var(--lys-text-dim)",
            marginBottom: 12,
            wordBreak: "break-all",
          }}>
            {data.smiles}
          </div>

          {data.functional_groups.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, color: "var(--lys-text-faint)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>
                functional groups
              </div>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {data.functional_groups.map((g) => (
                  <span key={g} style={{
                    padding: "2px 8px",
                    fontSize: 11,
                    fontFamily: "var(--lys-font-mono)",
                    background: "rgba(52, 211, 153, 0.12)",
                    color: "#86efac",
                    border: "1px solid rgba(52, 211, 153, 0.25)",
                    borderRadius: 12,
                  }}>{g}</span>
                ))}
              </div>
            </div>
          )}

          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, color: "var(--lys-text-faint)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>
              nearest known antibiotic
            </div>
            <div style={{ fontSize: 13, color: "var(--lys-text)" }}>
              <span style={{ fontFamily: "var(--lys-font-mono)" }}>{data.nearest_known.name}</span>
              <span style={{ color: "var(--lys-text-dim)" }}> · {data.nearest_known.class}</span>
              <span style={{ color: "var(--lys-accent)", marginLeft: 8 }}>
                tanimoto {data.nearest_known.similarity.toFixed(2)}
              </span>
            </div>
          </div>

          <div style={{
            display: "flex",
            flexDirection: "column",
            gap: 12,
            paddingTop: 12,
            borderTop: "1px solid var(--lys-border)",
          }}>
            {data.paragraphs.map((para, i) => (
              <p key={i} style={{
                margin: 0,
                fontSize: 13,
                lineHeight: 1.6,
                color: "var(--lys-text)",
              }}>
                {para}
              </p>
            ))}
          </div>

          <div style={{
            marginTop: 16,
            padding: 8,
            background: "var(--lys-surface)",
            borderRadius: 8,
            fontSize: 11,
            color: "var(--lys-text-faint)",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}>
            <ExternalLink size={11} />
            <span>Reasoning is deterministic from RDKit + first-line therapy knowledge base. The Mechanism agent layers an LLM on top via this same endpoint.</span>
          </div>
        </>
      )}
    </div>
  );
}
