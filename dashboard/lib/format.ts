// format.ts — pure display formatting. No fetching, no React — just the
// same "null means no data, never fabricate a 0" rule enforced everywhere
// else in this codebase (docs/BUGS.md #3), applied at the last mile.

export function formatScore(score: number | null): string {
  return score === null ? "—" : score.toFixed(2);
}

export function formatUsd(amount: number | null, opts: { decimals?: number } = {}): string {
  if (amount === null) return "—";
  const decimals = opts.decimals ?? 2;
  const formatted = amount.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return "$" + formatted;
}

export function formatCount(count: number | null): string {
  return count === null ? "—" : count.toLocaleString();
}

export function formatRelativeAge(isoDate: string | null): string {
  if (!isoDate) return "—";
  const ms = Date.now() - new Date(isoDate).getTime();
  const days = Math.floor(ms / (1000 * 60 * 60 * 24));
  if (days <= 0) return "today";
  if (days === 1) return "1 day ago";
  return `${days} days ago`;
}

/** 0.0219 -> "2.2%". null stays "—" (never a fabricated 0%). */
export function formatPercent(ratio: number | null, decimals = 1): string {
  return ratio === null ? "—" : `${(ratio * 100).toFixed(decimals)}%`;
}

/** 96293979 -> "96.3M" (for dense tables / stat tiles). */
export function formatCompact(value: number | null): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

/** "2026-10-05" -> "Oct 5" (UTC; the day string is already a UTC calendar date). */
export function formatDay(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** 77903 -> "21h 38m". */
export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 90) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 90) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function shortAddress(address: string): string {
  return address.length > 12 ? `${address.slice(0, 6)}…${address.slice(-4)}` : address;
}

/** 96293979 -> "$96.3M". */
export function formatUsdCompact(value: number | null): string {
  if (value === null) return "—";
  return "$" + new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

/** Tone for a failed-transaction rate: green < 1%, amber < 5%, red above. null -> neutral. */
export function failedTone(rate: number | null): "good" | "warn" | "bad" | "" {
  if (rate === null) return "";
  if (rate < 0.01) return "good";
  if (rate < 0.05) return "warn";
  return "bad";
}
