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
          <Link href="/">Projects</Link>
          <Link href="/gas">Gas leaderboard</Link>
        </nav>
      </div>
    </div>
  );
}

// Minimal inline rendering of the "ascending shard" mark described in
// docs/BRANDING.md §2.1 — two overlapping triangles, cream + coral, bases
// flush against the container bottom. Kept as inline SVG rather than an
// image asset so it's crisp at this small nav size without shipping a
// separate file.
function ShardIcon() {
  return (
    <svg width="16" height="12" viewBox="0 0 16 12" fill="none">
      <path d="M0 12 L6 2 L9 8 L2 12 Z" fill="#f2f0ea" />
      <path d="M6 12 L11 0 L16 12 Z" fill="#ff5b2e" />
    </svg>
  );
}
