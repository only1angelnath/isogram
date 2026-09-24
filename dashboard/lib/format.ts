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
