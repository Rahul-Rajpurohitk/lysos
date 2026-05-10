/**
 * PathogenMatrixCard — 8 pathogens × top 12 drug classes pressure matrix.
 *
 * Each cell intensity = number of resistance genes in that pathogen
 * that hit that drug class. Red = high pressure (avoid me-too here),
 * neutral = open territory.
 *
 * Click a row → switch the active pathogen.
 * Click a cell → fire `/wf discover_and_assess pathogen=X` skewed
 * away from that drug class.
 */
import { useEffect, useState, useMemo } from "react";

interface MatrixRow {
  pathogen: string;
  full_name: string;
  class_pressure: Record<string, number>;
  n_total_genes: number;
  first_line_count: number;
  validated_target_count: number;
}

interface MatrixResponse {
  rows: MatrixRow[];
  columns: string[];
  column_totals: Record<string, number>;
  n_pathogens: number;
}

interface Props {
  apiBase: string;
  activePathogen: string;
  onPathogenChange?: (p: string) => void;
}

export function PathogenMatrixCard({ apiBase, activePathogen, onPathogenChange }: Props) {
  const [data, setData] = useState<MatrixResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    (async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/knowledge/matrix`);
        if (!r.ok) return;
        const d = await r.json();
        if (alive) setData(d);
      } catch {/* offline */}
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [apiBase]);

  const maxValue = useMemo(() => {
    if (!data) return 1;
    let m = 0;
    for (const row of data.rows) {
      for (const c of data.columns) {
        const v = row.class_pressure[c] || 0;
        if (v > m) m = v;
      }
    }
    return m || 1;
  }, [data]);

  if (loading || !data) {
    return (
      <div style={{ padding: 12, fontSize: 11, color: "var(--lys-text-dim)" }}>
        Loading pressure matrix…
      </div>
    );
  }

  const cellSize = 22;
  const labelW = 92;
  return (
    <div style={{ padding: 8 }}>
      <div style={{
        fontSize: 9, color: "var(--lys-text-faint)", textTransform: "uppercase",
        letterSpacing: 0.6, marginBottom: 6, fontWeight: 600,
      }}>
        {data.n_pathogens} pathogens · {data.columns.length} drug classes ·
        red = avoid me-toos · click pathogen → switch
      </div>
      {/* Scrollable wrapper since the column labels can be long */}
      <div style={{ overflowX: "auto", paddingBottom: 4 }}>
        <div style={{ display: "inline-block" }}>
          {/* Column headers */}
          <div style={{ display: "flex", alignItems: "flex-end", marginLeft: labelW }}>
            {data.columns.map((c, i) => (
              <div
                key={c}
                title={c}
                style={{
                  width: cellSize, fontSize: 8.5,
                  fontFamily: "var(--lys-font-mono)",
                  color: hover?.col === i ? "#dc2626" : "var(--lys-text-dim)",
                  whiteSpace: "nowrap",
                  transform: "rotate(-50deg)", transformOrigin: "left bottom",
                  height: 80, paddingLeft: 4, paddingBottom: 4,
                  fontWeight: hover?.col === i ? 700 : 500,
                }}
              >
                {c.length > 18 ? c.slice(0, 17) + "…" : c}
              </div>
            ))}
          </div>
          {/* Rows */}
          {data.rows.map((row, ri) => {
            const active = row.pathogen === activePathogen;
            return (
              <div key={row.pathogen} style={{
                display: "flex", alignItems: "center",
                background: active ? "rgba(132,88,255,0.06)" : "transparent",
              }}>
                <button
                  onClick={() => onPathogenChange?.(row.pathogen)}
                  title={`${row.full_name} · ${row.n_total_genes} resistance genes · ${row.first_line_count} first-line drugs`}
                  style={{
                    width: labelW, padding: "3px 6px",
                    fontSize: 10.5, fontFamily: "var(--lys-font-mono)",
                    color: active ? "#8458ff" : "var(--lys-text)",
                    fontWeight: active ? 700 : 500,
                    background: "transparent", border: 0, textAlign: "left",
                    cursor: "pointer", whiteSpace: "nowrap", overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {active && "◆ "}{row.pathogen}
                </button>
                {data.columns.map((c, ci) => {
                  const v = row.class_pressure[c] || 0;
                  const intensity = v / maxValue;
                  const isHover = hover?.row === ri && hover?.col === ci;
                  return (
                    <div
                      key={c}
                      onMouseEnter={() => setHover({ row: ri, col: ci })}
                      onMouseLeave={() => setHover(null)}
                      title={`${row.pathogen} · ${c} · ${v} resistance gene${v === 1 ? "" : "s"}`}
                      style={{
                        width: cellSize, height: cellSize,
                        background: v === 0
                          ? "rgba(0,0,0,0.02)"
                          : `rgba(220, 38, 38, ${0.15 + intensity * 0.6})`,
                        border: isHover ? "1px solid #dc2626" : "1px solid white",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: 9, fontFamily: "var(--lys-font-mono)",
                        fontWeight: 700,
                        color: intensity > 0.4 ? "white" : "var(--lys-text-dim)",
                      }}
                    >
                      {v > 0 ? v : ""}
                    </div>
                  );
                })}
                <div style={{
                  marginLeft: 6, fontSize: 9.5, color: "var(--lys-text-faint)",
                  fontFamily: "var(--lys-font-mono)", whiteSpace: "nowrap",
                }}>
                  Σ{row.n_total_genes} · {row.first_line_count} first-line · {row.validated_target_count} PDBs
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default PathogenMatrixCard;
