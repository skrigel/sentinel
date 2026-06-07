"use client";

import { useState } from "react";
import { applyFix, type IncidentState } from "../lib/api";

interface Props {
  state: IncidentState;
}

export function ApplyButton({ state }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applying = state === "APPLYING";
  const disabled = state !== "AWAITING_APPROVAL" || applying;

  async function onConfirm() {
    setConfirming(false);
    setError(null);
    try {
      await applyFix();
    } catch (e) {
      setError(String(e));
    }
  }

  if (applying) {
    return (
      <button
        disabled
        className="w-full rounded-md bg-sky-700/60 px-4 py-2 font-semibold text-white"
      >
        Applying fix… switching victim to fixed mode, verifying recovery
      </button>
    );
  }

  return (
    <div>
      <button
        disabled={disabled}
        onClick={() => setConfirming(true)}
        className="w-full rounded-md bg-emerald-600 px-4 py-2 font-semibold text-white enabled:hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
      >
        Apply Fix
      </button>
      {error && (
        <div className="mt-2 text-sm text-red-400">
          {error}{" "}
          <button onClick={() => setConfirming(true)} className="underline">
            Retry
          </button>
        </div>
      )}

      {confirming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-80 rounded-lg border border-slate-700 bg-slate-900 p-5">
            <h3 className="font-semibold text-slate-100">Switch to fixed mode?</h3>
            <p className="mt-2 text-sm text-slate-400">
              This flips the victim to its pre-written fixed mode and verifies
              recovery on the live graph.
            </p>
            <div className="mt-4 flex gap-2">
              <button
                onClick={onConfirm}
                className="flex-1 rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
              >
                Confirm
              </button>
              <button
                onClick={() => setConfirming(false)}
                className="flex-1 rounded-md bg-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-600"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
