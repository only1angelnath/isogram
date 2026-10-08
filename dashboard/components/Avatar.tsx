// Avatar.tsx — a deterministic initials tile (no remote images). Same name -> same colour.

const PALETTE = ["#FF5B2E", "#5FC9C0", "#e3b45c", "#7ea8ff", "#c98bff", "#8fd16b", "#f08fb0", "#b7b3a8"];

export function Avatar({ name }: { name: string }) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  const initials = name.replace(/[^A-Za-z0-9 ]/g, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
  return (
    <span className="iso-avatar" style={{ background: PALETTE[h % PALETTE.length] }} aria-hidden="true">
      {initials}
    </span>
  );
}
