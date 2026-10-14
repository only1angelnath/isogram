import { getApiBaseUrlForBadge } from "@/lib/api";
import { CodeBlock } from "@/components/CodeBlock";

interface ScoreBadgeProps {
  projectId: string;
  projectName: string;
}

// Embeds the real badge served by GET /badge/{project_id}.svg (api/routes/badge.py)
// rather than re-rendering the score client-side: this is deliberately the
// same artifact a README embed would show, so what a builder sees on the
// dashboard and what they'd paste into their own repo always match.
export function ScoreBadge({ projectId, projectName }: ScoreBadgeProps) {
  const badgeUrl = `${getApiBaseUrlForBadge()}/badge/${encodeURIComponent(projectId)}.svg`;
  const pageUrl = `https://isogram.vercel.app/projects/${encodeURIComponent(projectId)}`;
  const markdown = `[![${projectName} Arc Native Score](${badgeUrl})](${pageUrl})`;
  const html = `<a href="${pageUrl}"><img src="${badgeUrl}" alt="${projectName} Arc Native Score" height="20"></a>`;

  return (
    <div className="embed">
      <p className="meta" style={{ marginBottom: 10 }}>embed this badge</p>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={badgeUrl} alt={`${projectName} Arc Native Score badge`} height={20} />
      <p className="iso-dim" style={{ margin: "10px 0 12px", fontSize: 13 }}>
        Live: it updates with the score, and links back to this page. Paste it into a README or a website.
      </p>
      <CodeBlock label="Markdown (README)" code={markdown} />
      <CodeBlock label="HTML" code={html} />
    </div>
  );
}
