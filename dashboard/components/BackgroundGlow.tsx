// Ported from mockups/landing-page.html's .bg-glow div — fixed, behind
// everything, rendered once in app/layout.tsx so it's consistent across
// every page rather than just the old marketing-only home page.
export function BackgroundGlow() {
  return (
    <div className="bg-glow" aria-hidden="true">
      <div className="noise" />
      <div className="glow" />
      <div className="aurora" />
    </div>
  );
}
