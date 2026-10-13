import { OG_SIZE, renderSiteCard } from "@/lib/og";

export const alt = "Isogram, the data truth layer for Arc";
export const size = OG_SIZE;
export const contentType = "image/png";

export default function Image() {
  return renderSiteCard();
}
