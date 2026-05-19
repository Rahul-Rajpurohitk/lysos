/**
 * IPSentinelCard — Service 2 frontend: IP / FTO Sentinel.
 *
 * "Run FTO scan" dispatches the `fto_scan` workflow (similarity scan →
 * IP-analyst review) so the agent streams visibly in the chat, then
 * polls for the persisted report and opens it.
 *
 * Renders the freedom-to-operate verdict: freedom score, claim-overlap
 * risk, the closest known antibiotic + its patent status, the closest
 * LIVE-patent analog (the IP to clear), prior-art density, the panel
 * hit list and the IP-analyst narrative — plus a CRUD shelf.
 *
 * Backend: /workbench/chem/ip/* (chem_ip.py).
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { Scale, RefreshCw, Trash2, ShieldCheck, AlertTriangle } from "lucide-react";

interface PanelHit {
  name: string; smiles: string; drug_class: string; status: string;
  patent: string; assignee: string; year: number; similarity: number;
}
interface FTOReport {
  smiles: string;
  freedom_score: number;
  verdict: string;
  claim_overlap_risk: "low" | "low-medium" | "medium" | "high";
  closest_analog: PanelHit | null;
  closest_live_patent_analog: PanelHit | null;
  top_panel_analogs: PanelHit[];
  closest_published_structure: { ref: string; similarity: number } | null;
  prior_art: {
    corpus_size: number; near_identical_092: number;
    similar_070: number; related_055: number;
  };
  narrative?: { assessment: string; recommended_action: string; model: string };
  artifact_id?: string | null;
}
interface SavedReport {
  id: string; smiles: string | null; title: string | null;
  updated_at: number; payload: FTOReport;
}

interface Props {
  apiBase: string;
  sessionId: string | null;
  smiles: string | null;
}

// Slate-blue "legal / IP" accent.
const SLATE = {
  bg: "rgba(71,85,105,0.06)",
  bgStrong: "rgba(71,85,105,0.12)",
  border: "rgba(71,85,105,0.26)",
  fg: "#475569",
  fgDeep: "#334155",
} as const;

const RISK_COLOR: Record<string, string> = {
  low: "#16a34a", "low-medium": "#65a30d", medium: "#d97706", high: "#dc2626",
};
const STATUS_COLOR: Record<string, string> = {
  "public-domain": "#16a34a", "marketed-generic": "#65a30d",
  "marketed-patented": "#dc2626", clinical: "#d97706",
};

export function IPSentinelCard({ apiBase, sessionId, smiles }: Props) {
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
      const d = await r.json();
      const rows: SavedReport[] = d.reports || [];
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
    const deadline = Date.now() + 60000;
    const poll = async () => {
      if (Date.now() > deadline) {
        setScanning(false);
        setError("FTO scan is streaming in the chat workflow — it'll appear here when the IP analyst finishes.");
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
    pollRef.current = window.setTimeout(() => { void poll(); }, 3000);
  }

  async function deleteReport(id: string) {
    try {
      await fetch(`${apiBase}/workbench/chem/ip/reports/${id}`, { method: "DELETE" });
      setSaved((s) => s.filter((x) => x.id !== id));
      if (report?.artifact_id === id) setReport(null);
    } catch { /* noop */ }
  }

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "transparent", overflow: "hidden",
      fontFamily: "var(--lys-font-body)",
    }}>
      {/* Header */}
      <div style={{
        padding: "6px 10px", display: "flex", alignItems: "center", gap: 6,
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
        textTransform: "uppercase", color: SLATE.fgDeep,
        borderBottom: `1px solid ${SLATE.border}`,
      }}>
        <Scale size={11} style={{ color: SLATE.fg }} />
        <span>ip / fto sentinel · freedom to operate</span>
        <span style={{ flex: 1 }} />
        {saved.length > 0 && (
          <span style={{
            padding: "1px 6px", borderRadius: 999, background: SLATE.bgStrong,
            border: `1px solid ${SLATE.border}`, color: SLATE.fgDeep, fontSize: 9,
          }}>{saved.length} saved</span>
        )}
        <button type="button" onClick={() => void refreshSaved()}
          style={{ border: 0, background: "transparent", cursor: "pointer",
            padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      {/* Scan action */}
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
            fontSize: 11, fontWeight: 600, fontFamily: "var(--lys-font-body)",
            cursor: !smiles || scanning ? "not-allowed" : "pointer",
          }}>
          <Scale size={12} />
          {scanning ? "Agent scanning IP…" : "Run FTO scan"}
        </button>
        <span style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
          {scanning ? "similarity scan → IP-analyst review, streaming in chat"
            : smiles ? smiles : "no candidate loaded"}
        </span>
      </div>

      {error && (
        <div style={{ padding: "6px 10px", fontSize: 10, color: SLATE.fgDeep }}>{error}</div>
      )}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!report && !scanning && (
          <div style={{
            display: "flex", flexDirection: "column", gap: 6, alignItems: "center",
            justifyContent: "center", padding: 20, textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 11,
          }}>
            <Scale size={22} style={{ opacity: 0.4 }} />
            <div>Run an FTO scan — Tanimoto similarity vs a curated patent
              panel + a 12k-structure prior-art corpus tells you if the
              candidate is free to operate or treads on a live claim.</div>
          </div>
        )}
        {scanning && !report && (
          <div style={{
            display: "flex", flexDirection: "column", gap: 6, alignItems: "center",
            justifyContent: "center", padding: 20, textAlign: "center",
            color: SLATE.fgDeep, fontSize: 11,
          }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Agent is scanning IP — watch the similarity scan + analyst
              review stream in the chat.</div>
          </div>
        )}

        {report && <FTOView report={report} />}

        {saved.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{
              fontSize: 9, fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
              textTransform: "uppercase", color: "var(--lys-text-faint)",
              padding: "0 2px 4px",
            }}>saved FTO reports</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {saved.map((rt) => (
                <div key={rt.id} style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "5px 7px", borderRadius: 5,
                  background: report?.artifact_id === rt.id ? SLATE.bgStrong : SLATE.bg,
                  border: `1px solid ${SLATE.border}`,
                }}>
                  <span style={{ width: 7, height: 7, borderRadius: 7, flexShrink: 0,
                    background: RISK_COLOR[rt.payload.claim_overlap_risk] ?? "#9ca3af" }} />
                  <button type="button" onClick={() => setReport({ ...rt.payload, artifact_id: rt.id })}
                    style={{
                      flex: 1, minWidth: 0, textAlign: "left", border: 0,
                      background: "transparent", cursor: "pointer", padding: 0,
                      fontSize: 10.5, fontWeight: 600, color: "var(--lys-text)",
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    }}>
                    {rt.title || "FTO report"}
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

function FTOView({ report }: { report: FTOReport }) {
  const r = report;
  const free = r.freedom_score >= 0.66;
  const pa = r.prior_art;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Verdict banner */}
      <div style={{
        border: `1px solid ${free ? "rgba(22,163,74,0.3)" : "rgba(217,119,6,0.3)"}`,
        background: free ? "rgba(22,163,74,0.06)" : "rgba(217,119,6,0.06)",
        borderRadius: 6, padding: "7px 9px",
        display: "flex", alignItems: "center", gap: 8,
      }}>
        {free ? <ShieldCheck size={16} style={{ color: "#16a34a" }} />
          : <AlertTriangle size={16} style={{ color: "#d97706" }} />}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--lys-text)" }}>
            {r.verdict}
          </div>
          <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)" }}>
            claim-overlap risk:{" "}
            <span style={{ color: RISK_COLOR[r.claim_overlap_risk], fontWeight: 700 }}>
              {r.claim_overlap_risk}
            </span>
          </div>
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
            textTransform: "uppercase", color: "var(--lys-text-faint)" }}>freedom</div>
          <div style={{ fontSize: 17, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
            color: free ? "#16a34a" : "#d97706" }}>{r.freedom_score.toFixed(2)}</div>
        </div>
      </div>

      {/* Closest known antibiotic */}
      {r.closest_analog && (
        <Block label="Closest known antibiotic">
          <Analog hit={r.closest_analog} />
        </Block>
      )}

      {/* Closest LIVE-patent analog — the IP to clear */}
      {r.closest_live_patent_analog ? (
        <Block label="Closest live-patent analog · the IP to clear">
          <Analog hit={r.closest_live_patent_analog} live />
        </Block>
      ) : (
        <div style={{ fontSize: 9.5, color: "#16a34a",
          background: "rgba(22,163,74,0.06)", borderRadius: 4,
          border: "1px solid rgba(22,163,74,0.22)", padding: "4px 7px" }}>
          No live-patent analog within the curated panel — the nearest
          antibiotics are off-patent.
        </div>
      )}

      {/* Prior-art density */}
      <Block label={`Prior-art density · ${pa.corpus_size} published structures`}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 5 }}>
          <Stat label="≥0.92 sim" value={String(pa.near_identical_092)}
            color={pa.near_identical_092 > 0 ? "#dc2626" : "#16a34a"} />
          <Stat label="≥0.70 sim" value={String(pa.similar_070)}
            color={pa.similar_070 > 8 ? "#d97706" : "#65a30d"} />
          <Stat label="≥0.55 sim" value={String(pa.related_055)} />
        </div>
        {r.closest_published_structure && (
          <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)", marginTop: 4 }}>
            closest published: {r.closest_published_structure.ref} ·{" "}
            {r.closest_published_structure.similarity} Tanimoto
          </div>
        )}
      </Block>

      {/* IP-analyst narrative */}
      {r.narrative && (
        <div style={{
          border: `1px solid ${SLATE.border}`, borderRadius: 6,
          background: SLATE.bg, padding: "6px 8px",
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: SLATE.fgDeep }}>
            IP analyst
          </div>
          <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)",
            marginTop: 3, lineHeight: 1.45 }}>{r.narrative.assessment}</div>
          <div style={{ fontSize: 9.5, color: SLATE.fgDeep, marginTop: 3,
            fontWeight: 600, lineHeight: 1.45 }}>
            → {r.narrative.recommended_action}
          </div>
        </div>
      )}

      {/* Panel hit list */}
      {r.top_panel_analogs.length > 0 && (
        <Block label="Nearest panel analogs">
          {r.top_panel_analogs.map((h, i) => (
            <div key={i} style={{ display: "flex", alignItems: "baseline",
              gap: 6, fontSize: 9.5, padding: "1px 0" }}>
              <span style={{ fontWeight: 600, color: "var(--lys-text)" }}>{h.name}</span>
              <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 9,
                color: SLATE.fgDeep }}>{h.similarity.toFixed(2)}</span>
              <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                color: STATUS_COLOR[h.status] ?? "#9ca3af" }}>{h.status}</span>
            </div>
          ))}
        </Block>
      )}
    </div>
  );
}

function Analog({ hit, live }: { hit: PanelHit; live?: boolean }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11.5, fontWeight: 700, color: "var(--lys-text)" }}>
          {hit.name}
        </span>
        <span style={{ fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
          fontWeight: 700, color: live ? "#dc2626" : SLATE.fgDeep }}>
          {hit.similarity.toFixed(2)} Tanimoto
        </span>
        <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
          padding: "1px 5px", borderRadius: 3,
          background: (STATUS_COLOR[hit.status] ?? "#9ca3af") + "22",
          color: STATUS_COLOR[hit.status] ?? "#9ca3af" }}>{hit.status}</span>
      </div>
      <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", marginTop: 2 }}>
        {hit.drug_class} · {hit.assignee} · {hit.patent} · {hit.year}
      </div>
    </div>
  );
}

function Block({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ border: `1px solid ${SLATE.border}`, borderRadius: 6,
      background: SLATE.bg, padding: "6px 8px" }}>
      <div style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.05em", textTransform: "uppercase",
        color: "var(--lys-text-faint)", marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: "rgba(255,255,255,0.6)",
      border: `1px solid ${SLATE.border}`, borderRadius: 4,
      padding: "3px 4px", textAlign: "center" }}>
      <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
        textTransform: "uppercase", color: "var(--lys-text-faint)" }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
        color: color ?? "var(--lys-text)" }}>{value}</div>
    </div>
  );
}
