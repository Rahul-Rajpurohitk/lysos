import { ChevronsLeft, Play, Pause, ChevronsRight } from "lucide-react";
import clsx from "clsx";

interface IterationStripProps {
  totalIters: number;
  currentIter: number;
  iterCompositeMap: Record<number, number>; // iter -> composite
  isPlaying: boolean;
  onPlayPause: () => void;
  onPrev: () => void;
  onNext: () => void;
  onSeek: (iter: number) => void;
  speed: 1 | 2 | 4;
  onSpeedChange: (s: 1 | 2 | 4) => void;
}

export function IterationStrip(p: IterationStripProps) {
  const segs = Array.from({ length: Math.max(1, p.totalIters) }, (_, i) => i + 1);
  return (
    <div className="lys-iter-strip">
      <span className="lys-iter-strip__label" style={{
        fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase",
        color: "var(--lys-text-faint)",
      }}>
        Iter
      </span>
      <span className="lys-iter-strip__num">
        {p.currentIter}/{p.totalIters}
      </span>
      <div className="lys-iter-strip__bar">
        {segs.map((n) => {
          const done = n < p.currentIter;
          const active = n === p.currentIter;
          const composite = p.iterCompositeMap[n];
          return (
            <button
              key={n}
              className={clsx(
                "lys-iter-segment",
                done && "lys-iter-segment--done",
                active && "lys-iter-segment--active"
              )}
              onClick={() => p.onSeek(n)}
              title={composite != null ? `iter ${n} · composite ${composite.toFixed(3)}` : `iter ${n}`}
              aria-label={`go to iteration ${n}`}
            />
          );
        })}
      </div>
      <div className="lys-iter-strip__playback">
        <button onClick={p.onPrev} title="prev iteration">
          <ChevronsLeft size={14} />
        </button>
        <button onClick={p.onPlayPause} title={p.isPlaying ? "pause" : "play"}>
          {p.isPlaying ? <Pause size={14} /> : <Play size={14} fill="currentColor" />}
        </button>
        <button onClick={p.onNext} title="next iteration">
          <ChevronsRight size={14} />
        </button>
        <button
          onClick={() => p.onSpeedChange(p.speed === 1 ? 2 : p.speed === 2 ? 4 : 1)}
          title={`playback speed: ${p.speed}x`}
          style={{ fontFamily: "var(--lys-font-mono)", fontSize: 10, fontWeight: 600 }}
        >
          {p.speed}x
        </button>
      </div>
    </div>
  );
}
