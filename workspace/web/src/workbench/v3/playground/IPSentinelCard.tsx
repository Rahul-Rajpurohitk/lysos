/**
 * IPSentinelCard — Service 2 frontend: IP / Novelty Sentinel (agentic).
 *
 * This card does NOT just grade a molecule. "Run IP scan" dispatches
 * the `fto_scan` workflow — an honest prior-art scan, then the agent
 * DESIGNS a novelty-escaping variant. The hero of the card is that
 * variant: a more-patentable molecule, ready to apply with one tap.
 *
 * Backend: /workbench/chem/ip/* (chem_ip.py).
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { Scale, RefreshCw, Trash2, Sparkles, ArrowRight } from "lucide-react";
import { Mol2DThumb } from "./Mol2DThumb";

interface MarketedDrug {
  name: string; smiles: string; drug_class: string;
  first_approval: number; originator: string; ip_status: string;
  similarity: number;
}
interface EscapeVariant {
  variant_smiles: string; modification: string; rationale: string;
  novelty_before: number; novelty_after: number; novelty_delta: number;
  closest_similarity_before: number; closest_similarity_after: number;
  verdict_after: string; improved: boolean;
}
interface FTOReport {
  smiles: string;
  novelty_score: number;
  novelty_tier: "n/a" | "none" | "low" | "low-medium" | "medium" | "good" | "high";
  verdict: string;
  ip_note: string;
  closest_published: { ref: string; similarity: number } | null;
  closest_published_similarity: number;
  closest_marketed_drug: MarketedDrug | null;
  related_marketed_drugs: MarketedDrug[];
  prior_art: {
    corpus_size: number; exact_matches: number;
    near_identical: number; close: number; related: number;
  };
  escape_variant: EscapeVariant | null;
  non_drug_reason?: string | null;
  artifact_id?: string | null;
}
interface SavedReport {
  id: string; title: string | null; payload: FTOReport;
}

interface Props {
  apiBase: string;
  sessionId: string | null;
  smiles: string | null;
  onLoad?: (smiles: string) => void;
}

const SLATE = {
  bg: "rgba(71,85,105,0.06)", bgStrong: "rgba(71,85,105,0.12)",
  border: "rgba(71,85,105,0.26)", fg: "#475569", fgDeep: "#334155",
} as const;
// The agent-action hero uses an emerald accent — it is the payoff.
const ACT = { bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.4)",
  fg: "#059669", fgDeep: "#047857" } as const;

const TIER_COLOR: Record<string, string> = {
  "n/a": "#94a3b8",  // gray — not applicable
  none: "#dc2626", low: "#dc2626", "low-medium": "#d97706",
  medium: "#d97706", good: "#65a30d", high: "#16a34a",
};
const STATUS_COLOR: Record<string, string> = {
  "off-patent": "#16a34a", "on-patent": "#dc2626", investigational: "#d97706",
};

export function IPSentinelCard({ apiBase, sessionId, smiles, onLoad }: Props) {
  const [report, setReport] = useState<FTOReport | null>(null);
  const [saved, setSaved] = useState<SavedReport[]>([]);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<number | undefined>(undefined);

  const refreshSaved = useCallback(async (): Promise<SavedReport[]> => {
    try {
      const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
      const r = await fetch(`${apiBase}/workbench/chem/ip/reports${qs}`);
      if (!r.ok) return [];
      const rows: SavedReport[] = (await r.json()).reports || [];
      setSaved(rows);
      return rows;
    } catch { return []; }
  }, [apiBase, sessionId]);

  useEffect(() => { void refreshSaved(); }, [refreshSaved]);
  useEffect(() => () => { if (pollRef.current) window.clearTimeout(pollRef.current); }, []);

  function runScan() {
    if (!smiles) { setError("Pick or design a candidate first."); return; }
    setError("");
    setScanning(true);
    const beforeIds = new Set(saved.map((s) => s.id));
    window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
      detail: { text: `/wf fto_scan ${JSON.stringify({ smiles, session_id: sessionId })}` },
    }));
    const deadline = Date.now() + 70000;
    const poll = async () => {
      if (Date.now() > deadline) {
        setScanning(false);
        setError("Scan is streaming in the chat workflow — it'll land here when the agent finishes.");
        return;
      }
      const rows = await refreshSaved();
      const fresh = rows.find((x) => !beforeIds.has(x.id));
      if (fresh) {
        setReport({ ...fresh.payload, artifact_id: fresh.id });
        setScanning(false);
        return;
      }
      pollRef.current = window.setTimeout(() => { void poll(); }, 2800);
    };
    pollRef.current = window.setTimeout(() => { void poll(); }, 3200);
  }

  async function deleteReport(id: string) {
    try {
      await fetch(`${apiBase}/workbench/chem/ip/reports/${id}`, { method: "DELETE" });
      setSaved((s) => s.filter((x) => x.id !== id));
      if (report?.artifact_id === id) setReport(null);
    } catch { /* noop */ }
  }

  function applyVariant(smi: string) {
    if (onLoad) onLoad(smi);
    else window.dispatchEvent(new CustomEvent("lysos:auto-slash",
      { detail: { text: `/load ${smi}` } }));
  }

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "transparent", overflow: "hidden", fontFamily: "var(--lys-font-body)",
    }}>
      <div style={{
        padding: "6px 10px", display: "flex", alignItems: "center", gap: 6,
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
        textTransform: "uppercase", color: SLATE.fgDeep,
        borderBottom: `1px solid ${SLATE.border}`,
      }}>
        <Scale size={11} style={{ color: SLATE.fg }} />
        <span>ip / novelty sentinel</span>
        <span style={{ flex: 1 }} />
        {saved.length > 0 && (
          <span style={{ padding: "1px 6px", borderRadius: 999, background: SLATE.bgStrong,
            border: `1px solid ${SLATE.border}`, color: SLATE.fgDeep, fontSize: 9 }}>
            {saved.length} saved</span>
        )}
        <button type="button" onClick={() => void refreshSaved()}
          style={{ border: 0, background: "transparent", cursor: "pointer",
            padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      <div style={{
        padding: "8px 10px", display: "flex", alignItems: "center", gap: 8,
        borderBottom: "1px solid rgba(0,0,0,0.05)",
      }}>
        <button type="button" onClick={runScan} disabled={scanning || !smiles}
          style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "5px 11px", borderRadius: 5, border: 0,
            background: !smiles ? "rgba(0,0,0,0.05)" : SLATE.fg,
            color: !smiles ? "var(--lys-text-faint)" : "white",
            fontSize: 11, fontWeight: 600, cursor: !smiles || scanning ? "not-allowed" : "pointer",
          }}>
          <Scale size={12} />
          {scanning ? "Agent scanning + designing…" : "Run IP scan"}
        </button>
        <span style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
          {scanning ? "prior-art scan → escape-variant design, in chat"
            : smiles ? smiles : "no candidate loaded"}
        </span>
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: SLATE.fgDeep }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!report && !scanning && (
          <Empty msg="Run an IP scan — the agent honestly assesses prior art, then designs a novelty-escaping variant you can apply in one tap. It hands you a more patentable molecule, not a score." />
        )}
        {scanning && !report && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 20,
            textAlign: "center", color: SLATE.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Agent is scanning prior art and designing a more-novel
              variant — streaming in the chat.</div>
          </div>
        )}

        {report && <FTOView apiBase={apiBase} report={report} onApply={applyVariant} />}

        {saved.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
              letterSpacing: "0.06em", textTransform: "uppercase",
              color: "var(--lys-text-faint)", padding: "0 2px 4px" }}>saved IP scans</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {saved.map((rt) => (
                <div key={rt.id} style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "5px 7px",
                  borderRadius: 5,
                  background: report?.artifact_id === rt.id ? SLATE.bgStrong : SLATE.bg,
                  border: `1px solid ${SLATE.border}`,
                }}>
                  <span style={{ width: 7, height: 7, borderRadius: 7, flexShrink: 0,
                    background: TIER_COLOR[rt.payload.novelty_tier] ?? "#9ca3af" }} />
                  <button type="button" onClick={() => setReport({ ...rt.payload, artifact_id: rt.id })}
                    style={{ flex: 1, minWidth: 0, textAlign: "left", border: 0,
                      background: "transparent", cursor: "pointer", padding: 0,
                      fontSize: 10.5, fontWeight: 600, color: "var(--lys-text)",
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {rt.title || "IP scan"}
                  </button>
                  <button type="button" onClick={() => void deleteReport(rt.id)}
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

function FTOView({ apiBase, report, onApply }: {
  apiBase: string; report: FTOReport; onApply: (s: string) => void;
}) {
  const r = report;
  const esc = r.escape_variant;
  const tierCol = TIER_COLOR[r.novelty_tier] ?? "#9ca3af";
  const pa = r.prior_art;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Structure-forward header — candidate molecule + tight verdict */}
      <div style={{ border: `1px solid ${SLATE.border}`, borderRadius: 7,
        background: SLATE.bg, padding: 8,
        display: "flex", alignItems: "center", gap: 10 }}>
        <Mol2DThumb apiBase={apiBase} smiles={r.smiles} w={120} h={90}
          caption="candidate" accent={tierCol} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--lys-text)",
            lineHeight: 1.3 }}>{r.verdict}</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6,
            marginTop: 4, fontFamily: "var(--lys-font-mono)" }}>
            <span style={{ fontSize: 18, fontWeight: 700, color: tierCol,
              lineHeight: 1 }}>{r.novelty_score.toFixed(2)}</span>
            <span style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
              textTransform: "uppercase", letterSpacing: "0.05em" }}>
              novelty · {r.novelty_tier}
            </span>
          </div>
          <div style={{ fontSize: 9, color: "var(--lys-text-faint)", marginTop: 3,
            fontFamily: "var(--lys-font-mono)" }}>
            closest: <span style={{ color: tierCol, fontWeight: 700 }}>
              {r.closest_published_similarity} Tanimoto
            </span>
            {r.closest_published?.ref && ` · ${r.closest_published.ref}`}
          </div>
        </div>
      </div>

      {/* THE AGENT ACTION — original ←→ variant structures, the payoff */}
      {esc && esc.improved && (
        <div style={{ border: `1.5px solid ${ACT.border}`, borderRadius: 7,
          background: ACT.bg, padding: "8px 9px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5,
            fontSize: 10, fontWeight: 700, color: ACT.fgDeep,
            marginBottom: 6 }}>
            <Sparkles size={12} />
            <span>Agent designed a more-novel variant</span>
          </div>
          {/* Side-by-side structures — the visual story */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
            gap: 6, padding: "2px 0 6px" }}>
            <Mol2DThumb apiBase={apiBase} smiles={r.smiles} w={130} h={100}
              caption="original" accent="rgba(71,85,105,0.35)" />
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center",
              gap: 2 }}>
              <ArrowRight size={18} style={{ color: ACT.fg }} />
              <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                color: ACT.fg, fontWeight: 700 }}>
                {esc.novelty_before.toFixed(2)}→{esc.novelty_after.toFixed(2)}
              </span>
            </div>
            <Mol2DThumb apiBase={apiBase} smiles={esc.variant_smiles} w={130} h={100}
              caption="variant" accent={ACT.fg} />
          </div>
          {/* One-line rationale */}
          <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)", lineHeight: 1.4,
            textAlign: "center" }}>
            <strong style={{ color: ACT.fgDeep }}>{esc.modification}</strong>
          </div>
          <button type="button" onClick={() => onApply(esc.variant_smiles)}
            style={{ marginTop: 6, width: "100%", padding: "6px 0", border: 0,
              borderRadius: 5, background: ACT.fg, color: "white",
              fontSize: 10.5, fontWeight: 700, cursor: "pointer" }}>
            Apply this variant → load + re-score
          </button>
        </div>
      )}
      {esc && !esc.improved && (
        <div style={{ fontSize: 9.5, color: "#16a34a", background: "rgba(22,163,74,0.06)",
          border: "1px solid rgba(22,163,74,0.22)", borderRadius: 4, padding: "4px 7px" }}>
          Already structurally novel — no escape edit needed.
        </div>
      )}

      {/* Closest marketed antibiotic — with structure thumbnail */}
      {r.closest_marketed_drug ? (
        <div style={{ border: `1px solid ${SLATE.border}`, borderRadius: 6,
          background: SLATE.bg, padding: 7,
          display: "flex", alignItems: "center", gap: 8 }}>
          <Mol2DThumb apiBase={apiBase} smiles={r.closest_marketed_drug.smiles}
            w={100} h={75} caption={r.closest_marketed_drug.name.toLowerCase()}
            accent={STATUS_COLOR[r.closest_marketed_drug.ip_status]} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--lys-text)" }}>
              {r.closest_marketed_drug.name}
              <span style={{ marginLeft: 6, fontFamily: "var(--lys-font-mono)",
                fontSize: 9, color: SLATE.fgDeep }}>
                {r.closest_marketed_drug.similarity} sim
              </span>
            </div>
            <div style={{ fontSize: 9, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", marginTop: 2 }}>
              {r.closest_marketed_drug.drug_class}
            </div>
            <div style={{ marginTop: 3, display: "inline-block",
              fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
              padding: "1px 5px", borderRadius: 3,
              background: (STATUS_COLOR[r.closest_marketed_drug.ip_status] ?? "#9ca3af") + "22",
              color: STATUS_COLOR[r.closest_marketed_drug.ip_status] ?? "#9ca3af" }}>
              {r.closest_marketed_drug.ip_status}
            </div>
          </div>
        </div>
      ) : null}

      {/* Prior-art density — compact row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 5 }}>
        <Stat label="exact" value={String(pa.exact_matches)}
          color={pa.exact_matches > 0 ? "#dc2626" : "#16a34a"} />
        <Stat label="near-id" value={String(pa.near_identical)}
          color={pa.near_identical > 0 ? "#d97706" : "#65a30d"} />
        <Stat label="close" value={String(pa.close)} />
        <Stat label="related" value={String(pa.related)} />
      </div>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: "rgba(255,255,255,0.6)", border: `1px solid ${SLATE.border}`,
      borderRadius: 4, padding: "3px 4px", textAlign: "center" }}>
      <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
        textTransform: "uppercase", color: "var(--lys-text-faint)" }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
        color: color ?? "var(--lys-text)" }}>{value}</div>
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "center",
      justifyContent: "center", padding: 20, textAlign: "center",
      color: "var(--lys-text-faint)", fontSize: 11 }}>
      <Scale size={22} style={{ opacity: 0.4 }} />
      <div>{msg}</div>
    </div>
  );
}
