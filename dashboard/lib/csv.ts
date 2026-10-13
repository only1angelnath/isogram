// csv.ts - tiny CSV writer for the download buttons.
//
// Two rules: null/undefined become an EMPTY cell (never 0 - the dashboard's honesty rule), and any
// text that a spreadsheet could read as a formula (leading = + - @ tab CR) is prefixed with a quote,
// because project names are chosen by token deployers and must not be able to run in Excel.

export type CsvCell = string | number | boolean | null | undefined;

function cell(v: CsvCell): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
  let s = String(v);
  if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(columns: string[], rows: CsvCell[][]): string {
  return [columns, ...rows].map((r) => r.map(cell).join(",")).join("\r\n") + "\r\n";
}
