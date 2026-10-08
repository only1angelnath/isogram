"use client";

// InteractiveChart.tsx — hover-able, animated bar/line chart with real axes.
// Client component (needs hover state), so formatting is selected by a string key — functions
// cannot be passed from server components. Rules shared with the rest of the dashboard:
// null = no data (drawn as an empty dotted slot, never a zero bar); partial points are faded
// (bars) or dashed (line) so an incomplete day never reads as a real drop.

import { useEffect, useState } from "react";
import { formatCompact, formatCount, formatDay, formatPercent, formatUsd, formatUsdCompact } from "@/lib/format";

export type ChartFormat = "count" | "compact" | "usd" | "usd4" | "usdCompact" | "percent" | "score";

export interface ChartPoint {
  /** YYYY-MM-DD (UTC) for daily series, or any ISO timestamp. */
  label: string;
  value: number | null;
  partial?: boolean;
  /** Extra tooltip lines, e.g. "408 of 21,008 txs failed". */
  detail?: string[];
}

interface Props {
  kind: "bar" | "line";
  points: ChartPoint[];
  format: ChartFormat;
  color?: string;
  height?: number;
  yTitle?: string;
  ariaLabel: string;
}

function fmt(kind: ChartFormat, v: number | null): string {
  switch (kind) {
    case "count": return formatCount(v);
    case "compact": return formatCompact(v);
    case "usd": return formatUsd(v);
    case "usd4": return formatUsd(v, { decimals: 4 });
    case "usdCompact": return formatUsdCompact(v);
    case "percent": return formatPercent(v);
    case "score": return v === null ? "—" : v.toFixed(2);
  }
}

// Short labels on the y axis: compact for big numbers so the axis stays narrow.
function axisFmt(kind: ChartFormat, v: number): string {
  switch (kind) {
    case "count": return formatCompact(v);
    case "usd":
    case "usd4": return formatUsdCompact(v);
    default: return fmt(kind, v);
  }
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const exp = Math.floor(Math.log10(v));
  const f = v / 10 ** exp;
  const nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nf * 10 ** exp;
}

function dayLabel(label: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(label) ? formatDay(label) : label;
}

export function InteractiveChart({ kind, points, format, color = "var(--accent)", height = 180, yTitle, ariaLabel }: Props) {
  const [active, setActive] = useState<number | null>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const measured = points.map((p) => p.value).filter((v): v is number => v !== null);
  if (measured.length === 0) {
    return (
      <div className="iso-dim" style={{ height, fontSize: 12, display: "flex", alignItems: "center" }}>
        collecting data…
      </div>
    );
  }

  const n = points.length;
  const max = niceMax(Math.max(...measured));
  const pct = (v: number) => Math.max(0, Math.min(100, (v / max) * 100));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const step = n <= 7 ? 1 : Math.ceil(n / 6);
  const xLabels = points.map((p, i) => (i % step === 0 || i === n - 1 ? dayLabel(p.label) : ""));
  const cx = (i: number) => ((i + 0.5) / n) * 100;

  // --- line geometry: one path per contiguous run of measured values ---
  const runs: { d: string; dashed: boolean }[] = [];
  let run = "";
  points.forEach((p, i) => {
    if (p.value === null) {
      if (run) runs.push({ d: run, dashed: false });
      run = "";
      return;
    }
    run += `${run ? " L" : "M"}${cx(i).toFixed(2)} ${(100 - pct(p.value)).toFixed(2)}`;
  });
  if (run) runs.push({ d: run, dashed: false });
  const lastPoint = points[n - 1];
  const prevPoint = points[n - 2];
  let dashedTail: string | null = null;
  if (kind === "line" && lastPoint?.partial && lastPoint.value !== null && prevPoint && prevPoint.value !== null) {
    dashedTail = `M${cx(n - 2).toFixed(2)} ${(100 - pct(prevPoint.value)).toFixed(2)} L${cx(n - 1).toFixed(2)} ${(100 - pct(lastPoint.value)).toFixed(2)}`;
  }
  const areaPoints = points
    .map((p, i) => (p.value === null ? null : `${cx(i).toFixed(2)},${(100 - pct(p.value)).toFixed(2)}`))
    .filter((x): x is string => x !== null);

  const a = active !== null ? points[active] : null;
  const tipLeft = active === null ? 0 : cx(active);
  const tipStyle: React.CSSProperties =
    tipLeft < 22 ? { left: `${tipLeft}%` } : tipLeft > 78 ? { left: `${tipLeft}%`, transform: "translateX(-100%)" } : { left: `${tipLeft}%`, transform: "translateX(-50%)" };

  return (
    <div role="img" aria-label={ariaLabel}>
      {yTitle && <div className="iso-ytitle">{yTitle}</div>}
      <div className="iso-chart">
        <div className="iso-yaxis" style={{ height }}>
          {ticks.map((t) => (
            <span key={t} style={{ bottom: `${(t / max) * 100}%` }}>{axisFmt(format, t)}</span>
          ))}
        </div>

        <div className="iso-plot" style={{ height }} onMouseLeave={() => setActive(null)}>
          {ticks.slice(1).map((t) => (
            <div key={t} className="iso-grid" style={{ bottom: `${(t / max) * 100}%` }} />
          ))}

          {kind === "line" && (
            <>
              <svg className="iso-linesvg" viewBox="0 0 100 100" preserveAspectRatio="none">
                <defs>
                  <linearGradient id={`iso-area-${ariaLabel.length}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={color} stopOpacity="0.28" />
                    <stop offset="100%" stopColor={color} stopOpacity="0" />
                  </linearGradient>
                </defs>
                {areaPoints.length > 1 && runs.length === 1 && (
                  <polygon
                    points={`${areaPoints[0].split(",")[0]},100 ${areaPoints.join(" ")} ${areaPoints[areaPoints.length - 1].split(",")[0]},100`}
                    fill={`url(#iso-area-${ariaLabel.length})`}
                    opacity={mounted ? 1 : 0}
                    style={{ transition: "opacity 1.2s ease .3s" }}
                  />
                )}
                {runs.map((r, i) => (
                  <path
                    key={i}
                    d={r.d}
                    pathLength={1}
                    fill="none"
                    stroke={color}
                    strokeWidth="2"
                    vectorEffect="non-scaling-stroke"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    style={{ strokeDasharray: 1, strokeDashoffset: mounted ? 0 : 1, transition: "stroke-dashoffset 1.4s cubic-bezier(.3,.7,.2,1)" }}
                  />
                ))}
                {dashedTail && (
                  <path d={dashedTail} fill="none" stroke={color} strokeWidth="2" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
                )}
              </svg>
              {active !== null && <div className="iso-cross" style={{ left: `${cx(active)}%` }} />}
              {points.map((p, i) =>
                p.value === null ? null : (
                  <div
                    key={p.label}
                    className="iso-dot"
                    style={{
                      left: `${cx(i)}%`,
                      top: `${100 - pct(p.value)}%`,
                      background: color,
                      opacity: mounted ? (p.partial ? 0.5 : 1) : 0,
                      transform: active === i ? "scale(1.9)" : "scale(1)",
                      transition: "opacity .6s ease 1s, transform .12s",
                    }}
                  />
                ),
              )}
            </>
          )}

          <div className="iso-cols">
            {points.map((p, i) => (
              <div key={p.label} className="iso-col" data-active={active === i} onMouseEnter={() => setActive(i)} onFocus={() => setActive(i)} tabIndex={0}>
                {kind === "bar" &&
                  (p.value === null ? (
                    <div className="iso-nodata" />
                  ) : (
                    <div
                      className="iso-bar"
                      style={{
                        height: `${mounted ? pct(p.value) : 0}%`,
                        minHeight: p.value > 0 ? 2 : 0,
                        background: p.partial ? `repeating-linear-gradient(135deg, ${color}, ${color} 4px, transparent 4px, transparent 7px)` : color,
                        opacity: p.partial ? 0.7 : 1,
                        transitionDelay: `${i * 35}ms`,
                      }}
                    />
                  ))}
              </div>
            ))}
          </div>

          {a && (
            <div className="iso-tip" style={tipStyle}>
              <b>{dayLabel(a.label)}{a.partial ? " · PARTIAL" : ""}</b>
              {a.value === null ? (
                <span className="iso-dim">no data</span>
              ) : (
                <span className="v">{fmt(format, a.value)}</span>
              )}
              {(a.detail ?? []).map((line) => (
                <small key={line}>{line}</small>
              ))}
            </div>
          )}
        </div>

        <div className="iso-xaxis">
          {xLabels.map((l, i) => (
            <span key={i}>{l}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
