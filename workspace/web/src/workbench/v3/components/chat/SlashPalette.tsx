/**
 * SlashPalette — Claude-Code-style command palette.
 *
 * Triggered when the composer's text starts with "/". Filters as the user
 * types. Categorized by skill family (generative / knowledge / scoring /
 * structural / amr / sandbox / system). Keyboard-first: ↑/↓ navigate,
 * ↵ select, Esc dismiss.
 *
 * Design choices:
 *  - No card backgrounds. Soft top border, generous row padding.
 *  - Category headers as small caps, muted color — visible only when 2+
 *    items in a category remain after filter.
 *  - Right-side argument hint in monospace, dimmed, only when present.
 *  - The whole palette is one column, no grids, no badges.
 *  - Renders OVER the composer, not above it (z-index 50, anchored bottom).
 */
import { useEffect, useMemo, useState } from "react";

export interface SlashCommand {
  name: string;                     // "design", "edit", ...
  description: string;
  category: SlashCategory;
  argument_hint?: string;
  aliases?: string[];
  requires_smiles?: boolean;
  requires_target?: boolean;
}

export type SlashCategory =
  | "system"
  | "design"
  | "edit"
  | "knowledge"
  | "scoring"
  | "structural"
  | "amr"
  | "sandbox";

// Default registry — kept in sync with workspace/agents/commands.py.
// Order here is the display order within each category.
export const DEFAULT_COMMANDS: SlashCommand[] = [
  // SYSTEM
  { name: "help",        description: "Show available skills",                       category: "system",     aliases: ["?", "skills"] },
  { name: "clear",       description: "Clear the active session",                    category: "system" },
  { name: "set-target",  description: "Set the active target pathogen",              category: "system",     argument_hint: "<pathogen>",  aliases: ["target"] },
  { name: "branch",      description: "Fork the active candidate as a new lineage",  category: "system",     argument_hint: "<hint>",       requires_smiles: true },
  { name: "run",         description: "Execute a Python cell in the sandbox",        category: "sandbox",    argument_hint: "<python>" },

  // DESIGN
  { name: "design",      description: "Propose new candidates for a target",         category: "design",     argument_hint: "<pathogen|target>", aliases: ["d"] },
  { name: "scaffold-hop", description: "Bioisosteric scaffold replacement",          category: "design",     argument_hint: "[n=5]", aliases: ["hop"], requires_smiles: true },
  { name: "edit",        description: "Apply a deterministic structural transform",  category: "edit",       argument_hint: "<op>",         aliases: ["e"], requires_smiles: true },

  // SCORING
  { name: "score",       description: "Run the 12-component reward stack",           category: "scoring",    argument_hint: "[smiles]" },
  { name: "similar",     description: "Top-K similar known antibiotics",             category: "scoring",    argument_hint: "[k=5]", aliases: ["sim"], requires_smiles: true },

  // KNOWLEDGE
  { name: "explain",     description: "Mechanism + spectrum + resistance",           category: "knowledge",  argument_hint: "<drug_name>" },

  // AMR
  { name: "resistance",  description: "Pathogen resistome + escape probability",     category: "amr",        argument_hint: "<pathogen>", aliases: ["res"] },
];

const CATEGORY_LABELS: Record<SlashCategory, string> = {
  system: "Session",
  design: "Design",
  edit: "Edit",
  knowledge: "Knowledge",
  scoring: "Scoring",
  structural: "Structural",
  amr: "AMR",
  sandbox: "Sandbox",
};

interface Props {
  /** Composer's current input. We slice the leading slash off internally. */
  query: string;
  /** Whether the palette is visible (parent toggles based on `query.startsWith("/")`) */
  open: boolean;
  /** Called when user picks a command — parent fills the composer. */
  onPick: (cmd: SlashCommand) => void;
  /** Called when user dismisses (Esc or click outside) */
  onClose: () => void;
  /** Optional override (e.g. fetched from /api/commands/list) */
  commands?: SlashCommand[];
}

export function SlashPalette({ query, open, onPick, onClose, commands }: Props) {
  const [highlightIdx, setHighlightIdx] = useState(0);

  const all = commands ?? DEFAULT_COMMANDS;

  // Filter by stripped query (the prefix after the slash)
  const prefix = query.startsWith("/") ? query.slice(1).split(" ")[0].toLowerCase() : "";
  const filtered = useMemo(() => {
    if (!prefix) return all;
    return all.filter((c) => {
      const names = [c.name, ...(c.aliases ?? [])];
      return names.some((n) => n.toLowerCase().startsWith(prefix)) ||
             c.description.toLowerCase().includes(prefix);
    });
  }, [all, prefix]);

  // Group by category, keeping the order from `filtered`
  const grouped = useMemo(() => {
    const order: SlashCategory[] = [];
    const map = new Map<SlashCategory, SlashCommand[]>();
    for (const cmd of filtered) {
      if (!map.has(cmd.category)) {
        map.set(cmd.category, []);
        order.push(cmd.category);
      }
      map.get(cmd.category)!.push(cmd);
    }
    return order.map((cat) => ({ category: cat, items: map.get(cat)! }));
  }, [filtered]);

  // Reset highlight when filter changes
  useEffect(() => {
    setHighlightIdx(0);
  }, [prefix]);

  // Keyboard handlers (parent should attach this to the composer textarea)
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlightIdx((i) => Math.min(i + 1, filtered.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlightIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" && filtered.length) {
        e.preventDefault();
        onPick(filtered[highlightIdx]);
      } else if (e.key === "Tab" && filtered.length) {
        e.preventDefault();
        onPick(filtered[highlightIdx]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, filtered, highlightIdx, onPick, onClose]);

  if (!open) return null;
  if (filtered.length === 0) {
    return (
      <div className="lys-slash-palette lys-slash-empty" role="listbox">
        <div className="lys-slash-empty-text">
          No commands match <code>/{prefix}</code>. Type <kbd>/help</kbd> for the full list.
        </div>
      </div>
    );
  }

  // Compute flat index from grouped layout
  let flatIdx = -1;
  return (
    <div className="lys-slash-palette" role="listbox" aria-label="Skill commands">
      {grouped.map(({ category, items }) => (
        <div key={category} className="lys-slash-group">
          <div className="lys-slash-cat">{CATEGORY_LABELS[category]}</div>
          {items.map((cmd) => {
            flatIdx++;
            const active = flatIdx === highlightIdx;
            return (
              <button
                key={cmd.name}
                type="button"
                role="option"
                aria-selected={active}
                className={`lys-slash-row ${active ? "is-active" : ""}`}
                onMouseDown={(e) => {
                  // mousedown not click — fires before composer blurs
                  e.preventDefault();
                  onPick(cmd);
                }}
                onMouseEnter={() => setHighlightIdx(flatIdx)}
              >
                <span className="lys-slash-name">/{cmd.name}</span>
                <span className="lys-slash-desc">{cmd.description}</span>
                {cmd.argument_hint && (
                  <span className="lys-slash-hint">{cmd.argument_hint}</span>
                )}
              </button>
            );
          })}
        </div>
      ))}
      <div className="lys-slash-foot">
        <kbd>↑↓</kbd> navigate &nbsp; <kbd>↵</kbd> pick &nbsp; <kbd>esc</kbd> close
      </div>
    </div>
  );
}
