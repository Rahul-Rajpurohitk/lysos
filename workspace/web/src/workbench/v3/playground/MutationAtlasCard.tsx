/**
 * MutationAtlasCard — known clinical resistance mutations for the
 * currently-selected target PDB, rendered as a position strip.
 *
 * Each mutation is colored by its drug class. The strip is sized to
 * fit the residue range; hovering shows wt → mutant + class.
 * Click a mutation → fires `/explain <gene>` so the user gets context.
 */
import { useEffect, useState, useMemo } from "react";

interface Mutation {
  wt: string;
  position: number;
  mutant: string;
  drug_class?: string;
  source?: string | null;
  freq?: number | null;
}

interface AtlasResponse {
  pdb_id: string;
  target_name: string;
  pathogen: string;
  n_mutations: number;
  mutations: Mutation[];
}

interface Props {
  apiBase: string;
  pdbId: string | null;
  onFireSlash?: (slash: string) => void;
}

const CLASS_COLORS: Record<string, string> = {
  ceftaroline: "#0ea5e9",
  all_beta_lactams: "#dc2626",
  carbapenems: "#7c3aed",
  oxacillin: "#f59e0b",
  methicillin: "#10b981",
  vancomycin: "#3b82f6",
  daptomycin: "#ec4899",
  linezolid: "#84cc16",
  rifampin: "#f97316",
};

function colorForClass(cls?: string): string {
  if (!cls) return "#9ca3af";
  if (CLASS_COLORS[cls]) return CLASS_COLORS[cls];
  // Hash to a stable hue
  let h = 0;
  for (let i = 0; i < cls.length; i++) h = (h * 31 + cls.charCodeAt(i)) % 360;
  return `hsl(${h}, 55%, 50%)`;
}

export function MutationAtlasCard({ apiBase, pdbId, onFireSlash }: Props) {
  const [data, setData] = useState<AtlasResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState<Mutation | null>(null);

  useEffect(() => {
    if (!pdbId) { setData(null); return; }
    let alive = true;
    setLoading(true);
    (async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/knowledge/mutations/${encodeURIComponent(pdbId)}`);
        if (!r.ok) return;
        const d = await r.json();
        if (alive) setData(d);
      } catch {/* offline */}
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [apiBase, pdbId]);

  const { posMin, posMax, byClass } = useMemo(() => {
    if (!data?.mutations?.length) return { posMin: 0, posMax: 0, byClass: {} as Record<string, number> };
    let lo = Infinity, hi = -Infinity;
    const classes: Record<string, number> = {};
    for (const m of data.mutations) {
      if (m.position < lo) lo = m.position;
      if (m.position > hi) hi = m.position;
      const c = m.drug_class || "unknown";
      classes[c] = (classes[c] || 0) + 1;
    }
    return { posMin: lo, posMax: hi, byClass: classes };
  }, [data]);

  if (!pdbId) {
    return (
      <div style={{ padding: 12, fontSize: 11, color: "var(--lys-text-faint)", fontStyle: "italic" }}>
        Pick a target PDB to load its mutation atlas.
      </div>
    );
  }
  if (loading) {
    return <div style={{ padding: 12, fontSize: 11, color: "var(--lys-text-dim)" }}>Loading mutation atlas…</div>;
  }
  if (!data || data.n_mutations === 0) {
    return (
      <div style={{ padding: 12, fontSize: 11, color: "var(--lys-text-faint)", fontStyle: "italic" }}>
        No curated clinical mutations on file for {pdbId}.
      </div>
    );
  }

  const range = Math.max(1, posMax - posMin);
  return (
    <div style={{ padding: 8 }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "flex-start",
        marginBottom: 6,
      }}>
        <div>
          <div style={{
            fontSize: 9, color: "var(--lys-text-faint)", textTransform: "uppercase",
            letterSpacing: 0.6, fontWeight: 600,
          }}>
            {data.target_name} · {data.pathogen} · {data.pdb_id}
          </div>
          <div style={{ fontSize: 12.5, color: "var(--lys-text)", fontWeight: 700, marginTop: 1 }}>
            {data.n_mutations} curated clinical mutations · residues {posMin}–{posMax}
          </div>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, maxWidth: 320, justifyContent: "flex-end" }}>
          {Object.entries(byClass).slice(0, 6).map(([cls, n]) => (
            <span key={cls} style={{
              fontSize: 9, padding: "2px 6px", borderRadius: 3,
              background: colorForClass(cls) + "22",
              color: colorForClass(cls),
              border: `1px solid ${colorForClass(cls)}55`,
              fontFamily: "var(--lys-font-mono)", fontWeight: 600,
            }}>
              {cls.slice(0, 18)} · {n}
            </span>
          ))}
        </div>
      </div>
      {/* Position strip */}
      <div style={{
        position: "relative", height: 36, background: "rgba(0,0,0,0.03)",
        borderRadius: 4, border: "1px solid rgba(0,0,0,0.06)",
      }}>
        {data.mutations.map((m, i) => {
          const left = ((m.position - posMin) / range) * 100;
          return (
            <button
              key={i}
              onClick={() => onFireSlash?.(`/escape ${m.position}`)}
              onMouseEnter={() => setHover(m)}
              onMouseLeave={() => setHover(null)}
              title={`${m.wt}${m.position}${m.mutant} · ${m.drug_class || "unknown"}${m.source ? ` · ${m.source}` : ""}`}
              style={{
                position: "absolute", left: `calc(${left}% - 6px)`, top: 6,
                width: 12, height: 24, borderRadius: 3,
                background: colorForClass(m.drug_class),
                border: hover === m ? "2px solid black" : "1px solid white",
                cursor: "pointer", padding: 0,
              }}
            />
          );
        })}
        <span style={{
          position: "absolute", left: 4, bottom: 2, fontSize: 8,
          color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)",
        }}>{posMin}</span>
        <span style={{
          position: "absolute", right: 4, bottom: 2, fontSize: 8,
          color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)",
        }}>{posMax}</span>
      </div>
      {/* Hover detail */}
      {hover && (
        <div style={{
          marginTop: 6, padding: "5px 8px",
          background: colorForClass(hover.drug_class) + "10",
          border: `1px solid ${colorForClass(hover.drug_class)}55`,
          borderLeft: `3px solid ${colorForClass(hover.drug_class)}`,
          borderRadius: 4, fontSize: 11,
        }}>
          <strong style={{ fontFamily: "var(--lys-font-mono)", color: colorForClass(hover.drug_class) }}>
            {hover.wt}{hover.position}{hover.mutant}
          </strong>
          <span style={{ marginLeft: 8, color: "var(--lys-text-dim)" }}>
            {hover.drug_class || "unknown class"}
          </span>
          {hover.source && (
            <span style={{ marginLeft: 8, color: "var(--lys-text-faint)" }}>
              · {hover.source}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export default MutationAtlasCard;
