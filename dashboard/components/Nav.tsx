import Link from "next/link";

export function Nav() {
  return (
    <div className="nav">
      <div className="container nav-inner">
        <Link href="/" className="wordmark">
          <span className="shard-mark" aria-hidden="true">
            <ShardIcon />
          </span>
          Isogram
        </Link>
        <nav className="nav-links">
          <Link href="/projects">Projects</Link>
          <Link href="/gas">Gas leaderboard</Link>
        </nav>
        <Link href="/projects" className="btn">
          Explore live data
        </Link>
      </div>
    </div>
  );
}

// Full "ascending shard" mark, per docs/BRANDING.md §2.1 — two overlapping
// triangular shards (taller coral spike breaking through a shorter cream
// one), bases flush against a rounded-square container. Inline SVG so it
// stays crisp at nav size without a separate asset file.
function ShardIcon() {
  return (
    <svg viewBox="0 0 28 28" width="28" height="28">
      <rect width="28" height="28" rx="7" fill="#101012" />
      <path d="M6 22 L12 6 L16 15 L10 22 Z" fill="#f2f0ea" />
      <path d="M13 22 L20 4 L24 22 Z" fill="#ff5b2e" />
    </svg>
  );
}
