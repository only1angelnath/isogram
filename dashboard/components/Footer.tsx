import Link from "next/link";

export function Footer() {
  return (
    <footer className="container site-footer">
      <span>Isogram · built on Arc</span>
      <nav aria-label="Footer">
        <Link href="/docs">Docs</Link>
        <Link href="/docs/api">API</Link>
        <a href="https://github.com/only1angelnath/isogram" target="_blank" rel="noreferrer">GitHub</a>
      </nav>
    </footer>
  );
}
