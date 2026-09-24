// Ported from mockups/landing-page.html's radial gauge (.radial-wrap /
// .radial-fg / .radial-sweep). Driven by a REAL score on the same 0-1 scale
// as api/routes/badge.py's SVG badge — no 0-100 rescaling, so this number
// always matches what a README badge embed shows for the same project.
import { formatScore } from "@/lib/format";

interface ScoreGaugeProps {
  score: number | null;
  size?: number;
}

const RADIUS = 36;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS; // ~226.19, matches the mockup's 226.2

export function ScoreGauge({ score, size = 88 }: ScoreGaugeProps) {
  const clamped = score === null ? 0 : Math.max(0, Math.min(1, score));
  const offset = CIRCUMFERENCE * (1 - clamped);

  return (
    <div className="radial-wrap" style={{ width: size, height: size }}>
      <svg viewBox="0 0 88 88" width={size} height={size}>
        <circle cx="44" cy="44" r={RADIUS} fill="none" stroke="rgba(242,240,234,0.12)" strokeWidth="6" />
        {score !== null && (
          <>
            <circle
              className="radial-fg"
              cx="44"
              cy="44"
              r={RADIUS}
              fill="none"
              stroke="var(--accent)"
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={CIRCUMFERENCE}
              transform="rotate(-90 44 44)"
              style={
                {
                  "--radial-circumference": CIRCUMFERENCE,
                  "--radial-offset": offset,
                } as React.CSSProperties
              }
            />
            <circle
              className="radial-sweep"
              cx="44"
              cy="44"
              r={RADIUS}
              fill="none"
              stroke="var(--accent)"
              strokeOpacity="0.5"
              strokeWidth="2"
              strokeLinecap="round"
              strokeDasharray={`8 ${CIRCUMFERENCE - 8}`}
            />
          </>
        )}
      </svg>
      <div className="radial-num mono">{formatScore(score)}</div>
    </div>
  );
}
