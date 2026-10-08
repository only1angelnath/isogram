// series.ts — turn API day rows into a CALENDAR-complete series.
//
// The API only returns days the pipeline covered. Plotting those rows side by side hides
// gaps (a 6-day hole would look like consecutive days), so charts get every calendar day
// between the first and last row, with value = null and a "no data" detail for days that
// were not ingested. Nothing is interpolated or zero-filled.

export interface DayPoint {
  label: string; // YYYY-MM-DD
  value: number | null;
  partial?: boolean;
  detail?: string[];
}

function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function fillCalendar<T extends { day: string }>(
  rows: T[],
  pick: (row: T) => { value: number | null; partial?: boolean; detail?: string[] },
): DayPoint[] {
  if (rows.length === 0) return [];
  const byDay = new Map(rows.map((r) => [r.day, r]));
  const sorted = [...rows].map((r) => r.day).sort();
  const out: DayPoint[] = [];
  for (let day = sorted[0]; day <= sorted[sorted.length - 1]; day = addDays(day, 1)) {
    const row = byDay.get(day);
    if (!row) {
      out.push({ label: day, value: null, detail: ["No data — this day was not ingested"] });
    } else {
      out.push({ label: day, ...pick(row) });
    }
  }
  return out;
}
