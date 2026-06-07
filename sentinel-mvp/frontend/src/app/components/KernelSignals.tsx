import { MetricChart } from './MetricChart';
import { FingerprintEvidence, KernelSignals, isAutoFixable } from '../services/sentinelApi';
import { Agent } from '../types';

interface KernelSignalsCardProps {
  signals: KernelSignals;
  status: Agent['status'];
}

/** The four extra signals the collector reads from the kernel each ~2s
 *  (USS, CPU%, open FDs, thread count), charted alongside the RSS series. */
export function KernelSignalsCard({ signals, status }: KernelSignalsCardProps) {
  const hasAny =
    signals.uss.length || signals.cpuPct.length || signals.numFds.length || signals.numThreads.length;

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-900">Kernel Signals</h3>
        <p className="text-xs text-gray-500 mt-1">
          Read from the OS by the collector (<code>metrics:procstat</code>) every ~2s
        </p>
      </div>

      {hasAny ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <MetricChart data={signals.uss} type="memory" status={status} label="USS (unique set)" unit="MB" />
          <MetricChart data={signals.cpuPct} type="cpu" status={status} label="Process CPU" unit="%" />
          <MetricChart data={signals.numFds} type="cpu" status={status} label="Open FDs" unit="" precision={0} />
          <MetricChart data={signals.numThreads} type="cpu" status={status} label="Threads" unit="" precision={0} />
        </div>
      ) : (
        <div className="py-10 text-center text-sm text-gray-500">
          No kernel signals yet — the collector emits these once the victim is running.
        </div>
      )}
    </div>
  );
}

const SUBCAUSE_LABEL: Record<string, string> = {
  unbounded_collection: 'Unbounded collection',
  native_memory_growth: 'Native memory growth',
  fd_leak: 'File-descriptor leak',
  thread_leak: 'Thread leak',
  sync_io_in_async_loop: 'Sync I/O in async loop',
  unknown: 'Unknown',
};

function humanizeSubcause(subcause: string | null | undefined): string {
  if (!subcause) return 'Unclassified';
  return SUBCAUSE_LABEL[subcause] ?? subcause;
}

function fmt(value: number | null | undefined, opts?: { pct?: boolean; bytes?: boolean }): string {
  if (value === null || value === undefined) return '—';
  if (opts?.bytes) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (opts?.pct) return `${value.toFixed(0)}%`;
  return `${value}`;
}

interface FingerprintCardProps {
  fingerprint: FingerprintEvidence | null;
  subcause: string | null | undefined;
  confidence: number | undefined;
}

/** "Here's why we say X": the deterministic cross-signal reasoning the graph
 *  used (matched_rule + the signal values it weighed), with an honest note when
 *  the subcause has no auto-fix by design. */
export function FingerprintCard({ fingerprint, subcause, confidence }: FingerprintCardProps) {
  if (!fingerprint) return null;
  const autoFixable = isAutoFixable(subcause);

  const rows: { label: string; value: string }[] = [
    { label: 'tracemalloc share', value: fmt(fingerprint.tracemalloc_pct, { pct: true }) },
    { label: 'USS net change', value: fmt(fingerprint.uss_net, { bytes: true }) },
    { label: 'FDs net change', value: fmt(fingerprint.fds_net) },
    { label: 'Threads net change', value: fmt(fingerprint.threads_net) },
    { label: 'CPU% mean', value: fmt(fingerprint.cpu_pct_mean, { pct: true }) },
    { label: 'Loop-lag mean', value: fingerprint.loop_lag_mean == null ? '—' : `${fingerprint.loop_lag_mean.toFixed(1)} ms` },
  ];

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-gray-900">Cause Fingerprint</h3>
          <p className="text-xs text-gray-500 mt-1">Deterministic classification from kernel + runtime signals</p>
        </div>
        <span
          className={`shrink-0 text-xs font-medium px-2 py-1 rounded ${
            autoFixable ? 'bg-blue-50 text-blue-700' : 'bg-amber-50 text-amber-700'
          }`}
        >
          {autoFixable ? 'Auto-fixable' : 'Detected — no auto-fix yet'}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wide">Suspected cause</div>
          <div className="text-lg font-light text-gray-900">{humanizeSubcause(subcause)}</div>
        </div>
        {fingerprint.matched_rule && (
          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wide">Matched rule</div>
            <code className="text-sm text-gray-800">{fingerprint.matched_rule}</code>
          </div>
        )}
        {confidence !== undefined && (
          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wide">Confidence</div>
            <div className="text-sm text-gray-800">{Math.round(confidence * 100)}%</div>
          </div>
        )}
        {fingerprint.mode && (
          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wide">Mode</div>
            <div className="text-sm text-gray-800">{fingerprint.mode.replace('_', ' ')}</div>
          </div>
        )}
      </div>

      <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-3">
        {rows.map((r) => (
          <div key={r.label} className="rounded bg-gray-50 px-3 py-2">
            <div className="text-xs text-gray-500">{r.label}</div>
            <div className="text-sm font-medium text-gray-900 mt-0.5">{r.value}</div>
          </div>
        ))}
      </div>

      {!autoFixable && (
        <p className="mt-4 text-xs text-gray-500">
          This class of fault is detected but not auto-fixable by design — Sentinel reports it for manual review
          rather than applying a fix.
        </p>
      )}
    </div>
  );
}
