/**
 * KnowledgeChampionPane — current reigning champion for a pathogen.
 *
 * Lives in the Knowledge container; reuses the chat ChampionCard
 * component for visual consistency. Refetches on pathogen change.
 */
import { useEffect, useState } from "react";
import ChampionCard from "../components/chat/ChampionCard";

interface ChampionRecord {
  pathogen: string;
  smiles: string;
  composite: number | null;
  robustness: number | null;
  fitness: number | null;
  scores?: Record<string, number>;
  rationale?: string;
}

interface Props {
  apiBase: string;
  pathogen: string;
  onLoadSmiles?: (smiles: string) => void;
}

export function KnowledgeChampionPane({ apiBase, pathogen, onLoadSmiles }: Props) {
  const [champ, setChamp] = useState<ChampionRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    (async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/champion/${encodeURIComponent(pathogen)}`);
        if (!r.ok) return;
        const d = await r.json();
        if (alive) setChamp(d.champion ?? null);
      } catch {/* offline */}
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [apiBase, pathogen, reloadTick]);

  // Auto-refresh when a workflow ends (the auto-promote fires there)
  useEffect(() => {
    const onWfDone = () => setReloadTick((t) => t + 1);
    window.addEventListener("lysos:workflow-done", onWfDone);
    window.addEventListener("lysos:champion-changed", onWfDone);
    return () => {
      window.removeEventListener("lysos:workflow-done", onWfDone);
      window.removeEventListener("lysos:champion-changed", onWfDone);
    };
  }, []);

  return (
    <div style={{ padding: 8 }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 8,
      }}>
        <div style={{
          fontSize: 10, color: "#6e7891", textTransform: "uppercase",
          letterSpacing: 0.8, fontWeight: 600,
        }}>
          {loading ? "Loading…" : champ ? "Current best · auto-promoted by workflows" : "No champion yet"}
        </div>
        <button
          onClick={() => setReloadTick((t) => t + 1)}
          style={{
            fontSize: 10, padding: "2px 8px",
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.10)",
            borderRadius: 3, color: "#a8b5ce", cursor: "pointer",
          }}
        >
          Refresh
        </button>
      </div>
      <ChampionCard
        msg={{ data: { mode: "show", champion: champ, pathogen } }}
        onLoadSmiles={onLoadSmiles}
      />
    </div>
  );
}

export default KnowledgeChampionPane;
