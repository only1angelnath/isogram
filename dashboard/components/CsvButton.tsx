"use client";

// CsvButton.tsx - downloads the rows it is given as a CSV file, built in the browser (no extra
// API call). Rows are passed in by the server page, so the file always matches what the page shows.

import { CsvCell, toCsv } from "@/lib/csv";

export function CsvButton({ filename, columns, rows, label = "CSV" }: {
  filename: string;
  columns: string[];
  rows: CsvCell[][];
  label?: string;
}) {
  function download() {
    // BOM so Excel reads the file as UTF-8.
    const blob = new Blob(["﻿" + toCsv(columns, rows)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <button type="button" className="iso-csv" onClick={download} title={`Download ${filename}`} disabled={rows.length === 0}>
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M8 2v8M4.5 7 8 10.5 11.5 7M2.5 13.5h11" />
      </svg>
      {label}
    </button>
  );
}
