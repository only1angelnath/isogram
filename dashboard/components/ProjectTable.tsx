import Link from "next/link";
import { ProjectSummary } from "@/lib/types";
import { formatCount, formatScore, formatUsd } from "@/lib/format";

interface ProjectTableProps {
  projects: ProjectSummary[];
}

export function ProjectTable({ projects }: ProjectTableProps) {
  if (projects.length === 0) {
    return (
      <div className="empty-state">
        No tracked projects yet. Arc mainnet is only days old — check back
        as more activity is discovered.
      </div>
    );
  }

  return (
    <table>
      <thead>
        <tr>
          <th>project</th>
          <th className="mono">score</th>
          <th className="mono">tvl</th>
          <th className="mono">gas (7d)</th>
          <th className="mono">users (7d)</th>
        </tr>
      </thead>
      <tbody>
        {projects.map((project) => (
          <tr key={project.id}>
            <td>
              <Link href={`/projects/${project.id}`}>{project.name}</Link>
              {project.category && <div className="stat-label">{project.category}</div>}
            </td>
            <td className="mono">{formatScore(project.score)}</td>
            <td className="mono">{formatUsd(project.tvl_usd)}</td>
            <td className="mono">{formatUsd(project.usdc_gas_7d, { decimals: 4 })}</td>
            <td className="mono">{formatCount(project.unique_users_7d)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
