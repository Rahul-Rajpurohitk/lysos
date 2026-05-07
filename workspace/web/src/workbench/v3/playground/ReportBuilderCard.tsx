/**
 * ReportBuilderCard — the deliverable. Snapshot every chem dashboard +
 * assemble a structured medchem report.
 *
 * Top-half: Capture button + summary stats
 * Bottom-half: Live HTML preview (iframe) of /workbench/report/{sid}/preview
 * Bottom toolbar: Export buttons (Markdown / JSON / Print as PDF)
 *
 * No external dependencies. The backend renders both the markdown and the
 * HTML preview; the frontend just orchestrates the snapshot + export.
 */
import { useEffect, useState } from "react";
import { FileText, Download, RefreshCw, Printer } from "lucide-react";

interface SnapshotSummary {
  session_id: string;
  captured_at: number;
  pathogen: string;
  session: {
    duration_min: number;
    n_candidates: number;
    n_score_actions: number;
    n_pocket_calls: number;
    n_resistance_calls: number;
    n_red_team_calls: number;
  };
  top_candidates: { rank: number; smiles: string; composite: number | null; created_by: string }[];
  workflow_phases_completed: string[];
}

interface Props {
  apiBase: string;
  sessionId: string | null;
}

export function ReportBuilderCard({ apiBase, sessionId }: Props) {
  const [summary, setSummary] = useState<SnapshotSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string>("");

  const captureSnapshot = async () => {
    if (!sessionId) return;
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/workbench/report/snapshot/${encodeURIComponent(sessionId)}`, { method: "POST" });
      if (!r.ok) {
        const txt = await r.text();
        setError(txt.slice(0, 200));
        return;
      }
      const d: SnapshotSummary = await r.json();
      setSummary(d);
      // Force iframe re-load with cache-buster
      setPreviewUrl(`${apiBase}/workbench/report/${encodeURIComponent(sessionId)}/preview?format=html&t=${Date.now()}`);
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setLoading(false);
    }
  };

  // Auto-capture once on mount
  useEffect(() => {
    if (sessionId) captureSnapshot();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const exportMarkdown = () => {
    if (!sessionId) return;
    window.open(`${apiBase}/workbench/report/${encodeURIComponent(sessionId)}/export?format=md`, "_blank");
  };

  const exportJson = () => {
    if (!sessionId) return;
    window.open(`${apiBase}/workbench/report/${encodeURIComponent(sessionId)}/export?format=json`, "_blank");
  };

  const printAsPdf = () => {
    if (!sessionId) return;
    const w = window.open(`${apiBase}/workbench/report/${encodeURIComponent(sessionId)}/preview?format=html`, "_blank");
    if (w) {
      w.addEventListener("load", () => { try { w.print(); } catch {/*noop*/} });
    }
  };

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
    }}>
      <div style={{
        padding: "5px 10px",
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", letterSpacing: "0.06em",
        textTransform: "uppercase",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <FileText size={11} style={{ color: "#0891b2" }} />
        <span>report builder</span>
        {summary && (
          <>
            <span style={{ flex: 1 }} />
            <span style={{
              padding: "1px 6px", borderRadius: 999, fontSize: 9,
              background: "rgba(8,145,178,0.10)", color: "#0891b2", fontWeight: 700,
            }}>
              {summary.session.n_candidates} candidates · {summary.workflow_phases_completed.length} phases
            </span>
          </>
        )}
        {loading && <RefreshCw size={11} style={{ animation: "spin 1s linear infinite" }} />}
      </div>

      {/* Top: capture controls + summary */}
      <div style={{
        padding: "8px 10px",
        display: "flex", flexDirection: "column", gap: 6,
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={captureSnapshot}
            disabled={!sessionId || loading}
            style={{
              padding: "4px 10px", borderRadius: 5,
              background: sessionId ? "#0891b2" : "var(--lys-bg-3, rgba(0,0,0,0.04))",
              color: sessionId ? "white" : "var(--lys-text-faint)",
              border: 0, cursor: sessionId ? "pointer" : "not-allowed",
              fontFamily: "var(--lys-font-mono)", fontSize: 10, fontWeight: 700,
              display: "inline-flex", alignItems: "center", gap: 4,
            }}>
            <RefreshCw size={11} />
            Capture snapshot
          </button>
          <span style={{ flex: 1 }} />
          <button type="button" onClick={exportMarkdown} disabled={!summary}
            style={btnStyle(!summary)} title="Download .md">
            <Download size={10} /> .md
          </button>
          <button type="button" onClick={exportJson} disabled={!summary}
            style={btnStyle(!summary)} title="Download .json">
            <Download size={10} /> .json
          </button>
          <button type="button" onClick={printAsPdf} disabled={!summary}
            style={btnStyle(!summary)} title="Open print dialog → save as PDF">
            <Printer size={10} /> PDF
          </button>
        </div>

        {error && (
          <div style={{ padding: "4px 6px", fontSize: 10, color: "#dc2626" }}>
            error: {error}
          </div>
        )}

        {summary && (
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(96px, 1fr))",
            gap: 4, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
          }}>
            <Stat label="pathogen" value={summary.pathogen} />
            <Stat label="duration" value={`${summary.session.duration_min}m`} />
            <Stat label="candidates" value={String(summary.session.n_candidates)} />
            <Stat label="scores" value={String(summary.session.n_score_actions)} />
            <Stat label="pose" value={String(summary.session.n_pocket_calls)} />
            <Stat label="resistance" value={String(summary.session.n_resistance_calls)} />
            <Stat label="red-team" value={String(summary.session.n_red_team_calls)} />
            <Stat label="phases" value={`${summary.workflow_phases_completed.length}/6`} />
          </div>
        )}
      </div>

      {/* Bottom: live preview iframe */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
        {!sessionId && (
          <div style={{
            padding: "30px 14px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 10.5,
            fontFamily: "var(--lys-font-mono)",
          }}>
            no active session
          </div>
        )}
        {sessionId && previewUrl && (
          <iframe
            key={previewUrl}
            src={previewUrl}
            title="Report preview"
            style={{
              width: "100%", height: "100%", border: 0,
              background: "white",
            }}
          />
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      padding: "3px 6px", borderRadius: 4,
      background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
      border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
    }}>
      <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
        letterSpacing: "0.04em", textTransform: "uppercase", fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--lys-text)" }}>
        {value}
      </div>
    </div>
  );
}

function btnStyle(disabled: boolean): React.CSSProperties {
  return {
    padding: "3px 8px", borderRadius: 4,
    background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
    border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
    cursor: disabled ? "not-allowed" : "pointer",
    fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
    color: disabled ? "var(--lys-text-faint)" : "var(--lys-text-dim)",
    display: "inline-flex", alignItems: "center", gap: 3,
    opacity: disabled ? 0.5 : 1,
  };
}
