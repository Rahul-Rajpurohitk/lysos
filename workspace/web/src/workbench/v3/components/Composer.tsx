import { Send, X, FlaskConical, Beaker, Plus, FileSearch, GitBranch } from "lucide-react";
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

interface ComposerProps {
  isRunning: boolean;
  onSend: (text: string) => void;
  onIntervene: (kind: "constraint" | "directive", payload: any) => void;
  constraints: Constraint[];
  onRemoveConstraint: (id: string) => void;
}

const SLASH_COMMANDS: SlashCmd[] = [
  {
    cmd: "/constraint",
    desc: "Pin a chemistry constraint (e.g. /constraint replace -Cl with -F)",
    icon: <FlaskConical size={14} />,
    apply: (rest) => ({ constraint: rest }),
  },
  {
    cmd: "/from-paper",
    desc: "Mine constraints from a recent paper (paste DOI / title)",
    icon: <FileSearch size={14} />,
    apply: (rest) => ({ send: `From paper: ${rest}` }),
  },
  {
    cmd: "/scaffold-hop",
    desc: "Ask Designer to scaffold-hop the current top candidate",
    icon: <GitBranch size={14} />,
    apply: () => ({ send: "Scaffold-hop the current top candidate." }),
  },
  {
    cmd: "/branch",
    desc: "Branch into a parallel design exploration",
    icon: <Plus size={14} />,
    apply: () => ({ send: "Branch into parallel exploration." }),
  },
  {
    cmd: "/clear",
    desc: "Clear the composer",
    icon: <X size={14} />,
    apply: () => ({}),
  },
];

export function Composer(props: ComposerProps) {
  const [text, setText] = useState("");
  const [showSlash, setShowSlash] = useState(false);
  const [slashIdx, setSlashIdx] = useState(0);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  const filteredSlash = SLASH_COMMANDS.filter((c) =>
    c.cmd.startsWith(text.split(/\s/)[0])
  );

  useEffect(() => {
    if (!taRef.current) return;
    const el = taRef.current;
    el.style.height = "auto";
    el.style.height = `${Math.min(160, el.scrollHeight)}px`;
  }, [text]);

  function reset() {
    setText("");
    setShowSlash(false);
    setSlashIdx(0);
  }

  function applySlashCommand(cmd: SlashCmd) {
    const rest = text.slice(cmd.cmd.length).trim();
    const r = cmd.apply(rest);
    if (r.constraint) props.onIntervene("constraint", { label: r.constraint });
    if (r.send) props.onSend(r.send);
    reset();
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (showSlash && filteredSlash.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSlashIdx((i) => (i + 1) % filteredSlash.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSlashIdx((i) => (i - 1 + filteredSlash.length) % filteredSlash.length);
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        applySlashCommand(filteredSlash[slashIdx]);
        return;
      }
      if (e.key === "Escape") {
        setShowSlash(false);
        return;
      }
    }
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey || !e.shiftKey)) {
      e.preventDefault();
      send();
    }
  }

  function send() {
    const t = text.trim();
    if (!t) return;
    if (t.startsWith("/")) {
      const cmd = SLASH_COMMANDS.find((c) => t.startsWith(c.cmd));
      if (cmd) {
        applySlashCommand(cmd);
        return;
      }
    }
    if (props.isRunning) {
      props.onIntervene("directive", { text: t });
    } else {
      props.onSend(t);
    }
    reset();
  }

  return (
    <div style={{ position: "relative" }}>
      {/* Constraint chips above the textarea */}
      {props.constraints.length > 0 && (
        <div className="lys-composer__chips">
          {props.constraints.map((c) => (
            <span key={c.id} className="lys-constraint-chip">
              <Beaker size={10} />
              {c.label}
              <button
                className="lys-constraint-chip__close"
                onClick={() => props.onRemoveConstraint(c.id)}
                aria-label="remove"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Slash menu */}
      {showSlash && filteredSlash.length > 0 && (
        <div className="lys-slash-menu" role="listbox">
          {filteredSlash.map((c, i) => (
            <button
              key={c.cmd}
              className={clsx(
                "lys-slash-menu__item",
                i === slashIdx && "lys-slash-menu__item--active"
              )}
              onClick={() => applySlashCommand(c)}
              onMouseEnter={() => setSlashIdx(i)}
            >
              {c.icon}
              <span className="lys-slash-menu__cmd">{c.cmd}</span>
              <span className="lys-slash-menu__desc">{c.desc}</span>
            </button>
          ))}
        </div>
      )}

      <div className="lys-composer">
        <textarea
          ref={taRef}
          className="lys-composer__textarea"
          placeholder={
            props.isRunning
              ? "Intervene mid-loop — type a directive or constraint…"
              : "Describe a target… (e.g. design a non-toxic macrolide for MRSA that escapes mecA)"
          }
          value={text}
          rows={1}
          onChange={(e) => {
            const v = e.target.value;
            setText(v);
            setShowSlash(v.startsWith("/"));
          }}
          onKeyDown={handleKey}
          onFocus={() => setShowSlash(text.startsWith("/"))}
        />
        <button className="lys-composer__push" onClick={send} disabled={!text.trim()}>
          <Send size={14} />
          {props.isRunning ? "Intervene" : "Push"}
        </button>
      </div>
    </div>
  );
}
