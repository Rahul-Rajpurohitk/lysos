/**
 * KnowledgeHubCard — pathogen command-center panel.
 *
 * One unified card at the top of the Knowledge tab that gives the user
 * (and the agents) an at-a-glance view of:
 *   - Headline + intrinsic features + clinical context
 *   - Top resistance threats (clickable → fires `/escape`)
 *   - Drug-class pressure (which classes already get hammered)
 *   - First-line therapy (what to AVOID being a me-too of)
 *   - Validated targets (clickable → fires `/theater`)
 *   - "View agent brief" toggle to see the same markdown the
 *     Designer/Critic/Editor are reading.
 *
 * Reads /workbench/knowledge/{pathogen}. Refetches on pathogen change.
 */
import { useEffect, useMemo, useState } from "react";

interface ResistanceThreat {
  gene: string;
  mechanism: string;
  drug_classes_affected: string[];
  prevalence?: number | null;
}
interface ClassPressure { drug_class: string; n_genes: number }
interface ValidatedTarget { name: string; pdb_id: string; description: string }
interface KnowledgeBrief {
  pathogen: string;
  full_name: string;
  common_syndromes: string[];
  intrinsic_features: string[];
  empirical: { first_line: string[]; syndromes: string[]; context: string };
  top_resistance: ResistanceThreat[];
  class_pressure: ClassPressure[];
  validated_targets: ValidatedTarget[];
  n_total_resistance_genes: number;
  markdown_brief: string;
  generated_ts: number;
}

interface Props {
  apiBase: string;
  pathogen: string;
  onFireSlash?: (slash: string) => void;
  onLoadPdb?: (pdbId: string) => void;
}

export function KnowledgeHubCard({ apiBase, pathogen, onFireSlash, onLoadPdb }: Props) {
  const [brief, setBrief] = useState<KnowledgeBrief | null>(null);
  const [loading, setLoading] = useState(false);
  const [showBrief, setShowBrief] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true); setErr(null); setBrief(null);
    (async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/knowledge/${encodeURIComponent(pathogen)}`);
        if (!r.ok) {
          setErr(`brief failed: HTTP ${r.status}`);
          return;
        }
        const d = await r.json();
        if (alive) setBrief(d);
      } catch (e: any) {
        if (alive) setErr(e?.message ?? String(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [apiBase, pathogen]);

  const maxPressure = useMemo(() => {
    if (!brief?.class_pressure?.length) return 1;
    return Math.max(...brief.class_pressure.map((c) => c.n_genes));
  }, [brief]);

  if (loading) {
    return (
      <div style={{ padding: 12, fontSize: 11, color: "var(--lys-text-dim)" }}>
        Building {pathogen} brief…
      </div>
    );
  }
  if (err) {
    return (
      <div style={{
        padding: 10, fontSize: 11, color: "#dc2626",
        background: "rgba(220,38,38,0.04)",
        border: "1px solid rgba(220,38,38,0.20)", borderRadius: 6,
      }}>
        Knowledge brief unavailable: {err}
      </div>
    );
  }
  if (!brief) return null;

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 10,
      padding: 12,
      background: "linear-gradient(180deg, rgba(132,88,255,0.04), rgba(132,88,255,0.00))",
      border: "1px solid rgba(132,88,255,0.20)",
      borderLeft: "3px solid #8458ff",
      borderRadius: 6,
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={{
            fontSize: 9, color: "#8458ff", letterSpacing: 1, fontWeight: 700,
            textTransform: "uppercase",
          }}>
            Pathogen command center
          </div>
          <div style={{
            fontSize: 16, fontWeight: 800, color: "var(--lys-text)", marginTop: 1,
          }}>
            {brief.full_name}
          </div>
          {brief.common_syndromes?.length > 0 && (
            <div style={{ fontSize: 11, color: "var(--lys-text-dim)", marginTop: 2 }}>
              {brief.common_syndromes.slice(0, 4).join(" · ")}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
          <button
            onClick={() => setShowBrief((s) => !s)}
            style={{
              fontSize: 9.5, padding: "3px 8px",
              background: showBrief ? "#8458ff" : "white",
              color: showBrief ? "white" : "#8458ff",
              border: "1px solid #8458ff",
              borderRadius: 3, cursor: "pointer", fontWeight: 600,
            }}
            title="Toggle the markdown brief that Designer/Critic/Editor agents see"
          >
            {showBrief ? "Hide" : "View"} agent brief
          </button>
          <button
            onClick={() => onFireSlash?.(`/explain ${pathogen}`)}
            style={{
              fontSize: 9.5, padding: "3px 8px",
              background: "white", color: "var(--lys-text)",
              border: "1px solid rgba(0,0,0,0.10)",
              borderRadius: 3, cursor: "pointer", fontWeight: 600,
            }}
          >
            /explain
          </button>
        </div>
      </div>

      {/* Clinical context strip */}
      {brief.empirical?.context && (
        <div style={{
          padding: "6px 8px", fontSize: 10.5,
          background: "rgba(245,158,11,0.06)",
          borderLeft: "2px solid #f59e0b",
          color: "var(--lys-text-dim)",
          lineHeight: 1.4,
        }}>
          <strong style={{ color: "#f59e0b" }}>Context · </strong>
          {brief.empirical.context}
        </div>
      )}

      {/* Quick stats grid */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6,
      }}>
        <Stat label="Resistance genes"  value={brief.n_total_resistance_genes} />
        <Stat label="Drug classes hit"  value={brief.class_pressure.length} />
        <Stat label="First-line drugs"  value={brief.empirical.first_line?.length ?? 0} />
        <Stat label="Validated targets" value={brief.validated_targets.length} />
      </div>

      {/* Two-column body */}
      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10,
      }}>
        {/* LEFT: Top resistance threats */}
        <Section title={`Top resistance threats · ${pathogen}`} accent="#dc2626">
          {brief.top_resistance.length === 0 ? (
            <Empty>No resistance threats catalogued.</Empty>
          ) : brief.top_resistance.slice(0, 6).map((g, i) => {
            // Strip "/" + alias halves so "mecA / PBP2a" → "mecA" — first
            // canonical gene token is what `/explain` expects.
            const geneToken = (g.gene || "").split(/\s*\/\s*|\s+/)[0];
            return (
            <div key={i} style={{
              fontSize: 10.5, padding: "5px 7px",
              background: "white", border: "1px solid rgba(0,0,0,0.06)",
              borderLeft: "2px solid #dc2626", borderRadius: 3,
              cursor: onFireSlash ? "pointer" : "default",
            }}
              onClick={() => onFireSlash?.(`/explain ${geneToken}`)}
              title={onFireSlash ? `Click to /explain ${geneToken}` : ""}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong style={{ color: "#dc2626", fontFamily: "var(--lys-font-mono)" }}>{g.gene}</strong>
                {g.drug_classes_affected.length > 0 && (
                  <span style={{
                    fontSize: 9, color: "var(--lys-text-faint)",
                    fontFamily: "var(--lys-font-mono)",
                  }}>
                    +{g.drug_classes_affected.length}
                  </span>
                )}
              </div>
              {g.mechanism && (
                <div style={{ fontSize: 10, color: "var(--lys-text-dim)", marginTop: 1 }}>
                  {g.mechanism}
                </div>
              )}
              {g.drug_classes_affected.length > 0 && (
                <div style={{ fontSize: 9, color: "var(--lys-text-faint)", marginTop: 2 }}>
                  Hits: {g.drug_classes_affected.slice(0, 2).join(" · ")}
                  {g.drug_classes_affected.length > 2 && ` +${g.drug_classes_affected.length - 2}`}
                </div>
              )}
            </div>
          );
          })}
        </Section>

        {/* RIGHT: Drug-class pressure */}
        <Section title="Drug-class pressure" accent="#f59e0b">
          {brief.class_pressure.length === 0 ? (
            <Empty>No class pressure mapped.</Empty>
          ) : brief.class_pressure.slice(0, 6).map((c, i) => {
            const pct = (c.n_genes / maxPressure) * 100;
            return (
              <div key={i} style={{ fontSize: 10.5 }}>
                <div style={{
                  display: "flex", justifyContent: "space-between", marginBottom: 2,
                }}>
                  <span style={{ color: "var(--lys-text)" }}>{c.drug_class}</span>
                  <span style={{
                    fontFamily: "var(--lys-font-mono)", color: "#f59e0b", fontWeight: 700,
                  }}>{c.n_genes}</span>
                </div>
                <div style={{
                  height: 4, background: "rgba(0,0,0,0.05)", borderRadius: 2,
                  overflow: "hidden",
                }}>
                  <div style={{
                    width: `${pct}%`, height: "100%",
                    background: "linear-gradient(90deg, #f59e0b, #dc2626)",
                  }} />
                </div>
              </div>
            );
          })}
        </Section>
      </div>

      {/* First-line therapy + validated targets */}
      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10,
      }}>
        <Section title="First-line therapy · avoid me-toos" accent="#3b82f6">
          {(brief.empirical.first_line ?? []).length === 0 ? (
            <Empty>No first-line guidance.</Empty>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {brief.empirical.first_line.slice(0, 8).map((d, i) => (
                <span key={i}
                  onClick={() => onFireSlash?.(`/explain ${d.split(/\s/)[0]}`)}
                  style={{
                    fontSize: 10, padding: "3px 7px",
                    background: "rgba(59,130,246,0.06)",
                    color: "#3b82f6",
                    border: "1px solid rgba(59,130,246,0.25)",
                    borderRadius: 3, cursor: onFireSlash ? "pointer" : "default",
                    fontFamily: "var(--lys-font-mono)",
                  }}
                >
                  {d}
                </span>
              ))}
            </div>
          )}
        </Section>

        <Section title="Validated targets · pockets" accent="#10b981">
          {brief.validated_targets.length === 0 ? (
            <Empty>No validated PDBs catalogued.</Empty>
          ) : brief.validated_targets.map((t, i) => (
            <div key={i}
              onClick={() => {
                onLoadPdb?.(t.pdb_id);
                onFireSlash?.(`/theater ${t.pdb_id}`);
              }}
              style={{
                fontSize: 10.5, padding: "5px 7px",
                background: "white", border: "1px solid rgba(0,0,0,0.06)",
                borderLeft: "2px solid #10b981", borderRadius: 3,
                cursor: "pointer",
              }}
              title={`Click to load ${t.pdb_id} into the 3D theater`}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong style={{ color: "var(--lys-text)" }}>{t.name}</strong>
                <span style={{
                  fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
                  color: "#10b981", fontWeight: 700,
                }}>{t.pdb_id}</span>
              </div>
              {t.description && (
                <div style={{ fontSize: 10, color: "var(--lys-text-dim)", marginTop: 1 }}>
                  {t.description}
                </div>
              )}
            </div>
          ))}
        </Section>
      </div>

      {/* Agent brief preview */}
      {showBrief && (
        <div style={{
          marginTop: 4,
          padding: 10,
          background: "rgba(0,0,0,0.02)",
          border: "1px solid rgba(0,0,0,0.06)",
          borderRadius: 4,
          maxHeight: 280, overflowY: "auto",
        }}>
          <div style={{
            fontSize: 9, color: "var(--lys-text-faint)", letterSpacing: 0.5,
            textTransform: "uppercase", marginBottom: 6, fontWeight: 600,
          }}>
            Agent brief · injected into Designer / Critic / Editor / Strategist prompts
          </div>
          <pre style={{
            fontFamily: "var(--lys-font-mono)", fontSize: 10.5,
            color: "var(--lys-text-dim)", lineHeight: 1.5,
            whiteSpace: "pre-wrap", margin: 0,
          }}>{brief.markdown_brief}</pre>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div style={{
      padding: "6px 8px", background: "white",
      border: "1px solid rgba(0,0,0,0.06)", borderRadius: 4,
    }}>
      <div style={{
        fontSize: 9, color: "var(--lys-text-faint)",
        letterSpacing: 0.4, textTransform: "uppercase", fontWeight: 600,
      }}>{label}</div>
      <div style={{
        fontSize: 18, fontWeight: 800, color: "var(--lys-text)",
        fontFamily: "var(--lys-font-mono)", lineHeight: 1.0, marginTop: 2,
      }}>{value}</div>
    </div>
  );
}

function Section({ title, accent, children }: { title: string; accent: string; children: any }) {
  return (
    <div>
      <div style={{
        fontSize: 9, color: accent, fontWeight: 700, letterSpacing: 0.6,
        textTransform: "uppercase", marginBottom: 4,
      }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {children}
      </div>
    </div>
  );
}

function Empty({ children }: { children: any }) {
  return (
    <div style={{
      fontSize: 10, fontStyle: "italic", color: "var(--lys-text-faint)",
      padding: "4px 0",
    }}>{children}</div>
  );
}

export default KnowledgeHubCard;
