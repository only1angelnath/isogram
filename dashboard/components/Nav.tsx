"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { SearchBox } from "@/components/SearchBox";

const LINKS = [
  { href: "/network", label: "Network" },
  { href: "/projects", label: "Projects" },
  { href: "/dexes", label: "DEXes" },
  { href: "/gas", label: "Gas" },
];

export function Nav() {
  const pathname = usePathname() ?? "/";
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [pathname]);

  const current = (href: string) => (pathname === href || pathname.startsWith(`${href}/`) ? "page" : undefined);

  return (
    <header className="nav">
      <div className="container nav-inner">
        <Link href="/" className="wordmark">
          <ShardIcon />
          Isogram
        </Link>
        <nav className="nav-links" aria-label="Main">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} aria-current={current(l.href)}>{l.label}</Link>
          ))}
        </nav>
        <div className="nav-search"><SearchBox /></div>
        <button
          type="button"
          className="nav-toggle"
          aria-expanded={open}
          aria-controls="nav-drawer"
          aria-label={open ? "Close menu" : "Open menu"}
          onClick={() => setOpen((v) => !v)}
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            {open ? <path d="M4 4l12 12M16 4L4 16" /> : <path d="M3 6h14M3 10h14M3 14h14" />}
          </svg>
        </button>
      </div>
      <div id="nav-drawer" className="nav-drawer" hidden={!open}>
        <div className="nav-search"><SearchBox idSuffix="m" /></div>
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className="drawer-link" aria-current={current(l.href)}>{l.label}</Link>
        ))}
        <Link href="/methodology" className="drawer-link" aria-current={current("/methodology")}>Methodology</Link>
      </div>
    </header>
  );
}

// "Ascending shard" mark (docs/BRANDING.md §2.1), inline so it stays crisp.
function ShardIcon() {
  return (
    <svg className="shard-mark" viewBox="0 0 28 28" aria-hidden="true">
      <rect width="28" height="28" rx="7" fill="#101012" />
      <path d="M6 22 L12 6 L16 15 L10 22 Z" fill="#f2f0ea" />
      <path d="M13 22 L20 4 L24 22 Z" fill="#ff5b2e" />
    </svg>
  );
}
