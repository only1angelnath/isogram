// Sparkline.tsx — an ANIMATED line of real data (server-rendered SVG, no libraries).
//
// Used for the hero's mini charts. The previous hero charts were decorative fixed curves
// (against docs/BRANDING.md §5's honest-stats rule); this plots the real series and keeps
// the motion: the line draws itself on load (CSS, see IsoStyles), a dot travels along the
// real path (SVG animateMotion), and the newest point pulses.
// Rules: null = "no data" and BREAKS the line (never drawn as 0); fewer than two measured
// points shows "collecting data…"; a partial last point is dashed.

interface SparklineProps {
  values: (number | null)[];
  color?: string;
  height?: number;
  lastPartial?: boolean;
  ariaLabel?: string;
  /** Disable the travelling dot / pulse (e.g. for dense lists). */
  still?: boolean;
}

const W = 160;

export function Sparkline({ values, color = "var(--accent)", height = 50, lastPartial = false, ariaLabel, still = false }: SparklineProps) {
  const measured = values.filter((v): v is number => v !== null);
  if (measured.length < 2) {
    return (
      <div className="mono" style={{ height, fontSize: 11, color: "var(--ink-dim)", display: "flex", alignItems: "center" }}>
        collecting data…
      </div>
    );
  }

  const min = Math.min(...measured);
  const max = Math.max(...measured);
  const span = max - min || 1;
  const padY = 6;
  const padX = 4;
  const x = (i: number) => padX + (i / (values.length - 1)) * (W - padX * 2);
  const y = (v: number) => padY + (1 - (v - min) / span) * (height - padY * 2);

  const lastIndex = values.length - 1;
  const runs: string[] = [];
  let current = "";
  values.forEach((v, i) => {
    if (v === null || (lastPartial && i === lastIndex)) {
      if (current) runs.push(current);
      current = "";
      return;
    }
    current += `${current ? " L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
  });
  if (current) runs.push(current);

  let dashed: string | null = null;
  const last = values[lastIndex];
  const prev = values[lastIndex - 1];
  if (lastPartial && last !== null && prev !== null && prev !== undefined) {
    dashed = `M${x(lastIndex - 1).toFixed(1)} ${y(prev).toFixed(1)} L${x(lastIndex).toFixed(1)} ${y(last).toFixed(1)}`;
  }

  // Path for the travelling dot: the measured points joined in order.
  const travel = values
    .map((v, i) => (v === null ? null : `${x(i).toFixed(1)} ${y(v).toFixed(1)}`))
    .filter((p): p is string => p !== null)
    .map((p, i) => `${i === 0 ? "M" : "L"}${p}`)
    .join(" ");
  const lastMeasuredIndex = values.map((v, i) => (v === null ? -1 : i)).reduce((a, b) => Math.max(a, b), -1);
  const lastMeasured = values[lastMeasuredIndex] as number;

  return (
    <svg viewBox={`0 0 ${W} ${height}`} width="100%" height={height} role="img" aria-label={ariaLabel}>
      {runs.map((d, i) => (
        <path key={i} className="iso-spark-line" d={d} pathLength={1} fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      ))}
      {dashed && <path d={dashed} fill="none" stroke={color} strokeWidth="1.8" strokeDasharray="3 3" />}
      {!still && (
        <>
          <circle className="iso-spark-end" cx={x(lastMeasuredIndex)} cy={y(lastMeasured)} r="2.6" fill={color} />
          <circle r="2.4" fill={color}>
            <animateMotion dur="5s" begin="1.8s" repeatCount="indefinite" path={travel} />
          </circle>
        </>
      )}
    </svg>
  );
}
