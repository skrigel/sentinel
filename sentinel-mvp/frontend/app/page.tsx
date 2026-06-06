"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCard } from "../components/AlertCard";
import { DiagnosisPanel } from "../components/DiagnosisPanel";
import { MetricsGraph } from "../components/MetricsGraph";
import { RecoveryConfirmation } from "../components/RecoveryConfirmation";
import {
  API_BASE,
  fetchIncident,
  fetchMetrics,
  forceDetection,
  type Incident,
  type IncidentState,
  type Metric,
} from "../lib/api";

const STATE_ORDER: IncidentState[] = [
  "IDLE",
  "DETECTED",
  "DIAGNOSED",
  "AWAITING_APPROVAL",
  "APPLYING",
  "RESOLVED",
  "FAILED",
];

// Next.js App Router requires a default export for the page.
export default function Page() {
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [incident, setIncident] = useState<Incident | null>(null);
  const [state, setState] = useState<IncidentState>("IDLE");
  const esRef = useRef<EventSource | null>(null);

  // Poll metrics every 2s for the live graph.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const data = await fetchMetrics();
        if (alive) setMetrics(data);
      } catch {
        /* transient; next tick retries */
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // SSE for incident state, with auto-reconnect + initial sync fallback.
  useEffect(() => {
    let closed = false;
    let backoff = 1000;

    const connect = () => {
      const es = new EventSource(`${API_BASE}/api/events`);
      esRef.current = es;

      es.onmessage = (e) => {
        try {
          const { new_state, incident: inc } = JSON.parse(e.data);
          if (new_state) setState(new_state as IncidentState);
          if (inc) setIncident(inc as Incident);
          backoff = 1000;
        } catch {
          /* ignore malformed frame */
        }
      };

      es.onerror = () => {
        es.close();
        if (closed) return;
        // On drop: resync via REST, then reconnect with backoff.
        fetchIncident()
          .then(({ state: s, incident: inc }) => {
            setState(s);
            setIncident(inc);
          })
          .catch(() => {});
        setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 30000);
      };
    };

    connect();
    return () => {
      closed = true;
      esRef.current?.close();
    };
  }, []);

  const atOrAfter = (s: IncidentState) =>
    STATE_ORDER.indexOf(state) >= STATE_ORDER.indexOf(s) && state !== "IDLE";

  return (
    <main className="mx-auto max-w-3xl space-y-4 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100">
            Sentinel — Self-Healing Agent Monitor
          </h1>
          <p className="text-sm text-slate-400">
            observe → reason → act → verify · state:{" "}
            <span className="font-mono text-sky-300">{state}</span>
          </p>
        </div>
        {state === "IDLE" && (
          <button
            onClick={() => forceDetection().catch(() => {})}
            className="rounded-md border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            Force Detection
          </button>
        )}
      </header>

      <MetricsGraph metrics={metrics} anomalyTs={incident?.anomaly?.start_ts} />

      {incident && atOrAfter("DETECTED") && <AlertCard incident={incident} />}

      {incident && atOrAfter("DETECTED") && state !== "RESOLVED" && (
        <DiagnosisPanel incident={incident} state={state} />
      )}

      {incident && <RecoveryConfirmation incident={incident} state={state} />}
    </main>
  );
}
