import { useEffect, useRef, useState } from "react";
import clsx from "clsx";

interface TabStripProps<T extends string> {
  tabs: readonly T[];
  active: T;
  onChange: (t: T) => void;
}

export function TabStrip<T extends string>({ tabs, active, onChange }: TabStripProps<T>) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [indicator, setIndicator] = useState<{ left: number; width: number }>({ left: 0, width: 0 });

  useEffect(() => {
    const el = refs.current[active];
    if (el) {
      setIndicator({ left: el.offsetLeft, width: el.offsetWidth });
    }
  }, [active, tabs.length]);

  return (
    <div className="lys-tabs">
      {tabs.map((t) => (
        <button
          key={t}
          ref={(el) => (refs.current[t] = el)}
          className={clsx("lys-tabs__btn", t === active && "lys-tabs__btn--active")}
          onClick={() => onChange(t)}
        >
          {t}
        </button>
      ))}
      <span
        className="lys-tabs__indicator"
        style={{ left: indicator.left, width: indicator.width }}
      />
    </div>
  );
}
