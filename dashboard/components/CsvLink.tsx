// CsvLink.tsx - a download link styled like CsvButton, for files the server builds on request
// (so the page does not have to carry the rows as props). Plain <a download>: works without JS.

export function CsvLink({ href, filename, label = "CSV" }: { href: string; filename: string; label?: string }) {
  return (
    <a className="iso-csv" href={href} download={filename} title={`Download ${filename}`}>
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M8 2v8M4.5 7 8 10.5 11.5 7M2.5 13.5h11" />
      </svg>
      {label}
    </a>
  );
}
