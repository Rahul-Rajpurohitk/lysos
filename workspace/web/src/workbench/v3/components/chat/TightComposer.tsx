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
import { ArrowUp, X, Beaker } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { SlashPalette, type SlashCommand, DEFAULT_COMMANDS } from "./SlashPalette";

interface Constraint {
  id: string;
  label: string;
}

interface TightComposerProps {
  isRunning: boolean;
  onSend: (text: string) => void;
  onIntervene: (kind: "constraint" | "directive", payload: any) => void;
  constraints: Constraint[];
  onRemoveConstraint: (id: string) => void;
}

export function TightComposer(p: TightComposerProps) {
  const [text, setText] = useState("");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const [registry, setRegistry] = useState<SlashCommand[]>(DEFAULT_COMMANDS);

  // Fetch the live command registry from the FastAPI server (so the palette
  // stays in sync with workspace/agents/commands.py without a frontend
  // rebuild). Falls back to DEFAULT_COMMANDS shipped with the bundle.
  useEffect(() => {
    let cancelled = false;
    fetch("/api/commands/list")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled && Array.isArray(d) && d.length) {
          setRegistry(d as SlashCommand[]);
        }
      })
      .catch(() => {
        /* fall back to bundled DEFAULT_COMMANDS */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // auto-grow up to ~6 lines
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    // Default 2 lines (~52px content). Auto-grow up to 4 lines (~96px),
    // then internal scrolling kicks in (overflow-y handled by maxHeight).
    el.style.height = "auto";
    el.style.height = `${Math.min(96, Math.max(52, el.scrollHeight))}px`;
  }, [text]);

  function reset() {
    setText("");
    setPaletteOpen(false);
  }

  function applySlash(cmd: SlashCommand) {
    // The user picked a command from the palette. Insert "/<name> "
    // into the textarea so they can fill the args, OR auto-send if the
    // command takes no arguments.
    const argHint = cmd.argument_hint || "";
    if (!argHint) {
      // No-args command: send immediately
      p.onSend(`/${cmd.name}`);
      reset();
    } else {
      setText(`/${cmd.name} `);
      setPaletteOpen(false);
      // Refocus textarea
      requestAnimationFrame(() => taRef.current?.focus());
    }
  }

  function send() {
    const t = text.trim();
    if (!t) return;
    // Slash command: pass through as-is — server-side harness routes it
    if (p.isRunning) p.onIntervene("directive", { text: t });
    else p.onSend(t);
    reset();
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (paletteOpen) {
      // Palette manages its own ↑↓↵Esc Tab — let it handle, but still
      // intercept Enter-without-modifier here in case palette is closed.
      if (e.key === "Escape") {
        setPaletteOpen(false);
        return;
      }
      if (e.key === "Enter" || e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Tab") {
        // Palette handles via window keydown listener
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  const canSend = text.trim().length > 0;

  return (
    /* No padding here — outer .lys-chat__composer handles the
       3-sided gap (8px top + sides) + 16px bottom seat. */
    <div style={{ position: "relative" }}>
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

      {/* Slash command palette — Claude Code style, registry-driven */}
      <SlashPalette
        query={text}
        open={paletteOpen}
        onPick={applySlash}
        onClose={() => setPaletteOpen(false)}
        commands={registry}
      />


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
          rows={2}
          placeholder={p.isRunning
            ? "Intervene… type a directive or constraint"
            : "Describe a target — e.g. non-toxic macrolide for MRSA that escapes mecA"}
          value={text}
          onChange={(e) => {
            const v = e.target.value;
            setText(v);
            setPaletteOpen(v.startsWith("/"));
          }}
          onKeyDown={handleKey}
          onFocus={() => setPaletteOpen(text.startsWith("/"))}
          style={{
            width: "100%",
            border: 0,
            outline: 0,
            background: "transparent",
            fontFamily: "inherit",
            fontSize: 13.5,
            lineHeight: 1.45,
            padding: "10px 92px 10px 14px",
            color: "var(--lys-text)",
            resize: "none",
            // Default visible 2 lines (~52px); auto-grow up to 4 lines (~96px);
            // then internal scrolling kicks in via overflowY=auto.
            minHeight: 52,
            maxHeight: 96,
            overflowY: "auto",
            boxSizing: "border-box",
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
