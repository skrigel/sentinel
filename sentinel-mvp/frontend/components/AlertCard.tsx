"use client";

import type { Incident } from "../lib/api";

interface Props {
  incident: Incident;
}

export function AlertCard({ incident }: Props) {
  const anomaly = incident.anomaly;
  if (!anomaly) return null;

  const detectedAt = new Date(anomaly.start_ts * 1000).toLocaleTimeString();
  const sevColor =
    anomaly.severity === "HIGH"
      ? "text-red-400 border-red-500/50 bg-red-500/10"
      : "text-amber-400 border-amber-500/50 bg-amber-500/10";

  return (
    <div className={`rounded-lg border p-4 ${sevColor}`}>
      <div className="flex items-center gap-2 font-semibold">
        🔴 ALERT: Memory Leak Detected
      </div>
      <div className="mt-1 text-sm text-slate-300">
        Detected at: {detectedAt} &nbsp;|&nbsp; Severity:{" "}
        <span className="font-mono">{anomaly.severity}</span> &nbsp;|&nbsp; Slope:{" "}
        <span className="font-mono">
          {(anomaly.slope / 1024 / 1024).toFixed(2)} MB/s
        </span>
      </div>
    </div>
  );
}
