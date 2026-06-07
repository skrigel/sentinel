"use client";

import type { Incident, IncidentState } from "../lib/api";
import { ApplyButton } from "./ApplyButton";

interface Props {
  incident: Incident;
  state: IncidentState;
}

export function DiagnosisPanel({ incident, state }: Props) {
  const proposal = incident.proposal;
  const ev = proposal?.evidence ?? incident.enriched?.evidence;
  if (!proposal && !ev) return null;

  const perCallMb = ev ? (ev.per_call_avg / 1024 / 1024).toFixed(1) : "—";
  const accuracy = proposal?.eval ? Math.round(proposal.eval.accuracy * 100) : null;
  const evalPass = accuracy !== null && accuracy >= 50;

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-300">
        🔍 Diagnosis
      </h2>

      <div className="space-y-3 text-sm">
        <div>
          <span className="text-slate-400">Blamed Operation: </span>
          <span className="font-mono text-sky-300">
            {proposal?.blamed_op ?? incident.enriched?.blamed_op ?? "…"}
          </span>
        </div>

        {ev && (
          <div>
            <div className="text-slate-400">Evidence:</div>
            <ul className="ml-4 list-disc text-slate-200">
              <li>
                {perCallMb} MB retained per call × {ev.invocations} calls
              </li>
              <li>
                {ev.pct_of_growth_explained.toFixed(0)}% of total RSS growth
                attributed
              </li>
            </ul>
          </div>
        )}

        {proposal ? (
          <>
            <Field label="Diagnosis" value={proposal.diagnosis} />
            <Field label="Root Cause" value={proposal.root_cause} />
            <Field label="Fix Strategy" value={proposal.fix_strategy} />
            <div>
              <span className="text-slate-400">Confidence: </span>
              <span className="font-mono uppercase text-amber-300">
                {proposal.confidence}
              </span>
            </div>

            {accuracy !== null && (
              <div
                className={`rounded-md border px-3 py-2 ${
                  evalPass
                    ? "border-emerald-600/50 bg-emerald-600/10 text-emerald-300"
                    : "border-red-600/50 bg-red-600/10 text-red-300"
                }`}
              >
                Weave Eval: {evalPass ? "✅" : "❌"} Diagnosis Accuracy: {accuracy}%
                <div className="mt-1 text-xs text-slate-400">
                  correct op:{" "}
                  {proposal.eval.mentioned_correct_op ? "yes" : "no"} · cause
                  identified: {proposal.eval.identified_cause ? "yes" : "no"}
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="italic text-slate-400">Diagnosing…</div>
        )}

        <div className="pt-2">
          <ApplyButton state={state} />
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-slate-400">{label}:</div>
      <div className="text-slate-100">{value}</div>
    </div>
  );
}
