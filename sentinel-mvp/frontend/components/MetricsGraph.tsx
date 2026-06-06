"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Metric } from "../lib/api";

interface Props {
  metrics: Metric[];
  anomalyTs?: number;
}

export function MetricsGraph({ metrics, anomalyTs }: Props) {
  const t0 = metrics.length > 0 ? metrics[0].timestamp : 0;
  const data = metrics.map((m) => ({
    t: Math.round(m.timestamp - t0),
    mb: +(m.rss / 1024 / 1024).toFixed(1),
  }));
  const current = data.length > 0 ? data[data.length - 1].mb : 0;
  const anomalyT = anomalyTs ? Math.round(anomalyTs - t0) : undefined;

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-slate-300">
          RSS Memory Usage (MB)
        </h2>
        <span className="text-sm text-slate-400">
          Current: <span className="font-mono text-slate-100">{current} MB</span>
        </span>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="t"
            stroke="#64748b"
            tick={{ fontSize: 12 }}
            unit="s"
          />
          <YAxis stroke="#64748b" tick={{ fontSize: 12 }} domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{
              background: "#0f172a",
              border: "1px solid #334155",
              borderRadius: 8,
            }}
          />
          {anomalyT !== undefined && (
            <ReferenceLine
              x={anomalyT}
              stroke="#ef4444"
              strokeDasharray="4 4"
              label={{ value: "anomaly", fill: "#ef4444", fontSize: 11 }}
            />
          )}
          <Line
            type="monotone"
            dataKey="mb"
            stroke="#38bdf8"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
