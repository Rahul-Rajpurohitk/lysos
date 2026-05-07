import { useEffect, useMemo, useState } from "react";
import { Beaker, Cpu, Github, Loader2, Search, Sparkles, X, Zap } from "lucide-react";
import clsx from "clsx";
import {
  type Candidate,
  type DesignResponse,
  type Pathogen,
  type SimilarHit,
  design,
  fetchHealth,
  fetchPathogens,
  findSimilar,
  type Health,
} from "./api";

export default function App() {
  const [pathogens, setPathogens] = useState<Pathogen[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [selected, setSelected] = useState<string>("MRSA");
  const [n, setN] = useState(20);
  const [temperature, setTemperature] = useState(1.0);
  const [modality, setModality] = useState<"smiles" | "peptide">("smiles");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<DesignResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPathogens().then(setPathogens).catch((e) => setError(e.message));
    fetchHealth().then(setHealth).catch(() => {});
  }, []);

  const selectedPathogen = useMemo(
    () => pathogens.find((p) => p.short === selected),
    [pathogens, selected]
  );

  async function onDesign() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await design({
        target: selected,
        n,
        temperature,
        modality,
        return_top: n,
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Header health={health} />

      <main className="max-w-7xl mx-auto w-full px-4 lg:px-8 py-8 grid lg:grid-cols-[280px_1fr] gap-6 flex-1">
        <aside className="space-y-4">
          <PathogenList
            pathogens={pathogens}
            selected={selected}
            onSelect={setSelected}
          />
        </aside>

        <section className="space-y-6">
          {selectedPathogen && (
            <PathogenHeader pathogen={selectedPathogen} />
          )}

          <ControlPanel
            n={n}
            setN={setN}
            temperature={temperature}
            setTemperature={setTemperature}
            modality={modality}
            setModality={setModality}
            running={running}
            onRun={onDesign}
          />

          {error && (
            <div className="card border-bad-500/40 text-bad-400">
              ⚠ {error}
            </div>
          )}

          {result && <ResultsView result={result} />}
        </section>
      </main>

      <Footer />
    </div>
  );
}

// ---------------------------------------------------------------------------

function Header({ health }: { health: Health | null }) {
  return (
    <header className="border-b border-ink-700/50 bg-ink-900/40 backdrop-blur sticky top-0 z-10">
      <div className="max-w-7xl mx-auto px-4 lg:px-8 h-14 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent-400 to-accent-600 flex items-center justify-center text-ink-950">
            <Beaker className="w-4 h-4" />
          </div>
          <div>
            <h1 className="font-mono text-lg tracking-tight">lysos</h1>
            <p className="text-[10px] text-slate-500 -mt-0.5 uppercase tracking-widest">
              generative drug designer · AMR
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {health && (
            <div className="flex items-center gap-2 text-xs text-slate-400 font-mono">
              <Cpu className="w-3 h-3" />
              <span>{health.model?.split("/").pop() ?? "model"}</span>
              <span
                className={clsx(
                  "w-1.5 h-1.5 rounded-full animate-pulse-slow",
                  health.loaded ? "bg-accent-500" : "bg-warn-500"
                )}
              />
            </div>
          )}
          <a
            href="https://github.com/Rahul-Rajpurohitk/lysos"
            target="_blank"
            rel="noreferrer"
            className="btn-ghost flex items-center gap-1 text-sm"
          >
            <Github className="w-4 h-4" />
            <span className="hidden md:inline">github</span>
          </a>
        </div>
      </div>
    </header>
  );
}

function PathogenList({
  pathogens,
  selected,
  onSelect,
}: {
  pathogens: Pathogen[];
  selected: string;
  onSelect: (s: string) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="text-xs uppercase tracking-widest text-slate-500 font-mono px-1">
        target pathogen
      </div>
      <div className="space-y-1">
        {pathogens.map((p) => (
          <button
            key={p.short}
            onClick={() => onSelect(p.short)}
            className={clsx(
              "w-full text-left px-3 py-2.5 rounded-lg border transition-colors",
              selected === p.short
                ? "bg-accent-500/10 border-accent-500/40 text-slate-100"
                : "bg-transparent border-ink-700/50 text-slate-300 hover:bg-ink-800/40 hover:border-ink-600"
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="font-mono text-sm">{p.short}</div>
                <div className="text-xs text-slate-500 truncate mt-0.5">
                  {p.name}
                </div>
              </div>
              <span
                className={
                  p.priority === "critical" ? "pill-critical" : "pill-high"
                }
              >
                {p.priority}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function PathogenHeader({ pathogen }: { pathogen: Pathogen }) {
  return (
    <div className="card animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs uppercase tracking-widest text-slate-500 font-mono">
            target
          </div>
          <h2 className="text-2xl font-medium mt-1">{pathogen.name}</h2>
        </div>
        <span
          className={
            pathogen.priority === "critical" ? "pill-critical" : "pill-high"
          }
        >
          {pathogen.priority} priority
        </span>
      </div>
      <p className="text-slate-400 mt-3 text-sm leading-relaxed">
        {pathogen.description}
      </p>
    </div>
  );
}

function ControlPanel({
  n,
  setN,
  temperature,
  setTemperature,
  modality,
  setModality,
  running,
  onRun,
}: {
  n: number;
  setN: (v: number) => void;
  temperature: number;
  setTemperature: (v: number) => void;
  modality: "smiles" | "peptide";
  setModality: (m: "smiles" | "peptide") => void;
  running: boolean;
  onRun: () => void;
}) {
  return (
    <div className="card">
      <div className="flex items-center gap-2 mb-4">
        <Sparkles className="w-4 h-4 text-accent-400" />
        <h3 className="font-medium text-sm uppercase tracking-widest text-slate-300">
          Generation parameters
        </h3>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Slider
          label="candidates"
          value={n}
          min={5}
          max={100}
          step={5}
          onChange={setN}
        />
        <Slider
          label="temperature"
          value={temperature}
          min={0.5}
          max={1.5}
          step={0.1}
          format={(v) => v.toFixed(1)}
          onChange={setTemperature}
        />
        <ModalitySelect modality={modality} setModality={setModality} />
      </div>
      <div className="mt-5 flex items-center justify-between gap-3">
        <div className="text-xs text-slate-500 font-mono">
          model: <span className="text-slate-300">rahul24raj/lysos-base-dpo</span> ·{" "}
          mi300x · gemma-4-31b
        </div>
        <button
          onClick={onRun}
          disabled={running}
          className="btn-primary flex items-center gap-2"
        >
          {running ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              designing...
            </>
          ) : (
            <>
              <Zap className="w-4 h-4" />
              generate {n} candidates
            </>
          )}
        </button>
      </div>
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-xs">
        <span className="uppercase tracking-widest text-slate-500 font-mono">
          {label}
        </span>
        <span className="text-accent-400 font-mono">
          {format ? format(value) : value}
        </span>
      </div>
      <input
        type="range"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full mt-2 accent-accent-500"
      />
    </div>
  );
}

function ModalitySelect({
  modality,
  setModality,
}: {
  modality: "smiles" | "peptide";
  setModality: (m: "smiles" | "peptide") => void;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-widest text-slate-500 font-mono">
        modality
      </div>
      <div className="grid grid-cols-2 gap-1 mt-2 p-1 bg-ink-900 rounded-lg border border-ink-700/50">
        {(["smiles", "peptide"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setModality(m)}
            className={clsx(
              "py-1.5 rounded text-xs font-mono transition-colors",
              modality === m
                ? "bg-accent-500 text-ink-950"
                : "text-slate-400 hover:text-slate-200"
            )}
          >
            {m === "smiles" ? "small molecule" : "peptide"}
          </button>
        ))}
      </div>
    </div>
  );
}

function ResultsView({ result }: { result: DesignResponse }) {
  return (
    <div className="space-y-4 animate-fade-in">
      <div className="flex items-center justify-between">
        <h3 className="font-medium text-sm uppercase tracking-widest text-slate-300">
          Top {result.candidates.length} candidates · {result.target}
        </h3>
        <div className="text-xs text-slate-500 font-mono">
          {result.elapsed_s.toFixed(1)}s · {result.n_total} generated ·{" "}
          {(result.aggregate.validity_rate * 100).toFixed(0)}% valid
        </div>
      </div>
      <AggregateBar aggregate={result.aggregate} />
      <div className="space-y-2">
        {result.candidates.map((c, i) => (
          <CandidateCard key={i} index={i + 1} candidate={c} />
        ))}
      </div>
    </div>
  );
}

function AggregateBar({ aggregate }: { aggregate: Record<string, number> }) {
  const components: Array<[string, string]> = [
    ["validity", "mean_validity"],
    ["MIC", "mean_predicted_mic"],
    ["QED", "mean_drug_likeness_qed"],
    ["synth", "mean_synthesizability"],
    ["safety", "mean_hemolysis_safety"],
    ["novelty", "mean_novelty"],
  ];
  return (
    <div className="card grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {components.map(([label, key]) => {
        const v = aggregate[key] ?? 0;
        return (
          <div key={key} className="text-center">
            <div className="text-[10px] uppercase tracking-widest text-slate-500 font-mono">
              {label}
            </div>
            <div className="text-lg font-mono mt-1">{v.toFixed(2)}</div>
            <div className="h-1 w-full bg-ink-900 rounded-full mt-1 overflow-hidden">
              <div
                className="h-full bg-accent-500 transition-all"
                style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function CandidateCard({ index, candidate }: { index: number; candidate: Candidate }) {
  const score = candidate.combined;
  const tone =
    score > 0.6 ? "good" : score > 0.4 ? "warn" : "bad";
  const [similar, setSimilar] = useState<SimilarHit[] | null>(null);
  const [loadingSim, setLoadingSim] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);

  async function onFindSimilar() {
    if (!candidate.smiles) return;
    setLoadingSim(true);
    setSimError(null);
    try {
      const hits = await findSimilar(candidate.smiles, 5);
      setSimilar(hits);
    } catch (e) {
      setSimError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingSim(false);
    }
  }

  return (
    <div className="card card-hover">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <span
            className={clsx(
              "w-7 h-7 rounded-md grid place-items-center font-mono text-xs",
              tone === "good" && "bg-good-500/15 text-good-400",
              tone === "warn" && "bg-warn-500/15 text-warn-400",
              tone === "bad" && "bg-bad-500/15 text-bad-400"
            )}
          >
            {index}
          </span>
          <div className="min-w-0 flex-1">
            <div className="font-mono text-sm break-all">
              {candidate.smiles ?? candidate.sequence ?? "(invalid)"}
            </div>
            <ScoresStrip scores={candidate.scores} />
          </div>
        </div>
        <div className="flex items-center gap-3">
          {candidate.smiles && (
            <button
              onClick={onFindSimilar}
              disabled={loadingSim}
              title="Find known antibiotics most similar to this generated molecule"
              className="btn-ghost flex items-center gap-1 text-xs disabled:opacity-50"
            >
              {loadingSim ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Search className="w-3 h-3" />
              )}
              <span>similar</span>
            </button>
          )}
          <div className="text-right">
            <div className="text-xs uppercase tracking-widest text-slate-500 font-mono">
              score
            </div>
            <div
              className={clsx(
                "text-xl font-mono mt-0.5",
                tone === "good" && "text-good-400",
                tone === "warn" && "text-warn-400",
                tone === "bad" && "text-bad-400"
              )}
            >
              {score.toFixed(2)}
            </div>
          </div>
        </div>
      </div>

      {(similar || simError) && (
        <div className="mt-3 pt-3 border-t border-ink-700/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] uppercase tracking-widest text-slate-500 font-mono">
              top {similar?.length ?? 0} known antibiotics (Gemini Embedding 2 cosine)
            </span>
            <button
              onClick={() => { setSimilar(null); setSimError(null); }}
              className="text-slate-500 hover:text-slate-300"
              title="Close similar panel"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
          {simError && (
            <div className="text-xs text-bad-400 font-mono">⚠ {simError}</div>
          )}
          {similar?.map((h, i) => (
            <div key={i} className="flex items-center justify-between gap-3 text-xs py-1">
              <span className="font-mono truncate min-w-0 flex-1 text-slate-300">
                {h.name || h.smiles.slice(0, 40)}
              </span>
              <div className="flex items-center gap-2 shrink-0">
                <div className="w-20 h-1 bg-ink-900 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-accent-500"
                    style={{ width: `${Math.max(0, Math.min(1, h.similarity)) * 100}%` }}
                  />
                </div>
                <span className="font-mono text-accent-400 w-12 text-right">
                  {(h.similarity * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ScoresStrip({ scores }: { scores: Candidate["scores"] }) {
  const items: Array<[string, number]> = [
    ["MIC", scores.predicted_mic],
    ["QED", scores.drug_likeness_qed],
    ["SA", scores.synthesizability],
    ["safety", scores.hemolysis_safety],
    ["novelty", scores.novelty],
  ];
  return (
    <div className="flex items-center gap-3 mt-1.5 text-[11px] font-mono text-slate-400 flex-wrap">
      {items.map(([label, v]) => (
        <span key={label} className="flex items-center gap-1">
          <span className="text-slate-500">{label}</span>
          <span
            className={clsx(
              v > 0.6 && "text-good-400",
              v > 0.4 && v <= 0.6 && "text-warn-400",
              v <= 0.4 && "text-bad-400"
            )}
          >
            {v.toFixed(2)}
          </span>
        </span>
      ))}
    </div>
  );
}

function Footer() {
  return (
    <footer className="border-t border-ink-700/50 mt-12">
      <div className="max-w-7xl mx-auto px-4 lg:px-8 py-6 text-xs text-slate-500 font-mono flex flex-wrap items-center gap-x-6 gap-y-2">
        <span>lysos · v0.1</span>
        <span>·</span>
        <a
          href="https://lablab.ai/ai-hackathons/amd-developer"
          target="_blank"
          rel="noreferrer"
          className="hover:text-slate-300"
        >
          AMD Developer Hackathon 2026
        </a>
        <span>·</span>
        <span>built on gemma-4-31b · trained on amd mi300x · MIT licensed</span>
      </div>
    </footer>
  );
}
