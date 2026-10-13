// og.tsx - the share-card artwork (Open Graph / Twitter), rendered by next/og at request time.
// Satori (the renderer) supports a CSS subset: every element with more than one child needs
// display:flex, and fonts are the bundled default, so weights carry the brand instead of Archivo.

import { ImageResponse } from "next/og";

export const OG_SIZE = { width: 1200, height: 630 };
export const OG_TYPE = "image/png";

const BG = "#0c0c0e";
const PANEL = "#17171a";
const INK = "#f2f0ea";
const DIM = "#8f8d86";
const CORAL = "#ff5b2e";
const VERDIGRIS = "#5fc9c0";

/** The Ascending Shard mark: a tall coral spike breaking through a shorter cream one. */
function Mark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64">
      <rect width="64" height="64" rx="14" fill={PANEL} />
      <path d="M14 52 L28 26 L42 52 Z" fill={INK} />
      <path d="M26 52 L40 12 L54 52 Z" fill={CORAL} />
    </svg>
  );
}

function Frame({ children, eyebrow }: { children: React.ReactNode; eyebrow: string }) {
  return (
    <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", background: BG, color: INK, padding: "64px 72px", position: "relative" }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: 1200, height: 8, background: CORAL, display: "flex" }} />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <Mark size={56} />
          <div style={{ fontSize: 36, fontWeight: 800, letterSpacing: -1, display: "flex" }}>Isogram</div>
        </div>
        <div style={{ fontSize: 22, color: DIM, letterSpacing: 3, textTransform: "uppercase", display: "flex" }}>{eyebrow}</div>
      </div>
      {children}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 24, color: DIM }}>
        <div style={{ display: "flex" }}>isogram.vercel.app</div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 12, height: 12, borderRadius: 12, background: VERDIGRIS, display: "flex" }} />
          <div style={{ display: "flex" }}>Live on Arc mainnet</div>
        </div>
      </div>
    </div>
  );
}

export function renderSiteCard(): ImageResponse {
  return new ImageResponse(
    (
      <Frame eyebrow="Arc mainnet analytics">
        <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
          <div style={{ fontSize: 96, fontWeight: 900, letterSpacing: -4, lineHeight: 1, display: "flex" }}>The data truth layer for Arc.</div>
          <div style={{ fontSize: 32, color: DIM, lineHeight: 1.35, display: "flex", maxWidth: 900 }}>
            Network activity, projects, tokens, DEX volume and DeFi scores, with every number sourced and every gap shown.
          </div>
        </div>
      </Frame>
    ),
    { ...OG_SIZE },
  );
}

export interface ProjectCardData {
  name: string;
  category: string | null;
  stats: { label: string; value: string }[];
}

export function renderProjectCard(d: ProjectCardData): ImageResponse {
  const name = d.name.length > 38 ? d.name.slice(0, 37) + "…" : d.name;
  return new ImageResponse(
    (
      <Frame eyebrow={d.category ?? "Project"}>
        <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
          <div style={{ fontSize: name.length > 20 ? 84 : 112, fontWeight: 900, letterSpacing: -4, lineHeight: 1, display: "flex" }}>{name}</div>
          <div style={{ display: "flex", gap: 56 }}>
            {d.stats.map((s) => (
              <div key={s.label} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ fontSize: 56, fontWeight: 800, color: CORAL, display: "flex" }}>{s.value}</div>
                <div style={{ fontSize: 22, color: DIM, textTransform: "uppercase", letterSpacing: 2, display: "flex" }}>{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </Frame>
    ),
    { ...OG_SIZE },
  );
}
