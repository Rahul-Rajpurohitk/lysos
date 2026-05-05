/**
 * TightComposer — keyboard-first input.
 *
 * Reasoning:
 *  - The previous composer used a chunky textarea + a green "Push" button.
 *    "Push" is a non-standard verb. Big colored buttons signal commit-and-
 *    blow-up; in a research tool you want a fast keyboard loop instead.
 *  - New design: clean textarea with a subtle border, kbd hint at the
 *    right (⌘ ↵), inline arrow-icon send button that activates only when
 *    text is present. Same bandwidth (you can still click) but the
 *    primary affordance is keyboard.
 *  - Slash menu unchanged (it's already good).
 *  - Constraint chips are placed ABOVE the input as a tiny strip; only
 *    rendered when there are constraints (no empty placeholder taking
 *    space).
 *  - When isRunning, the placeholder shifts to "intervene…" so the user
 *    knows what their input does.
 *  - Auto-grow up to 6 lines; scroll past that.
 */
import { ArrowUp, X, Beaker, FlaskConical, FileSearch, GitBranch, Plus } from "lucide-react";
import clsx from "clsx";
import { useEffect, useRef, useState } from "react";

interface Constraint {
  id: string;
  label: string;
}

interface SlashCmd {
  cmd: string;
  desc: string;
  icon: React.ReactNode;
  apply: (rest: string) => { send?: string; constraint?: string };
}

interface TightComposerProps {
  isRunning: boolean;
  onSend: (text: string) => void;
  onIntervene: (kind: "constraint" | "directive", payload: any) => void;
  constraints: Constraint[];
  onRemoveConstraint: (id: string) => void;
}

const SLASH: SlashCmd[] = [
  {
    cmd: "/constraint",
    desc: "Pin a chemistry constraint",
    icon: <FlaskConical size={12} />,
    apply: (r) => ({ constraint: r }),
  },
  {
    cmd: "/from-paper",
    desc: "Mine constraints from a paper (DOI / title)",
    icon: <FileSearch size={12} />,
    apply: (r) => ({ send: `From paper: ${r}` }),
  },
  {
    cmd: "/scaffold-hop",
    desc: "Scaffold-hop the current top candidate",
    icon: <GitBranch size={12} />,
    apply: () => ({ send: "Scaffold-hop the current top candidate." }),
  },
  {
    cmd: "/branch",
    desc: "Branch into a parallel exploration",
    icon: <Plus size={12} />,
    apply: () => ({ send: "Branch into parallel exploration." }),
  },
];

export function TightComposer(p: TightComposerProps) {
  const [text, setText] = useState("");
  const [showSlash, setShowSlash] = useState(false);
  const [slashIdx, setSlashIdx] = useState(0);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  const filtered = SLASH.filter((c) => c.cmd.startsWith(text.split(/\s/)[0]));

  // auto-grow up to ~6 lines
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(132, el.scrollHeight)}px`;
  }, [text]);

  function reset() {
    setText("");
    setShowSlash(false);
    setSlashIdx(0);
  }

  function applySlash(cmd: SlashCmd) {
    const rest = text.slice(cmd.cmd.length).trim();
    const r = cmd.apply(rest);
    if (r.constraint) p.onIntervene("constraint", { label: r.constraint });
    if (r.send) p.onSend(r.send);
    reset();
  }

  function send() {
    const t = text.trim();
    if (!t) return;
    if (t.startsWith("/")) {
      const cmd = SLASH.find((c) => t.startsWith(c.cmd));
      if (cmd) return applySlash(cmd);
    }
    if (p.isRunning) p.onIntervene("directive", { text: t });
    else p.onSend(t);
    reset();
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (showSlash && filtered.length > 0) {
      if (e.key === "ArrowDown") { e.preventDefault(); setSlashIdx((i) => (i + 1) % filtered.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setSlashIdx((i) => (i - 1 + filtered.length) % filtered.length); return; }
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); applySlash(filtered[slashIdx]); return; }
      if (e.key === "Escape") { setShowSlash(false); return; }
    }
    // Enter to send (unless Shift+Enter for newline). Cmd+Enter also works.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  const canSend = text.trim().length > 0;

  return (
    <div style={{ position: "relative", padding: "8px 16px 12px" }}>
      {/* Constraint chip strip — only when constraints exist */}
      {p.constraints.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
          {p.constraints.map((c) => (
            <span key={c.id} style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "2px 6px 2px 8px",
              fontSize: 10.5,
              fontFamily: "var(--lys-font-mono)",
              color: "#1d4ed8",
              background: "#eff6ff",
              border: "1px solid #bfdbfe",
              borderRadius: 4,
            }}>
              <Beaker size={9} />
              {c.label}
              <button
                onClick={() => p.onRemoveConstraint(c.id)}
                style={{
                  border: 0,
                  background: "transparent",
                  color: "inherit",
                  padding: 0,
                  marginLeft: 2,
                  cursor: "pointer",
                  display: "inline-grid",
                  placeItems: "center",
                }}
                aria-label="remove constraint"
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Slash menu */}
      {showSlash && filtered.length > 0 && (
        <div style={{
          position: "absolute",
          bottom: "calc(100% - 6px)",
          left: 16,
          right: 16,
          background: "white",
          border: "1px solid var(--lys-border-strong)",
          borderRadius: 8,
          padding: 4,
          boxShadow: "var(--lys-shadow-lg)",
          zIndex: 50,
        }}>
          {filtered.map((c, i) => (
            <button
              key={c.cmd}
              className={clsx(i === slashIdx && "lys-slash-menu__item--active")}
              onClick={() => applySlash(c)}
              onMouseEnter={() => setSlashIdx(i)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 8px",
                width: "100%",
                border: 0,
                background: i === slashIdx ? "var(--lys-surface-2)" : "transparent",
                color: "var(--lys-text)",
                fontFamily: "inherit",
                fontSize: 12,
                cursor: "pointer",
                borderRadius: 4,
                textAlign: "left",
              }}
            >
              {c.icon}
              <span style={{
                fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-accent)",
                fontWeight: 600,
                width: 100,
              }}>{c.cmd}</span>
              <span style={{ color: "var(--lys-text-dim)", fontSize: 11 }}>{c.desc}</span>
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div style={{
        position: "relative",
        background: "white",
        border: "1px solid var(--lys-border)",
        borderRadius: 8,
        transition: "border-color 0.15s, box-shadow 0.15s",
      }}
      // focus glow handled via :focus-within in v3.css
      >
        <textarea
          ref={taRef}
          rows={1}
          placeholder={p.isRunning
            ? "Intervene… type a directive or constraint"
            : "Describe a target — e.g. non-toxic macrolide for MRSA that escapes mecA"}
          value={text}
          onChange={(e) => {
            const v = e.target.value;
            setText(v);
            setShowSlash(v.startsWith("/"));
          }}
          onKeyDown={handleKey}
          onFocus={() => setShowSlash(text.startsWith("/"))}
          style={{
            width: "100%",
            border: 0,
            outline: 0,
            background: "transparent",
            fontFamily: "inherit",
            fontSize: 13.5,
            lineHeight: 1.45,
            padding: "8px 88px 8px 12px",
            color: "var(--lys-text)",
            resize: "none",
            minHeight: 36,
            maxHeight: 132,
          }}
        />

        {/* kbd hint + send icon — right-anchored, vertically centered */}
        <div style={{
          position: "absolute",
          right: 6,
          bottom: 6,
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}>
          <span style={{
            fontSize: 9.5,
            fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)",
            background: "var(--lys-surface-2)",
            padding: "1px 5px",
            borderRadius: 3,
            opacity: text.length > 0 ? 1 : 0.6,
          }}>
            {p.isRunning ? "↵ intervene" : "↵ send"}
          </span>
          <button
            onClick={send}
            disabled={!canSend}
            style={{
              display: "grid",
              placeItems: "center",
              width: 24,
              height: 24,
              borderRadius: 5,
              border: 0,
              background: canSend ? "var(--lys-text)" : "var(--lys-surface-2)",
              color: canSend ? "white" : "var(--lys-text-faint)",
              cursor: canSend ? "pointer" : "default",
              transition: "background 0.12s, color 0.12s",
            }}
            aria-label="send"
            title={p.isRunning ? "intervene mid-loop" : "send message"}
          >
            <ArrowUp size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
