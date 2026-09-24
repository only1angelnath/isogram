import { listProjects } from "@/lib/api";
import { ProjectTable } from "@/components/ProjectTable";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const projects = await listProjects();
  const scoredCount = projects.filter((p) => p.score !== null).length;

  return (
    <main className="container" style={{ paddingTop: 40, paddingBottom: 64 }}>
      <h1 style={{ fontSize: "2rem", marginBottom: 12 }}>The data truth layer for Arc.</h1>
      <p style={{ color: "var(--color-ink-dim)", maxWidth: 560, marginBottom: 32 }}>
        USDC gas paid, TVL, and the Arc Native Score — three views of the
        same dataset, read directly from Arc mainnet via RPC. No third-party
        indexer in the pipeline.
      </p>

      {/* Honest stat strip, per docs/BRANDING.md §5 — real facts only, never
          a fabricated usage number before real data exists. */}
      <div
        style={{
          display: "flex",
          gap: 32,
          marginBottom: 40,
          paddingBottom: 32,
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        <Stat label="tracked projects" value={String(projects.length)} />
        <Stat label="scored so far" value={String(scoredCount)} />
        <Stat label="data source" value="direct RPC" />
      </div>

      <ProjectTable projects={projects} />
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
