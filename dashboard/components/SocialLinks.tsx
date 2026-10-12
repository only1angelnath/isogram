import { SocialLink } from "@/lib/types";

const LABELS: Record<string, string> = { website: "web", x: "x", telegram: "tg", discord: "dc", github: "gh" };
const NAMES: Record<string, string> = { website: "Website", x: "X", telegram: "Telegram", discord: "Discord", github: "GitHub" };

function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

/**
 * Social links. The API has already validated every URL (https only, platform handles rebuilt on the
 * platform's own host), but links that a token's deployer registered are still UNVERIFIED, so they are
 * marked as such and opened with noopener / nofollow / ugc. Hand-set links on curated projects are tinted.
 */
export function SocialLinks({ links }: { links?: SocialLink[] | null }) {
  if (!links || links.length === 0) return <span className="iso-dim">—</span>;
  return (
    <span className="iso-links">
      {links.map((l) => (
        <a
          key={l.kind}
          href={l.url}
          target="_blank"
          rel="noopener noreferrer nofollow ugc"
          className={`iso-link${l.curated ? " curated" : ""}`}
          title={`${NAMES[l.kind] ?? l.kind}: ${hostOf(l.url)} - ${l.curated ? "set by Isogram" : "self-reported by the token's deployer, not verified"}`}
        >
          {LABELS[l.kind] ?? l.kind}
        </a>
      ))}
    </span>
  );
}
