"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const PAGES = [
  { href: "/docs", label: "Overview" },
  { href: "/docs/methodology", label: "Methodology" },
  { href: "/docs/api", label: "API reference" },
  { href: "/docs/badges", label: "Badges" },
];

export function DocsNav() {
  const pathname = usePathname() ?? "/docs";
  return (
    <nav className="docs-nav" aria-label="Documentation">
      <span className="docs-nav-title">Docs</span>
      {PAGES.map((p) => (
        <Link key={p.href} href={p.href} aria-current={pathname === p.href ? "page" : undefined}>{p.label}</Link>
      ))}
    </nav>
  );
}
