import { getApiBaseUrlForBadge } from "@/lib/api";

interface ScoreBadgeProps {
  projectId: string;
  projectName: string;
}

// Embeds the real badge served by GET /badge/{project_id}.svg (api/routes/badge.py)
// rather than re-rendering the score client-side — this is deliberately the
// same artifact a README embed would show, so what a builder sees on the
// dashboard and what they'd paste into their own repo always match.
export function ScoreBadge({ projectId, projectName }: ScoreBadgeProps) {
  const badgeUrl = `${getApiBaseUrlForBadge()}/badge/${encodeURIComponent(projectId)}.svg`;
  const markdownSnippet = `[![${projectName} — Arc Native Score](${badgeUrl})](https://isogram.xyz/projects/${projectId})`;

  return (
    <div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={badgeUrl} alt={`${projectName} Arc Native Score badge`} height={20} />
      <p className="stat-label" style={{ marginTop: 12, marginBottom: 4 }}>
        embed in your README
      </p>
      <pre
        className="mono panel"
        style={{ padding: 12, fontSize: "0.8rem", overflowX: "auto", margin: 0 }}
      >
        {markdownSnippet}
      </pre>
    </div>
  );
}
