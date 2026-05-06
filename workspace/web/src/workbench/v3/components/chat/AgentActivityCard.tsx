/**
 * AgentActivityCard — Claude-style "Reading×2 / Writing×5 / Updated todos"
 * activity box with disclosure arrow + inline list when expanded.
 *
 * Matches the Claude design philosophy: light gray rounded box, lightning
 * bolt or list-icon glyph on the left, "verb + count" or "verb, file"
 * label, and a chevron on the right that toggles a sub-list of items.
 *
 * Used inside ChatPanel timeline as the visual unit for any multi-step
 * tool action: "Writing×5 [styles.css, site.js, ...]" / "Reading×2" /
 * "Updated todos [...]" / "Done, Fork verifier agent [...]".
 *
 * Props design: caller passes a `kind` (icon hint), a `label` (the verb
 * or summary text), and optional `items` (the inline expand list). If
 * no items are provided, the card renders without a chevron.
 */
import { useState } from "react";
import { Zap, ListChecks, ChevronDown, ChevronUp } from "lucide-react";

export interface AgentActivityItem {
  text: string;
  /** Optional second-line subtle annotation, e.g. "8 ms" / "score 0.84" */
  meta?: string;
}

interface Props {
  kind?: "lightning" | "list" | "auto";    // glyph; auto = list when label
                                            // starts with "Updated"
  label: string;                            // "Writing ×5" | "Reading ×2"
                                            // | "Done, Fork verifier agent"
                                            // | "Updated todos"
  items?: AgentActivityItem[];
  defaultOpen?: boolean;
}

export function AgentActivityCard({ kind = "auto", label, items, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const hasItems = !!items && items.length > 0;

  const Icon = (kind === "list" || (kind === "auto" && /update|todo|check/i.test(label)))
    ? ListChecks
    : Zap;

  return (
    <div className="lys-act">
      <button
        type="button"
        className="lys-act-row"
        onClick={() => hasItems && setOpen((o) => !o)}
        aria-expanded={open}
        aria-disabled={!hasItems}
        style={{ cursor: hasItems ? "pointer" : "default" }}
      >
        <Icon size={13} className="lys-act-icon" />
        <span className="lys-act-label">{label}</span>
        {hasItems && (
          <span className="lys-act-toggle">
            {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </span>
        )}
      </button>
      {hasItems && open && (
        <ul className="lys-act-list">
          {items!.map((it, i) => (
            <li key={i} className="lys-act-item">
              <span className="lys-act-bullet">•</span>
              <span className="lys-act-item-text">{it.text}</span>
              {it.meta && <span className="lys-act-item-meta">{it.meta}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
