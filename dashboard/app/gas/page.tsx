import { getGasLeaderboard } from "@/lib/api";
import { ProjectTable } from "@/components/ProjectTable";

export const dynamic = "force-dynamic";

export default async function GasLeaderboardPage() {
  const projects = await getGasLeaderboard(25);

  return (
    <main className="container" style={{ paddingTop: 40, paddingBottom: 64 }}>
      <h1 style={{ fontSize: "1.6rem", marginBottom: 12 }}>Gas leaderboard</h1>
      <p style={{ color: "var(--color-ink-dim)", maxWidth: 560, marginBottom: 32 }}>
        Top projects by USDC gas paid over the trailing 7 days. USDC is
        Arc&apos;s native gas asset — this is Arc-native activity, not a
        proxy for it.
      </p>
      <ProjectTable projects={projects} />
    </main>
  );
}
