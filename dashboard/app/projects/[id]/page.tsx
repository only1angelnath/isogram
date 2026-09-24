import { notFound } from "next/navigation";
import { getProject } from "@/lib/api";
import { ScoreBadge } from "@/components/ScoreBadge";
import { formatCount, formatRelativeAge, formatScore, formatUsd } from "@/lib/format";

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
    <main className="container" style={{ paddingTop: 40, paddingBottom: 64 }}>
      <div style={{ marginBottom: 8 }}>
        {project.category && <div className="stat-label">{project.category}</div>}
        <h1 style={{ fontSize: "1.8rem" }}>{project.name}</h1>
      </div>
      <p className="stat-label" style={{ marginBottom: 32 }}>
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
        <StatPanel label="arc native score" value={formatScore(project.score)} />
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
        <p className="stat-label" style={{ marginBottom: 8 }}>
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
    <div className="panel" style={{ padding: 16 }}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
