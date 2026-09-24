import { getGasLeaderboard } from "@/lib/api";
import { ProjectTable } from "@/components/ProjectTable";

export const dynamic = "force-dynamic";

export default async function GasLeaderboardPage() {
  const projects = await getGasLeaderboard(25);

  return (
    <main className="container section">
      <div className="eyebrow">GAS LEADERBOARD</div>
      <h2 style={{ fontSize: 32, marginBottom: 12 }}>Top projects by USDC gas paid.</h2>
      <p className="lede">
        Trailing 7 days, highest first. USDC is Arc&apos;s native gas asset —
        this is Arc-native activity, not a proxy for it.
      </p>
      <ProjectTable projects={projects} />
    </main>
  );
}
