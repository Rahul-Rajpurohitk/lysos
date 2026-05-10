import { Play, Download, RotateCcw, ChevronDown } from "lucide-react";
import clsx from "clsx";
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";

export interface Pathogen {
  code: string;
  name: string;
  priority: "critical" | "high";
  resistanceCount?: number;
  firstLineCount?: number;
}

type Mode = "Design" | "Discover" | "Repair" | "Robustify";
type Autonomy = "Co-pilot" | "Auto" | "Manual";

interface TopHeaderProps {
  pathogens: Pathogen[];
  selectedPathogen: string;
  onPathogenChange: (code: string) => void;
  mode: Mode;
  onModeChange: (m: Mode) => void;
  autonomy: Autonomy;
  onAutonomyChange: (a: Autonomy) => void;
  iters: number;
  onItersChange: (n: number) => void;
  onStart: () => void;
  onExport: () => void;
  onReset: () => void;
  isRunning: boolean;
  composite: number | null;
  paretoCount: number;
  resistanceCount: number;
  firstLineCount: number;
  activeAgents: string[];
  sessionId: string | null;
  /** Optional inline tab strip rendered between center cluster + actions
   *  (tabs from TabbedView merged into the same row to kill the second navbar). */
  tabsSlot?: React.ReactNode;
  /** When set, the LEFT cluster is fixed to this width (in px) so the
   *  nav-bar's internal left/right split tracks the Allotment chat-pane
   *  divider dynamically. The right cluster fills whatever is left. */
  leftClusterWidth?: number;
}

const MODES: Mode[] = ["Design", "Discover", "Repair", "Robustify"];
const AUTONOMIES: Autonomy[] = ["Co-pilot", "Auto", "Manual"];

// AGENT_COLORS lived here for the (now-removed) ActiveAgents dots; the
// chat panel's filter strip carries its own canonical mapping.

export function TopHeader(props: TopHeaderProps) {
  const compact = !!props.tabsSlot;
  const leftWidth = props.leftClusterWidth;
  return (
    <header
      className="lys-header"
      style={compact ? {
        // Override the default 3-column grid (auto 1fr auto). Compact
        // mode is a flexbox row split into TWO segments:
        //   LEFT  — brand · controls · actions (chat-pane side)
        //   RIGHT — view-toggle · tabs (playground side)
        // The left segment's width tracks the Allotment chat-pane width
        // so the nav-bar split aligns with the body's vertical divider.
        display: "flex", gap: 0, padding: "4px 0",
      } : undefined}>
      {compact ? (
        <>
          {/* LEFT segment — chat-pane side. SaaS-agentic minimal chrome.
              Just brand · pathogen · status pill. Mode / Design / Iters /
              Start / Export / Reset are all chat slash commands now —
              no UI buttons. The agent observes + acts; the user types
              /design /run /export /reset in the chat thread. */}
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            width: leftWidth ? `${leftWidth}px` : "auto",
            flex: leftWidth ? "0 0 auto" : "0 0 auto",
            paddingLeft: 10, paddingRight: 8,
            minWidth: 0, overflow: "hidden",
          }}>
            <div className="lys-header__brand" title="Lysos · Workbench · v0.3"
              style={{ flex: "0 0 auto" }}>
              <BrandMark active={props.isRunning} />
            </div>
            <PathogenPicker
              pathogens={props.pathogens}
              selected={props.selectedPathogen}
              onChange={props.onPathogenChange}
              compact={true}
            />
            <StatusPill running={props.isRunning} />
            <span style={{ flex: 1, minWidth: 0 }} />
          </div>

          {/* RIGHT segment — playground side. Naturally fills the rest of
              the row, no border so the visual divider IS the Allotment
              divider's vertical split, not an extra line on the nav.
              The tabs strip itself owns its own overflow — we just give
              it a min-width:0 box to live in. */}
          <div style={{
            flex: "1 1 0", minWidth: 0,
            display: "flex", alignItems: "stretch",
            paddingLeft: 0, paddingRight: 4,
          }}>
            {props.tabsSlot}
          </div>
        </>
      ) : (
        <>
          <div className="lys-header__brand" title="Lysos · Workbench · v0.3">
            <BrandMark active={props.isRunning} />
          </div>
          <div className="lys-header__center">
            <PathogenPicker
              pathogens={props.pathogens}
              selected={props.selectedPathogen}
              onChange={props.onPathogenChange}
            />
            <PillSelector<Mode>
              options={MODES}
              value={props.mode}
              onChange={props.onModeChange}
              width={120}
            />
            <PillSelector<Autonomy>
              options={AUTONOMIES}
              value={props.autonomy}
              onChange={props.onAutonomyChange}
              width={110}
            />
            <div className="lys-header__iters">
              <span className="lys-header__iters-label">Iters</span>
              <input
                className="lys-header__iters-input"
                type="number"
                min={1}
                max={20}
                value={props.iters}
                onChange={(e) => props.onItersChange(parseInt(e.target.value || "1", 10))}
              />
            </div>
          </div>
          <div className="lys-header__actions">
            <button
              onClick={props.onStart}
              disabled={props.isRunning}
              className={clsx("lys-header__btn-primary", props.isRunning && "lys-header__btn-primary--running")}
            >
              <Play size={14} fill="white" /> {props.isRunning ? "Running…" : "Start"}
            </button>
            <button onClick={props.onExport} className="lys-header__btn-ghost" title="Export session">
              <Download size={14} />
            </button>
            <button onClick={props.onReset} className="lys-header__btn-ghost" title="Reset">
              <RotateCcw size={14} />
            </button>
          </div>
        </>
      )}
    </header>
  );
}

function BrandMark({ active }: { active: boolean }) {
  return (
    <motion.div
      className="lys-brandmark"
      animate={active ? { boxShadow: ["0 0 0 0 rgba(52,211,153,0.6)", "0 0 0 6px rgba(52,211,153,0)"] } : {}}
      transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
    >
      <span className="lys-brandmark__glyph">L</span>
    </motion.div>
  );
}

function PillSelector<T extends string>({
  options,
  value,
  onChange,
  width,
}: {
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  /** When omitted, the closed pill auto-sizes to the current label
   *  (just text + chevron + tight padding). The dropdown menu still
   *  renders at its natural width to fit longer option labels. */
  width?: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="lys-pill-selector"
      style={width ? { width } : { width: "auto", flex: "0 0 auto" }}>
      <button
        className="lys-pill"
        style={!width ? { width: "auto", padding: "0 8px", minWidth: 0 } : undefined}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span>{value}</span>
        <ChevronDown size={12} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.ul
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="lys-pill__menu"
            role="listbox"
          >
            {options.map((opt) => (
              <li
                key={opt}
                className={clsx("lys-pill__item", opt === value && "lys-pill__item--active")}
                onClick={() => {
                  onChange(opt);
                  setOpen(false);
                }}
                role="option"
                aria-selected={opt === value}
              >
                {opt}
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}

function PathogenPicker({
  pathogens,
  selected,
  onChange,
  compact,
}: {
  pathogens: Pathogen[];
  selected: string;
  onChange: (code: string) => void;
  /** When true, hides the full Latin pathogen name (kept in tooltip)
   *  so the picker fits in a single shared nav row. */
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const sel = pathogens.find((p) => p.code === selected);
  return (
    <div className="lys-pathogen-picker"
      style={compact ? { width: "auto", flex: "0 0 auto" } : undefined}>
      <button
        className={clsx("lys-pill", !compact && "lys-pill--wide")}
        style={compact ? { width: "auto", padding: "0 8px", minWidth: 0 } : undefined}
        onClick={() => setOpen((o) => !o)}
        title={sel?.name ?? "Pick pathogen"}>
        <span className="lys-pathogen-picker__code">{sel?.code ?? selected}</span>
        {!compact && (
          <span className="lys-pathogen-picker__name">{sel?.name ?? "— pick pathogen —"}</span>
        )}
        <ChevronDown size={12} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            className="lys-pill__menu lys-pill__menu--pathogens"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
          >
            {pathogens.map((p) => (
              <button
                key={p.code}
                className={clsx("lys-pathogen-picker__row", p.code === selected && "lys-pathogen-picker__row--active")}
                onClick={() => {
                  onChange(p.code);
                  setOpen(false);
                }}
              >
                <span className="lys-pathogen-picker__row-code">{p.code}</span>
                <span className="lys-pathogen-picker__row-name">{p.name}</span>
                <span className={clsx("lys-pathogen-picker__row-tier", `lys-pathogen-picker__row-tier--${p.priority ?? "high"}`)}>
                  {p.priority ?? "—"}
                </span>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// SummaryRibbon + CompositeGauge + RibbonStat + ActiveAgents removed in
// the single-navbar redesign. They moved into per-panel headers
// (right-side artifact panel meta strip + chat panel agent dots) so
// the top nav stays one tight row, Claude.ai-style.


/** StatusPill — passive run-state indicator that replaces the old
 *  Start CTA. The user triggers runs via chat slash commands; this
 *  pill is observation only (pulsing green dot when running, idle
 *  grey otherwise). */
function StatusPill({ running }: { running: boolean }) {
  return (
    <div
      title={running ? "Agent loop running — type /pause or /reset in chat to control" : "Idle — type /design or /run in chat to start"}
      style={{
        display: "inline-flex", alignItems: "center", gap: 5,
        height: 22, padding: "0 8px",
        borderRadius: 4, fontFamily: "var(--lys-font-mono)",
        fontSize: 9.5, letterSpacing: "0.04em", textTransform: "uppercase",
        fontWeight: 600,
        background: running ? "rgba(16,185,129,0.12)" : "rgba(0,0,0,0.04)",
        border: `1px solid ${running ? "rgba(16,185,129,0.30)" : "rgba(0,0,0,0.08)"}`,
        color: running ? "#059669" : "var(--lys-text-faint)",
        flex: "0 0 auto", userSelect: "none",
      }}>
      <motion.span
        animate={running ? {
          opacity: [0.4, 1, 0.4],
          scale: [0.9, 1.1, 0.9],
        } : {}}
        transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
        style={{
          width: 6, height: 6, borderRadius: 6,
          background: running ? "#10b981" : "#94a3b8",
          flexShrink: 0,
        }} />
      <span>{running ? "running" : "idle"}</span>
    </div>
  );
}
