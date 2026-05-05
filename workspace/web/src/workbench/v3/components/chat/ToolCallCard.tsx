import { useState } from "react";
import { ChevronRight, Wrench, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import { agentColor } from "./AgentAvatar";

interface ToolCallCardProps {
  name: string;
  agent: string;
  status: "ok" | "err" | "running";
  duration_ms?: number;
  args?: any;
  result?: any;
  error?: string;
}

export function ToolCallCard(p: ToolCallCardProps) {
  const [open, setOpen] = useState(false);
  const color = agentColor(p.agent);

  return (
    <div
      style={{
        marginTop: 6,
        marginLeft: 12,
        position: "relative",
      }}
    >
      {/* Thread connector — vertical line linking message to tool-call */}
      <span
        style={{
          position: "absolute",
          left: -12,
          top: -6,
          width: 1,
          height: "100%",
          background: "var(--lys-border)",
        }}
      />
      <span
        style={{
          position: "absolute",
          left: -12,
          top: 16,
          width: 12,
          height: 1,
          background: "var(--lys-border)",
        }}
      />

      <div
        style={{
          background: "white",
          border: "1px solid var(--lys-border)",
          borderRadius: 8,
          fontSize: 12,
          overflow: "hidden",
        }}
      >
        <button
          onClick={() => setOpen((o) => !o)}
          style={{
            width: "100%",
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 10px",
            border: 0,
            background: "transparent",
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          <ChevronRight
            size={12}
            style={{
              transform: open ? "rotate(90deg)" : "none",
              transition: "transform 0.15s",
              color: "var(--lys-text-faint)",
            }}
          />
          <StatusPip status={p.status} />
          <Wrench size={11} color="var(--lys-text-dim)" />
          <span
            style={{
              fontFamily: "var(--lys-font-mono)",
              fontWeight: 600,
              color: "var(--lys-text)",
              fontSize: 12,
            }}
          >
            {p.name}
          </span>
          <span
            style={{
              padding: "1px 6px",
              fontSize: 9,
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              fontWeight: 600,
              borderRadius: 999,
              background: `${color}1a`,
              color,
            }}
          >
            {p.agent}
          </span>
          {p.duration_ms != null && (
            <span
              style={{
                marginLeft: "auto",
                fontFamily: "var(--lys-font-mono)",
                fontSize: 10,
                color: "var(--lys-text-faint)",
              }}
            >
              {p.duration_ms < 1 ? "<1ms" : `${p.duration_ms}ms`}
            </span>
          )}
        </button>

        {open && (
          <div
            style={{
              padding: 10,
              borderTop: "1px solid var(--lys-border)",
              background: "var(--lys-surface-2)",
              fontFamily: "var(--lys-font-mono)",
              fontSize: 11,
            }}
          >
            {p.args && (
              <div style={{ marginBottom: 6 }}>
                <div
                  style={{
                    fontSize: 9,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: "var(--lys-text-faint)",
                    marginBottom: 3,
                  }}
                >
                  args
                </div>
                <pre
                  style={{
                    margin: 0,
                    fontSize: 11,
                    color: "var(--lys-text)",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    fontFamily: "inherit",
                  }}
                >
                  {JSON.stringify(p.args, null, 2)}
                </pre>
              </div>
            )}
            {p.result != null && (
              <div>
                <div
                  style={{
                    fontSize: 9,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: "var(--lys-text-faint)",
                    marginBottom: 3,
                  }}
                >
                  result
                </div>
                <pre
                  style={{
                    margin: 0,
                    fontSize: 11,
                    color: "var(--lys-text)",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    fontFamily: "inherit",
                    maxHeight: 200,
                    overflow: "auto",
                  }}
                >
                  {typeof p.result === "string" ? p.result : JSON.stringify(p.result, null, 2)}
                </pre>
              </div>
            )}
            {p.error && (
              <div style={{ color: "#b91c1c" }}>
                <strong>error: </strong>
                {p.error}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusPip({ status }: { status: "ok" | "err" | "running" }) {
  if (status === "running")
    return (
      <Loader2
        size={11}
        color="#8b5cf6"
        className="lys-spin"
        style={{ animation: "lys-spin 1s linear infinite" }}
      />
    );
  if (status === "err") return <AlertCircle size={11} color="#ef4444" />;
  return <CheckCircle2 size={11} color="#10b981" />;
}
