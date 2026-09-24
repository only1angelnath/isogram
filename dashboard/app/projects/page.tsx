import { listProjects } from "@/lib/api";
import { ProjectTable } from "@/components/ProjectTable";

export const dynamic = "force-dynamic";

export default async function ProjectsPage() {
  const projects = await listProjects();

  return (
    <main className="container section">
      <div className="eyebrow">ALL PROJECTS</div>
      <h2 style={{ fontSize: 32, marginBottom: 12 }}>Every tracked project.</h2>
      <p className="lede">
        Score, TVL, USDC gas paid, and unique users — three views of the same
        underlying dataset, read directly from Arc mainnet.
      </p>
      <ProjectTable projects={projects} />
    </main>
  );
}
