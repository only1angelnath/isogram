import Link from "next/link";

export default function NotFound() {
  return (
    <main className="container empty-state">
      <h1 style={{ fontSize: "1.4rem", marginBottom: 8 }}>Not tracked</h1>
      <p style={{ marginBottom: 16 }}>Isogram has no project at this address. Try the search, or browse everything tracked.</p>
      <Link href="/projects" className="btn">Browse projects</Link>
    </main>
  );
}
