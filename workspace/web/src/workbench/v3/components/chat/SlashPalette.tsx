/**
 * SlashPalette — Claude Code-style command palette.
 *
 * Triggered when the composer's text starts with "/". Filters as the user
 * types. Categorized by skill family. Keyboard-first: ↑/↓ navigate, ↵ pick,
 * Esc dismiss.
 *
 * Design (per user redesign brief):
 *   • Tight rows (~30px), no wrapping — every command is a one-liner
 *   • Icon column (category-coded) | mono /cmd | concise description |
 *     mono arg hint — visually scannable like a CLI cheat sheet
 *   • Active row: subtle bg-tint, no border (Claude.ai pattern)
 *   • Category labels are quiet 9.5pt mono caps separators
 *   • Footer keyboard shortcuts as kbd-pills, monospace
 */
import { useEffect, useMemo, useState } from "react";
import {
  Settings, FlaskConical, Edit3, BookOpen, Target, Layers, Shield, Terminal,
  Sparkles,
} from "lucide-react";

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
  | "sandbox"
  | "general";

// Default registry — mirrors workspace/agents/commands.py descriptions.
// The live registry is fetched from /api/commands/list at runtime; this
// is the offline fallback bundled with the JS chunk.
export const DEFAULT_COMMANDS: SlashCommand[] = [
  // SYSTEM
  { name: "help",        description: "List all slash commands",                       category: "system",     aliases: ["?", "skills"] },
  { name: "clear",       description: "Reset the chat & state",                         category: "system" },
  { name: "set-target",  description: "Set the active target pathogen",                 category: "system",     argument_hint: "<pathogen>",      aliases: ["target"] },
  { name: "branch",      description: "Fork the active candidate as a branch",          category: "system",     argument_hint: "<branch hint>",   requires_smiles: true },
  { name: "trace",       description: "Show last N harness events",                     category: "system",     argument_hint: "[n=20]" },
  { name: "run",         description: "Run a Python cell in the sandbox",               category: "sandbox",    argument_hint: "<code>" },

  // DESIGN
  { name: "design",      description: "Start a multi-agent design session",             category: "design",     argument_hint: "<pathogen> [objective]", aliases: ["d"] },
  { name: "scaffold-hop", description: "Bioisosteric scaffold replacements",            category: "design",     argument_hint: "[n=5]", aliases: ["hop"], requires_smiles: true },
  { name: "edit",        description: "Apply a deterministic edit op",                  category: "edit",       argument_hint: "<op>",            aliases: ["e"], requires_smiles: true },

  // SCORING
  { name: "score",       description: "Score with the 12-axis reward stack",            category: "scoring",    argument_hint: "[smiles]" },
  { name: "similar",     description: "Top-K similar antibiotics (embedding)",          category: "scoring",    argument_hint: "[k=5]", aliases: ["sim"], requires_smiles: true },
  { name: "admet",       description: "ADMET panel (A/D/M/E/T predictions)",            category: "scoring",    argument_hint: "[smiles]" },
  { name: "synth",       description: "Retrosynthesis route + cost estimate",           category: "scoring",    argument_hint: "[smiles]" },

  // KNOWLEDGE
  { name: "explain",     description: "Mechanism + spectrum + resistance brief",        category: "knowledge",  argument_hint: "<target|drug>" },

  // STRUCTURAL
  { name: "dock",        description: "Dock candidate vs target PDB",                   category: "structural", argument_hint: "[pdb_id]", aliases: ["docking"], requires_smiles: true },
  { name: "complex",     description: "Predict 3D complex pose (Boltz-2)",              category: "structural", argument_hint: "[pathogen]", requires_smiles: true },

  // AMR
  { name: "resistance",  description: "Resistome + escape probability",                 category: "amr",        argument_hint: "<pathogen>", aliases: ["res"] },
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
  general: "General",
};

// One icon per category — visual rhythm + faster scanning than text alone.
const CATEGORY_ICON: Record<SlashCategory, React.ComponentType<any>> = {
  system: Settings,
  design: FlaskConical,
  edit: Edit3,
  knowledge: BookOpen,
  scoring: Target,
  structural: Layers,
  amr: Shield,
  sandbox: Terminal,
  general: Sparkles,
};

// Defensive fallback if backend ever sends a category we haven't mapped:
// always show *something* instead of crashing the render with undefined.
const FALLBACK_ICON = Sparkles;

interface Props {
  query: string;
  open: boolean;
  onPick: (cmd: SlashCommand) => void;
  onClose: () => void;
  commands?: SlashCommand[];
}

export function SlashPalette({ query, open, onPick, onClose, commands }: Props) {
  const [highlightIdx, setHighlightIdx] = useState(0);

  const all = commands ?? DEFAULT_COMMANDS;

  const prefix = query.startsWith("/") ? query.slice(1).split(" ")[0].toLowerCase() : "";
  const filtered = useMemo(() => {
    if (!prefix) return all;
    return all.filter((c) => {
      const names = [c.name, ...(c.aliases ?? [])];
      return names.some((n) => n.toLowerCase().startsWith(prefix)) ||
             c.description.toLowerCase().includes(prefix);
    });
  }, [all, prefix]);

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

  useEffect(() => {
    setHighlightIdx(0);
  }, [prefix]);

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
      } else if ((e.key === "Enter" || e.key === "Tab") && filtered.length) {
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

  let flatIdx = -1;
  return (
    <div className="lys-slash-palette" role="listbox" aria-label="Slash commands">
      <div className="lys-slash-head">
        <span style={{ fontFamily: "var(--lys-font-mono)", color: "var(--lys-accent)", fontWeight: 600 }}>/</span>
        <span style={{ flex: 1 }}>{filtered.length} command{filtered.length === 1 ? "" : "s"}</span>
        <kbd>↑↓</kbd>
        <kbd>↵</kbd>
        <kbd>esc</kbd>
      </div>
      {grouped.map(({ category, items }) => {
        const Icon = CATEGORY_ICON[category] ?? FALLBACK_ICON;
        return (
          <div key={category} className="lys-slash-group">
            <div className="lys-slash-cat">{CATEGORY_LABELS[category] ?? category}</div>
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
                    e.preventDefault();
                    onPick(cmd);
                  }}
                  onMouseEnter={() => setHighlightIdx(flatIdx)}
                  title={cmd.aliases && cmd.aliases.length
                    ? `aliases: ${cmd.aliases.map((a) => "/" + a).join(", ")}`
                    : undefined}
                >
                  <span className="lys-slash-ico" style={{ color: active ? "var(--lys-accent)" : "var(--lys-text-faint)" }}>
                    <Icon size={12} />
                  </span>
                  <span className="lys-slash-name">/{cmd.name}</span>
                  <span className="lys-slash-desc">{cmd.description}</span>
                  {cmd.argument_hint && (
                    <span className="lys-slash-hint">{cmd.argument_hint}</span>
                  )}
                </button>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
