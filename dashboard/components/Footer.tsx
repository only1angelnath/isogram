import Link from "next/link";
import { getApiBaseUrlForBadge } from "@/lib/api";

function apiDocs(): string | null {
  try {
    return `${getApiBaseUrlForBadge()}/docs`;
  } catch {
    return null;
  }
}

export function Footer() {
  const docs = apiDocs();
  return (
    <footer className="container site-footer">
      <span>Isogram · built on Arc</span>
      <nav aria-label="Footer">
        <Link href="/methodology">Methodology</Link>
        {docs && <a href={docs} target="_blank" rel="noreferrer">API docs</a>}
        <a href="https://github.com/only1angelnath/isogram" target="_blank" rel="noreferrer">GitHub</a>
      </nav>
    </footer>
  );
}
