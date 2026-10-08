// StatusPill.tsx — shows whether the data is actually live, from /metrics/status.
// "LIVE" is only shown when the pipeline's last applied block is recent; otherwise the
// page says how far behind it is. Never an unconditional "LIVE" label.

import { PipelineStatus } from "@/lib/types";
import { formatDuration } from "@/lib/format";

export function StatusPill({ status }: { status: PipelineStatus | null }) {
  if (status?.status === "live") {
    return (
      <span className="live">
        <span className="live-dot" /> ARC MAINNET · LIVE
      </span>
    );
  }
  if (status?.status === "behind") {
    return (
      <span className="mono" style={{ color: "var(--ink-dim)" }} title={`data through ${status.data_through ?? "?"}`}>
        ARC MAINNET · CATCHING UP · data {formatDuration(status.lag_seconds)} behind
      </span>
    );
  }
  return (
    <span className="mono" style={{ color: "var(--ink-dim)" }}>
      ARC MAINNET · FRESHNESS UNKNOWN
    </span>
  );
}
