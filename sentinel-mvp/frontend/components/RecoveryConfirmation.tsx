"use client";

import type { Incident, IncidentState } from "../lib/api";

interface Props {
  incident: Incident;
  state: IncidentState;
}

export function RecoveryConfirmation({ incident, state }: Props) {
  const v = incident.verification;
  if (!v || (state !== "RESOLVED" && state !== "FAILED")) return null;

  const before = (v.slope_before / 1024 / 1024).toFixed(2);
  const after = (v.slope_after / 1024 / 1024).toFixed(2);
  const resolved = state === "RESOLVED";

  return (
    <div
      className={`rounded-lg border p-4 ${
        resolved
          ? "border-emerald-600/50 bg-emerald-600/10"
          : "border-red-600/50 bg-red-600/10"
      }`}
    >
      <h2 className="font-semibold">
        {resolved ? "✅ Memory leak fixed!" : "❌ Recovery not confirmed"}
      </h2>
      <div className="mt-2 grid grid-cols-3 gap-3 text-sm">
        <Stat label="Slope before" value={`${before} MB/s`} />
        <Stat label="Slope after" value={`${after} MB/s`} />
        <Stat label="Reduction" value={`${v.reduction_pct.toFixed(0)}%`} />
      </div>
      {v.duration_seconds != null && (
        <div className="mt-2 text-xs text-slate-400">
          Detect → resolve: {v.duration_seconds.toFixed(0)}s
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-slate-400">{label}</div>
      <div className="font-mono text-slate-100">{value}</div>
    </div>
  );
}
