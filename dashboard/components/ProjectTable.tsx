import Link from "next/link";
import { ProjectSummary } from "@/lib/types";
import { formatCount, formatScore, formatUsd } from "@/lib/format";

interface ProjectTableProps {
  projects: ProjectSummary[];
  /** Skip the header row — used when embedding inside a section that already has one. */
  showHeader?: boolean;
}

// A handful of fixed category colors so the same category always reads the
// same dot color across the whole app — not meaningful data encoding, just
// a visual anchor like the mockup's colored preview-table dots.
const CATEGORY_COLORS: Record<string, string> = {
  dex: "var(--accent)",
  stablecoin: "var(--data-2)",
  infra: "#8f8d86",
  institutional: "#c9a15f",
};
const DEFAULT_DOT_COLOR = "#8f8d86";

export function ProjectTable({ projects, showHeader = true }: ProjectTableProps) {
  if (projects.length === 0) {
    return (
      <div className="preview-table">
        <div className="empty-state">
          No tracked projects yet. Arc mainnet is only days old — check back
          as more activity is discovered.
        </div>
      </div>
    );
  }

  return (
    <div className="preview-table">
      {showHeader && (
        <div className="pt-row pt-head">
          <span>project</span>
          <span>score</span>
          <span>tvl</span>
          <span>gas (7d)</span>
          <span>users (7d)</span>
        </div>
      )}
      {projects.map((project) => (
        <Link key={project.id} href={`/projects/${project.id}`} className="pt-row pt-link">
          <span className="pt-name">
            <span
              className="pt-dot"
              style={{ background: CATEGORY_COLORS[project.category ?? ""] ?? DEFAULT_DOT_COLOR }}
              aria-hidden="true"
            />
            <span>
              {project.name}
              {project.category && <span className="pt-category">{project.category}</span>}
            </span>
          </span>
          <span className="pt-score">{formatScore(project.score)}</span>
          <span>{formatUsd(project.tvl_usd)}</span>
          <span>{formatUsd(project.usdc_gas_7d, { decimals: 4 })}</span>
          <span>{formatCount(project.unique_users_7d)}</span>
        </Link>
      ))}
    </div>
  );
}
