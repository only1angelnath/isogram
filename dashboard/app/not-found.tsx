import Link from "next/link";

export default function NotFound() {
  return (
    <main className="container empty-state">
      <h1 style={{ fontSize: "1.4rem", marginBottom: 8 }}>Not tracked</h1>
      <p style={{ marginBottom: 16 }}>
        That project isn&apos;t in Isogram yet — it may not exist, or hasn&apos;t
        been discovered on Arc mainnet.
      </p>
      <Link href="/">Back to all projects</Link>
    </main>
  );
}
