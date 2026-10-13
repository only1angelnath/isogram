import { NextResponse } from "next/server";
import { getProjectRefByAddress, listProjects } from "@/lib/api";

// Two jobs for the nav search, both read through the API like every other page (never the database):
//   GET /api/search                  -> a slim projection of /projects (id, name, category, 7-day activity,
//                                       the last used only to rank equal matches)
//   GET /api/search?address=0x...    -> which project owns that contract: {id, name}, or 404
export const dynamic = "force-dynamic";

const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/;
const CACHE = { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600" };

export async function GET(request: Request) {
  const address = new URL(request.url).searchParams.get("address");
  try {
    if (address !== null) {
      if (!ADDRESS_RE.test(address)) return NextResponse.json({ error: "invalid_address" }, { status: 400 });
      const ref = await getProjectRefByAddress(address);
      return ref
        ? NextResponse.json(ref, { headers: CACHE })
        : NextResponse.json({ error: "not_found" }, { status: 404, headers: CACHE });
    }
    const projects = await listProjects();
    const items = projects.map((p) => ({ id: p.id, name: p.name, category: p.category, tx: p.tx_count_7d ?? 0 }));
    return NextResponse.json(items, { headers: CACHE });
  } catch {
    return NextResponse.json({ error: "unavailable" }, { status: 503 });
  }
}
