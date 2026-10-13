// GET /api/projects-csv - every tracked project as a CSV download.
//
// Served by the dashboard's own server (not the browser) so the /projects page does not have to
// carry ~900 rows of data in its HTML just to power one button.

import { listProjects } from "@/lib/api";
import { toCsv } from "@/lib/csv";
import { PROJECT_CSV_COLUMNS, PROJECT_CSV_FILENAME, projectCsvRow } from "@/lib/projectsCsv";

export const dynamic = "force-dynamic";

export async function GET() {
  let projects;
  try {
    projects = await listProjects();
  } catch {
    return new Response("The data API is not reachable right now. Try again in a minute.", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
    });
  }
  // BOM so Excel reads the file as UTF-8.
  const body = "﻿" + toCsv(PROJECT_CSV_COLUMNS, projects.map(projectCsvRow));
  return new Response(body, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${PROJECT_CSV_FILENAME}"`,
      "Cache-Control": "public, max-age=0, s-maxage=300",
    },
  });
}
