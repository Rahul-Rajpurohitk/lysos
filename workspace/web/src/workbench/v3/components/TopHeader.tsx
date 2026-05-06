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
}

const MODES: Mode[] = ["Design", "Discover", "Repair", "Robustify"];
const AUTONOMIES: Autonomy[] = ["Co-pilot", "Auto", "Manual"];

// AGENT_COLORS lived here for the (now-removed) ActiveAgents dots; the
// chat panel's filter strip carries its own canonical mapping.

export function TopHeader(props: TopHeaderProps) {
  return (
    <header className="lys-header">
      {/* Brand cluster */}
      <div className="lys-header__brand">
        <BrandMark active={props.isRunning} />
        <div className="lys-header__brand-text">
          <div className="lys-header__brand-name">Lysos</div>
          <div className="lys-header__brand-tag">Workbench · v0.3</div>
        </div>
      </div>

      {/* Center cluster: pathogen + mode + autonomy + iters */}
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

      {/* Right cluster: actions */}
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
  width?: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="lys-pill-selector" style={{ width }}>
      <button
        className="lys-pill"
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
}: {
  pathogens: Pathogen[];
  selected: string;
  onChange: (code: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const sel = pathogens.find((p) => p.code === selected);
  return (
    <div className="lys-pathogen-picker">
      <button className="lys-pill lys-pill--wide" onClick={() => setOpen((o) => !o)}>
        <span className="lys-pathogen-picker__code">{sel?.code ?? selected}</span>
        <span className="lys-pathogen-picker__name">{sel?.name ?? "— pick pathogen —"}</span>
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
