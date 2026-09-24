import Link from "next/link";
import { notFound } from "next/navigation";
import { getProject } from "@/lib/api";
import { ScoreBadge } from "@/components/ScoreBadge";
import { ScoreGauge } from "@/components/ScoreGauge";
import { formatCount, formatRelativeAge, formatUsd } from "@/lib/format";

interface ProjectPageProps {
  params: Promise<{ id: string }>;
}

export const dynamic = "force-dynamic";

export default async function ProjectDetailPage({ params }: ProjectPageProps) {
  const { id } = await params;
  const project = await getProject(id);

  if (!project) {
    notFound();
  }

  return (
    <main className="container section">
      <p className="mono" style={{ fontSize: 12, color: "var(--ink-dim)", marginBottom: 24 }}>
        <Link href="/projects">← all projects</Link>
      </p>

      <div style={{ display: "flex", alignItems: "center", gap: 24, marginBottom: 12, flexWrap: "wrap" }}>
        <ScoreGauge score={project.score} />
        <div>
          {project.category && <div className="eyebrow" style={{ marginBottom: 4 }}>{project.category}</div>}
          <h1 style={{ fontSize: 32 }}>{project.name}</h1>
        </div>
      </div>

      <p className="mono" style={{ fontSize: 12, color: "var(--ink-dim)", marginBottom: 32 }}>
        deployed {formatRelativeAge(project.created_at)} · last scored{" "}
        {formatRelativeAge(project.computed_at)}
      </p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: 16,
          marginBottom: 32,
        }}
      >
        <StatPanel label="tvl" value={formatUsd(project.tvl_usd)} />
        <StatPanel label="usdc gas (7d)" value={formatUsd(project.usdc_gas_7d, { decimals: 4 })} />
        <StatPanel label="unique users (7d)" value={formatCount(project.unique_users_7d)} />
      </div>

      {project.score === null && (
        <p className="no-data" style={{ marginBottom: 32 }}>
          This project hasn&apos;t been scored yet — either it was just
          added, or Arc mainnet is still too young for a meaningful reading.
          Check back after the next scoring run.
        </p>
      )}

      <div className="panel" style={{ padding: 24, marginBottom: 32 }}>
        <ScoreBadge projectId={project.id} projectName={project.name} />
      </div>

      <div>
        <p className="mono" style={{ fontSize: 12, color: "var(--ink-dim)", marginBottom: 8 }}>
          tracked contracts
        </p>
        <ul style={{ margin: 0, paddingLeft: 20 }}>
          {project.contracts.map((address) => (
            <li key={address} className="mono" style={{ fontSize: "0.85rem", marginBottom: 4 }}>
              {address}
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}

function StatPanel({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-panel">
      <div className="value mono">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}
