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
import { ArrowUp, X, Beaker, FlaskConical, Target, HelpCircle, Activity } from "lucide-react";
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
  /** When true, render a starter-prompt chip strip above the input.
   *  Auto-hides once the user has sent the first message. */
  chatEmpty?: boolean;
  /** Free-form slot rendered above EVERYTHING in the composer (above
   *  constraints, starters, palette, input). Used for the agent
   *  suggestion strip so context-aware "what next" chips live right
   *  above the input regardless of whether the chat is empty. */
  headerSlot?: React.ReactNode;
}

interface StarterPrompt {
  cmd: string;          // accent-colored mono (e.g. "/design")
  rest: string;         // dim normal text (e.g. "β-lactam for MRSA")
  prompt: string;       // full text dropped into the textarea on click
  icon: React.ReactNode;
}

const STARTER_PROMPTS: StarterPrompt[] = [
  {
    cmd: "/design",
    rest: "β-lactam for MRSA",
    prompt: "/design β-lactam for MRSA that escapes mecA",
    icon: <FlaskConical size={11} />,
  },
  {
    cmd: "/score",
    rest: "a candidate",
    prompt: "/score CCO",
    icon: <Target size={11} />,
  },
  {
    cmd: "/explain",
    rest: "a target",
    prompt: "/explain mecA / PBP2a",
    icon: <HelpCircle size={11} />,
  },
  {
    cmd: "/spectrum",
    rest: "macrolide",
    prompt: "/spectrum macrolide for MRSA + VRE",
    icon: <Activity size={11} />,
  },
];

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

  // Auto-slash dispatch — when the orchestrator picks a slash route, it
  // emits the rendered command via window event. We catch it here and
  // re-fire onSend so the existing slash-command pipeline runs without
  // duplicating routing logic.
  //
  // Module-level dedup ref: under React 18 StrictMode useEffect runs
  // twice in dev, so a single dispatched event was firing onSend twice
  // → two identical user bubbles + two backend roundtrips. The window
  // event itself is not duplicated; the listener registration is.
  // A static "last fired text + ts" ref drops duplicates within 1500ms.
  useEffect(() => {
    function onAutoSlash(ev: Event) {
      const detail = (ev as CustomEvent).detail as { text?: string } | undefined;
      const slash = (detail?.text || "").trim();
      if (!slash) return;
      const w = window as any;
      const now = Date.now();
      const last = w.__lysAutoSlashLast as { text: string; ts: number } | undefined;
      if (last && last.text === slash && (now - last.ts) < 1500) {
        return;  // de-dup
      }
      w.__lysAutoSlashLast = { text: slash, ts: now };
      p.onSend(slash);
    }
    window.addEventListener("lysos:auto-slash", onAutoSlash);
    return () => window.removeEventListener("lysos:auto-slash", onAutoSlash);
  }, [p.onSend]);

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (paletteOpen) {
      if (e.key === "Escape") {
        setPaletteOpen(false);
        return;
      }
      // Tab + arrow keys belong to the palette (autocomplete +
      // navigation). Enter, however, must always send when the user
      // has typed past the bare command name (e.g. `/wf do anything`)
      // — otherwise the palette eats Enter, fires onPick on its own
      // schedule, and the message never sends. The previous
      // implementation deferred Enter to the palette's window
      // listener, which created a race against React state updates
      // and made Enter feel broken.
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Tab") {
        return;
      }
      const hasArgs = /\s/.test(text.trim());  // typed past the slash command
      if (e.key === "Enter" && !e.shiftKey && hasArgs) {
        e.preventDefault();
        setPaletteOpen(false);
        send();
        return;
      }
      // Plain `/cmd` + Enter (no args) → let palette handle (it autocompletes
      // or, on exact match, closes itself and lets the next branch send).
      if (e.key === "Enter") return;
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
      {/* Free header slot — agent-suggestion strip + workflow palette
          live here. Rendered before constraints/starters so the
          "what's next" guidance is the FIRST thing the user sees. */}
      {p.headerSlot}
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

      {/* Starter-prompt chips — discovery surface for the slash-command
          registry. Each chip is structured: icon · accent slash · dim rest.
          Hover lifts a subtle accent border + bg-tint. */}
      {p.chatEmpty && !p.isRunning && p.constraints.length === 0 && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 4,
          marginBottom: 6,
        }}>
          {STARTER_PROMPTS.map((s) => (
            <button
              key={s.cmd}
              type="button"
              onClick={() => {
                setText(s.prompt);
                requestAnimationFrame(() => taRef.current?.focus());
              }}
              className="lys-starter-chip"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                padding: "5px 9px",
                background: "white",
                border: "1px solid var(--lys-border, rgba(15,23,42,0.08))",
                borderRadius: 6,
                cursor: "pointer",
                fontFamily: "inherit",
                textAlign: "left",
                minWidth: 0,
                transition: "border-color 0.12s, background 0.12s, transform 0.12s",
              }}
            >
              <span style={{
                color: "var(--lys-accent)",
                display: "inline-flex",
                flexShrink: 0,
              }}>
                {s.icon}
              </span>
              <span style={{
                fontFamily: "var(--lys-font-mono)",
                fontSize: 10.5,
                fontWeight: 600,
                color: "var(--lys-accent)",
                flexShrink: 0,
              }}>
                {s.cmd}
              </span>
              <span style={{
                fontSize: 10.5,
                color: "var(--lys-text-dim)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                minWidth: 0,
              }}>
                {s.rest}
              </span>
            </button>
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
            : "Ask the agent · type / for commands or /wf for workflows"}
          value={text}
          onChange={(e) => {
            const v = e.target.value;
            setText(v);
            // Open palette only when the FIRST non-empty line begins
            // with "/" — multi-line input where the slash is on a
            // later line shouldn't summon a "no commands match" pop.
            const firstNonEmpty = v.split(/[\n\r]/).find((l) => l.trim().length > 0) ?? "";
            setPaletteOpen(firstNonEmpty.trim().startsWith("/"));
          }}
          onKeyDown={handleKey}
          onFocus={() => {
            const firstNonEmpty = text.split(/[\n\r]/).find((l) => l.trim().length > 0) ?? "";
            setPaletteOpen(firstNonEmpty.trim().startsWith("/"));
          }}
          style={{
            width: "100%",
            border: 0,
            outline: 0,
            background: "transparent",
            fontFamily: "inherit",
            fontSize: 13.5,
            lineHeight: 1.45,
            padding: "10px 44px 10px 14px",
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

        {/* Single send button — right-anchored, vertically centered.
            Note: previously had a `↵ send` kbd-hint chip next to it which
            looked like a second send button. Removed per user feedback.
            The native title tooltip still shows the keyboard hint. */}
        <button
          onClick={send}
          disabled={!canSend}
          style={{
            position: "absolute",
            right: 6,
            bottom: 6,
            display: "grid",
            placeItems: "center",
            width: 26,
            height: 26,
            borderRadius: 6,
            border: 0,
            background: canSend ? "var(--lys-text)" : "var(--lys-surface-2)",
            color: canSend ? "white" : "var(--lys-text-faint)",
            cursor: canSend ? "pointer" : "default",
            transition: "background 0.12s, color 0.12s",
          }}
          aria-label="send"
          title={p.isRunning ? "intervene (↵)" : "send (↵)"}
        >
          <ArrowUp size={14} />
        </button>
      </div>
    </div>
  );
}
