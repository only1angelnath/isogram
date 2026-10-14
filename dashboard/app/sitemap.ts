import type { MetadataRoute } from "next";
import { listProjects } from "@/lib/api";

// Static pages plus one entry per tracked project. Rendered on request so it never needs the API at build time;
// if the API is unreachable the project entries are simply left out and the static pages are still served.
export const dynamic = "force-dynamic";

const SITE = "https://isogram.vercel.app";

const STATIC: { path: string; priority: number; changeFrequency: "hourly" | "daily" | "weekly" }[] = [
  { path: "", priority: 1, changeFrequency: "hourly" },
  { path: "/network", priority: 0.8, changeFrequency: "hourly" },
  { path: "/projects", priority: 0.8, changeFrequency: "hourly" },
  { path: "/dexes", priority: 0.7, changeFrequency: "hourly" },
  { path: "/gas", priority: 0.7, changeFrequency: "hourly" },
  { path: "/submit", priority: 0.5, changeFrequency: "weekly" },
  { path: "/docs", priority: 0.6, changeFrequency: "weekly" },
  { path: "/docs/methodology", priority: 0.6, changeFrequency: "weekly" },
  { path: "/docs/api", priority: 0.6, changeFrequency: "weekly" },
  { path: "/docs/badges", priority: 0.5, changeFrequency: "weekly" },
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();
  const pages: MetadataRoute.Sitemap = STATIC.map((p) => ({
    url: `${SITE}${p.path}`,
    lastModified: now,
    changeFrequency: p.changeFrequency,
    priority: p.priority,
  }));

  let projects: { id: string }[] = [];
  try {
    projects = await listProjects();
  } catch {
    /* API unreachable: ship the static pages only */
  }
  const projectPages: MetadataRoute.Sitemap = projects.map((p) => ({
    url: `${SITE}/projects/${encodeURIComponent(p.id)}`,
    lastModified: now,
    changeFrequency: "daily",
    priority: 0.4,
  }));

  return [...pages, ...projectPages];
}
