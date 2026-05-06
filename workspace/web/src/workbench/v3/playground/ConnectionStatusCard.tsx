/**
 * ConnectionStatusCard — live signal of the playground's backend health.
 *
 * Shows: WS state · cursor count · edit count · last event time · agent
 * activity · job queue size. Pure read-only window into the live system.
 */
import { useEffect, useState } from "react";
import { Wifi, WifiOff, Activity, Users, Database, Zap } from "lucide-react";

interface Props {
  apiBase: string;
  sessionId: string;
  connected: boolean;
  cursorCount: number;
  recentEditCount: number;
  lastEventTs?: number;
}

interface JobsSummary {
  queued: number;
  running: number;
  done: number;
  error: number;
}

export function ConnectionStatusCard(p: Props) {
  const [jobs, setJobs] = useState<JobsSummary>({ queued: 0, running: 0, done: 0, error: 0 });
  const [moleculeCount, setMoleculeCount] = useState(0);

  useEffect(() => {
    if (!p.sessionId) return;
    let cancelled = false;
    async function tick() {
      try {
        // Jobs summary
        const jr = await fetch(`${p.apiBase}/workbench/playground/sessions/${p.sessionId}/jobs`);
        if (jr.ok && !cancelled) {
          const d = await jr.json();
          const sum = { queued: 0, running: 0, done: 0, error: 0 };
          for (const j of d.jobs ?? []) {
            const s = j.status as keyof JobsSummary;
            if (s in sum) sum[s] += 1;
          }
          setJobs(sum);
        }
        // Molecule count
        const mr = await fetch(`${p.apiBase}/workbench/playground/sessions/${p.sessionId}/molecules`);
        if (mr.ok && !cancelled) {
          const d = await mr.json();
          setMoleculeCount((d.molecules ?? []).length);
        }
      } catch {/* */}
    }
    tick();
    const id = window.setInterval(tick, 4000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [p.apiBase, p.sessionId]);

  const lastEventDelta = p.lastEventTs ? Math.round((Date.now() / 1000 - p.lastEventTs)) : null;

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "auto", padding: 10, gap: 8,
    }}>
      <Row icon={p.connected ? Wifi : WifiOff} color={p.connected ? "#10b981" : "#dc2626"}
           label="WebSocket"
           value={p.connected ? "connected" : "disconnected"}
           sub={`/ws/playground/${p.sessionId.slice(0, 12)}…`}
      />
      <Row icon={Users} color="#8b5cf6"
           label="Live cursors"
           value={String(p.cursorCount)}
           sub={p.cursorCount > 0 ? "agents are looking" : "idle"}
      />
      <Row icon={Database} color="#3b82f6"
           label="Persisted molecules"
           value={String(moleculeCount)}
           sub="atoms + bonds in SQLite"
      />
      <Row icon={Activity} color="#10b981"
           label="Recent edits"
           value={String(p.recentEditCount)}
           sub={lastEventDelta != null ? `last ${lastEventDelta}s ago` : "no events yet"}
      />
      <Row icon={Zap} color="#d97706"
           label="Job queue"
           value={`${jobs.running} running · ${jobs.queued} queued`}
           sub={`${jobs.done} done · ${jobs.error} errored`}
      />
    </div>
  );
}

function Row({
  icon: Icon, color, label, value, sub,
}: {
  icon: any; color: string; label: string; value: string; sub: string;
}) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "16px 1fr auto",
      gap: 8,
      alignItems: "center",
      padding: "4px 0",
      borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
    }}>
      <Icon size={13} style={{ color }} />
      <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <span style={{
          fontSize: 9.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}>{label}</span>
        <span style={{ fontSize: 9.5, color: "var(--lys-text-faint)" }}>{sub}</span>
      </div>
      <span style={{
        fontFamily: "var(--lys-font-mono)",
        fontSize: 11,
        fontWeight: 600,
        color,
      }}>{value}</span>
    </div>
  );
}
