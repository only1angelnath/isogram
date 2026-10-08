// DailyBars.tsx — per-day bar chart (server-rendered SVG, no libraries).
// null days are drawn as an empty slot (not a zero-height bar), and partial days are
// drawn at reduced opacity so an incomplete day never reads as a real dip.

import { formatDay } from "@/lib/format";

export interface Bar {
  day: string;
  value: number | null;
  partial?: boolean;
}

interface DailyBarsProps {
  bars: Bar[];
  color?: string;
  height?: number;
  format: (v: number | null) => string;
  ariaLabel?: string;
}

export function DailyBars({ bars, color = "var(--accent)", height = 90, format, ariaLabel }: DailyBarsProps) {
  const measured = bars.map((b) => b.value).filter((v): v is number => v !== null);
  if (measured.length === 0) {
    return (
      <div className="mono" style={{ height, fontSize: 11, color: "var(--ink-dim)", display: "flex", alignItems: "center" }}>
        collecting data…
      </div>
    );
  }
  const max = Math.max(...measured, 0) || 1;
  const slot = 100 / bars.length;
  const plotH = height - 6;

  return (
    <div>
      <svg viewBox={`0 0 100 ${height}`} width="100%" height={height} preserveAspectRatio="none" role="img" aria-label={ariaLabel}>
        {bars.map((b, i) =>
          b.value === null ? null : (
            <rect
              key={b.day}
              x={i * slot + slot * 0.12}
              width={slot * 0.76}
              y={plotH - (b.value / max) * plotH + 3}
              height={Math.max((b.value / max) * plotH, 0.8)}
              fill={color}
              opacity={b.partial ? 0.4 : 1}
            >
              <title>{`${formatDay(b.day)}${b.partial ? " (partial)" : ""}: ${format(b.value)}`}</title>
            </rect>
          ),
        )}
      </svg>
      <div className="mono" style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--ink-dim)" }}>
        <span>{formatDay(bars[0].day)}</span>
        <span>{formatDay(bars[bars.length - 1].day)}{bars[bars.length - 1].partial ? " (partial)" : ""}</span>
      </div>
    </div>
  );
}
