import { NextResponse } from "next/server";
import { listProjects } from "@/lib/api";

// A slim projection of /projects for the nav search: id, name, category, 7-day activity (used only
// to rank equal matches). Read through the API like every other page; never touches the database.
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const projects = await listProjects();
    const items = projects.map((p) => ({ id: p.id, name: p.name, category: p.category, tx: p.tx_count_7d ?? 0 }));
    return NextResponse.json(items, { headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600" } });
  } catch {
    return NextResponse.json({ error: "unavailable" }, { status: 503 });
  }
}
