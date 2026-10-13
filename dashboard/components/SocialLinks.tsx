import { SocialLink } from "@/lib/types";

const NAMES: Record<string, string> = { website: "Website", x: "X", telegram: "Telegram", discord: "Discord", github: "GitHub" };

function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

// Small line icons (16px). X is the platform's own glyph; the rest are generic stand-ins, not brand logos.
function Icon({ kind }: { kind: string }) {
  const line = { fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  switch (kind) {
    case "x":
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
        </svg>
      );
    case "telegram":
      return (
        <svg width="15" height="15" viewBox="0 0 16 16" {...line} aria-hidden="true">
          <path d="M14 2 1.8 6.8l3.6 1.5L6 12.8l2.2-2.4 3.2 2.4z" /><path d="m5.4 8.3 8.6-6.3" />
        </svg>
      );
    case "discord":
      return (
        <svg width="15" height="15" viewBox="0 0 16 16" {...line} aria-hidden="true">
          <path d="M2.5 3.5h11v7h-5l-3 2.5v-2.5h-3z" />
        </svg>
      );
    case "github":
      return (
        <svg width="15" height="15" viewBox="0 0 16 16" {...line} aria-hidden="true">
          <circle cx="4.5" cy="3.5" r="1.5" /><circle cx="4.5" cy="12.5" r="1.5" /><circle cx="11.5" cy="6" r="1.5" />
          <path d="M4.5 5v6M11.5 7.5c0 2.5-3 2-7 3" />
        </svg>
      );
    default: // website: a globe
      return (
        <svg width="15" height="15" viewBox="0 0 16 16" {...line} aria-hidden="true">
          <circle cx="8" cy="8" r="6" /><path d="M2 8h12M8 2c2 1.7 3 3.7 3 6s-1 4.3-3 6c-2-1.7-3-3.7-3-6s1-4.3 3-6z" />
        </svg>
      );
  }
}

/**
 * Social links as icons. The API has already validated every URL (https only, platform handles rebuilt
 * on the platform's own host), but links that a token's deployer registered are still UNVERIFIED, so the
 * tooltip says so and they open with noopener / nofollow / ugc. Hand-set links on curated projects are tinted.
 */
export function SocialLinks({ links }: { links?: SocialLink[] | null }) {
  if (!links || links.length === 0) return <span className="iso-dim">—</span>;
  return (
    <span className="iso-links">
      {links.map((l) => {
        const name = NAMES[l.kind] ?? l.kind;
        return (
          <a
            key={l.kind}
            href={l.url}
            target="_blank"
            rel="noopener noreferrer nofollow ugc"
            className={`iso-link${l.curated ? " curated" : ""}`}
            aria-label={`${name}: ${hostOf(l.url)}${l.curated ? "" : " (self-reported, not verified)"}`}
            title={`${name}: ${hostOf(l.url)} - ${l.curated ? "set by Isogram" : "self-reported by the token's deployer, not verified"}`}
          >
            <Icon kind={l.kind} />
          </a>
        );
      })}
    </span>
  );
}
