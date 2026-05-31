/**
 * GeneratorCard — Service 4 frontend: de-novo + lead-opt molecular generation.
 *
 * The Designer agent generates REAL, valid, novel molecules (BRICS fragment
 * recombination locally; GenMol on MI300X in Act II), scored + ranked by the
 * same 12-axis stack. This card shows the generated structures as a grid of
 * thumbnails — impactful chemistry, not text — each one-tap applyable.
 *
 * Backend: /workbench/chem/generate (chem_generate.py).
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { Sparkles, RefreshCw, Trash2, Atom, Wand2 } from "lucide-react";
import { Mol2DThumb } from "./Mol2DThumb";

interface GenCandidate {
  smiles: string;
  composite: number | null;
  novelty_vs_seed: number | null;
}
interface GenRun {
  seed: string | null;
  pathogen: string;
  engine: "brics" | "genmol";
  n_generated: number;
  n_returned: number;
  candidates: GenCandidate[];
  elapsed_s: number;
  artifact_id?: string | null;
}
interface SavedRun { id: string; title: string | null; payload: GenRun; }

interface Props {
  apiBase: string;
  sessionId: string | null;
  smiles: string | null;          // current candidate = optional lead-opt seed
  pathogen?: string | null;
  onLoad?: (smiles: string) => void;
}

// Violet "creation" accent — distinct from the other services.
const VIO = {
  bg: "rgba(124,58,237,0.06)", bgStrong: "rgba(124,58,237,0.13)",
  border: "rgba(124,58,237,0.28)", fg: "#7c3aed", fgDeep: "#6d28d9",
} as const;

function compositeColor(c: number | null): string {
  if (c == null) return "#94a3b8";
  if (c >= 0.7) return "#16a34a";
  if (c >= 0.55) return "#65a30d";
  if (c >= 0.4) return "#d97706";
  return "#dc2626";
}

export function GeneratorCard({ apiBase, sessionId, smiles, pathogen, onLoad }: Props) {
  const [run, setRun] = useState<GenRun | null>(null);
  const [saved, setSaved] = useState<SavedRun[]>([]);
  const [busy, setBusy] = useState<"" | "denovo" | "leadopt">("");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const refreshSaved = useCallback(async () => {
    if (!sessionId) return;
    try {
      const r = await fetch(`${apiBase}/workbench/chem/generate/runs?session_id=${sessionId}`);
      if (r.ok) setSaved((await r.json()).items ?? []);
    } catch { /* ignore */ }
  }, [apiBase, sessionId]);

  useEffect(() => { void refreshSaved(); }, [refreshSaved]);
  useEffect(() => () => abortRef.current?.abort(), []);

  async function generate(mode: "denovo" | "leadopt") {
    setError(null);
    setBusy(mode);
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const r = await fetch(`${apiBase}/workbench/chem/generate`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          seed: mode === "leadopt" ? smiles : null,
          n: 8,
          pathogen: pathogen || "MRSA",
          session_id: sessionId,
          save: true,
        }),
        signal: ac.signal,
      });
      if (!r.ok) { setError(`generation failed (HTTP ${r.status})`); return; }
      const d: GenRun = await r.json();
      setRun(d);
      void refreshSaved();
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("generation error");
    } finally {
      setBusy("");
    }
  }

  async function deleteRun(id: string) {
    await fetch(`${apiBase}/workbench/chem/generate/runs/${id}`, { method: "DELETE" });
    await refreshSaved();
    if (run?.artifact_id === id) setRun(null);
  }

  function apply(smi: string) {
    if (onLoad) onLoad(smi);
    else window.dispatchEvent(new CustomEvent("lysos:auto-slash",
      { detail: { text: `/load ${smi}` } }));
  }

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", background: "transparent", overflow: "hidden",
      fontFamily: "var(--lys-font-body)" }}>
      {/* header */}
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: VIO.fgDeep,
        borderBottom: `1px solid ${VIO.border}` }}>
        <Atom size={11} style={{ color: VIO.fg }} />
        <span>generator · de-novo + lead-opt</span>
        <span style={{ flex: 1 }} />
        {saved.length > 0 && (
          <span style={{ padding: "1px 6px", borderRadius: 999, background: VIO.bgStrong,
            border: `1px solid ${VIO.border}`, color: VIO.fgDeep, fontSize: 9 }}>
            {saved.length} runs</span>
        )}
        <button type="button" onClick={() => void refreshSaved()}
          style={{ border: 0, background: "transparent", cursor: "pointer",
            padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      {/* actions */}
      <div style={{ padding: "8px 10px", display: "flex", gap: 6,
        borderBottom: "1px solid rgba(0,0,0,0.05)" }}>
        <button type="button" onClick={() => generate("denovo")} disabled={!!busy}
          style={{ display: "inline-flex", alignItems: "center", gap: 5,
            padding: "5px 10px", borderRadius: 5, border: 0, background: VIO.fg,
            color: "white", fontSize: 10.5, fontWeight: 600,
            cursor: busy ? "not-allowed" : "pointer", opacity: busy ? 0.6 : 1 }}>
          <Sparkles size={12} />
          {busy === "denovo" ? "Generating…" : "Generate de-novo"}
        </button>
        <button type="button" onClick={() => generate("leadopt")}
          disabled={!!busy || !smiles}
          title={smiles ? "Optimize the current candidate" : "Load a candidate first"}
          style={{ display: "inline-flex", alignItems: "center", gap: 5,
            padding: "5px 10px", borderRadius: 5,
            border: `1px solid ${VIO.border}`,
            background: !smiles ? "rgba(0,0,0,0.04)" : "white",
            color: !smiles ? "var(--lys-text-faint)" : VIO.fgDeep,
            fontSize: 10.5, fontWeight: 600,
            cursor: busy || !smiles ? "not-allowed" : "pointer" }}>
          <Wand2 size={12} />
          {busy === "leadopt" ? "Optimizing…" : "Optimize lead"}
        </button>
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!run && !busy && (
          <Empty msg="Generate real, valid, novel molecules — de-novo from an antibiotic-fragment pool, or lead-optimized from the current candidate. Every structure is RDKit-validated, drug-like-gated, and scored." />
        )}
        {busy && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 20,
            textAlign: "center", color: VIO.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Generating + scoring real candidates…</div>
          </div>
        )}

        {run && <GenView apiBase={apiBase} run={run} onApply={apply} />}

        {saved.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
              letterSpacing: "0.06em", textTransform: "uppercase",
              color: "var(--lys-text-faint)", padding: "0 2px 4px" }}>saved runs</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {saved.map((s) => (
                <div key={s.id} style={{ display: "flex", alignItems: "center",
                  gap: 6, padding: "5px 7px", borderRadius: 5,
                  background: run?.artifact_id === s.id ? VIO.bgStrong : VIO.bg,
                  border: `1px solid ${VIO.border}` }}>
                  <button type="button"
                    onClick={() => setRun({ ...s.payload, artifact_id: s.id })}
                    style={{ flex: 1, minWidth: 0, textAlign: "left", border: 0,
                      background: "transparent", cursor: "pointer", padding: 0,
                      fontSize: 10.5, fontWeight: 600, color: "var(--lys-text)",
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {s.title || "generation run"}
                  </button>
                  <button type="button" onClick={() => void deleteRun(s.id)}
                    style={{ border: 0, background: "transparent", cursor: "pointer",
                      padding: 0, color: "var(--lys-text-faint)" }}>
                    <Trash2 size={11} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function GenView({ apiBase, run, onApply }: {
  apiBase: string; run: GenRun; onApply: (s: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* run summary */}
      <div style={{ display: "flex", alignItems: "center", gap: 8,
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)", color: VIO.fgDeep,
        background: VIO.bg, border: `1px solid ${VIO.border}`,
        borderRadius: 6, padding: "5px 8px" }}>
        <span style={{ fontWeight: 700, textTransform: "uppercase" }}>
          {run.seed ? "lead-opt" : "de-novo"}
        </span>
        <span style={{ color: "var(--lys-text-faint)" }}>·</span>
        <span>{run.engine} engine</span>
        <span style={{ flex: 1 }} />
        <span style={{ color: "var(--lys-text-faint)" }}>
          {run.n_generated} gen → {run.n_returned} kept · {run.elapsed_s}s
        </span>
      </div>

      {/* candidate grid — the visual payoff */}
      <div style={{ display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))", gap: 8 }}>
        {run.candidates.map((c, i) => {
          const col = compositeColor(c.composite);
          return (
            <div key={i} style={{ display: "flex", flexDirection: "column",
              gap: 4, padding: 6, borderRadius: 7, background: "white",
              border: `1px solid ${VIO.border}` }}>
              <Mol2DThumb apiBase={apiBase} smiles={c.smiles} w={116} h={92}
                accent={col} title={c.smiles} />
              <div style={{ display: "flex", alignItems: "center", gap: 4,
                fontFamily: "var(--lys-font-mono)" }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: col }}>
                  {c.composite != null ? c.composite.toFixed(2) : "—"}
                </span>
                <span style={{ fontSize: 7.5, color: "var(--lys-text-faint)",
                  textTransform: "uppercase" }}>composite</span>
                {c.novelty_vs_seed != null && (
                  <span style={{ fontSize: 7.5, color: VIO.fg, marginLeft: "auto" }}>
                    nov {c.novelty_vs_seed.toFixed(2)}
                  </span>
                )}
              </div>
              {/* composite bar */}
              <div style={{ height: 5, borderRadius: 3, background: "rgba(0,0,0,0.06)",
                overflow: "hidden" }}>
                <div style={{ width: `${Math.round((c.composite ?? 0) * 100)}%`,
                  height: "100%", background: col }} />
              </div>
              <button type="button" onClick={() => onApply(c.smiles)}
                style={{ width: "100%", padding: "4px 0", border: 0, borderRadius: 4,
                  background: VIO.fg, color: "white", fontSize: 9.5, fontWeight: 700,
                  cursor: "pointer" }}>
                Apply
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6,
      alignItems: "center", justifyContent: "center", padding: 20,
      textAlign: "center", color: "var(--lys-text-faint)", fontSize: 11 }}>
      <Atom size={22} style={{ opacity: 0.4 }} />
      <div>{msg}</div>
    </div>
  );
}
