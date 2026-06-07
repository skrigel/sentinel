import { type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  Check,
  GitPullRequest,
  Radar,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Wrench,
  Zap,
} from 'lucide-react';

const memoryBars = [22, 29, 38, 51, 67, 83, 78, 55, 34, 26, 24, 23];
const cpuBars = [18, 20, 21, 23, 77, 86, 82, 28, 22, 19, 18, 17];

const timeline = [
  { label: 'Detect', tone: 'bg-amber-500', detail: 'RSS slope + loop lag' },
  { label: 'Trace', tone: 'bg-orange-500', detail: 'Weave spans isolate step' },
  { label: 'Patch', tone: 'bg-blue-500', detail: 'Bound state, move work' },
  { label: 'Verify', tone: 'bg-green-500', detail: 'Metrics flatten' },
];

const proofPoints = [
  { value: '2', label: 'failure modes' },
  { value: '<30s', label: 'demo arc' },
  { value: '1 loop', label: 'observe, act, verify' },
];

export function LandingPage() {
  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between px-5 py-4 sm:px-8">
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded bg-gray-900 text-white">
              <ShieldCheck className="h-4 w-4" />
            </span>
            <span className="text-sm font-medium">Sentinel</span>
          </Link>
          <nav className="flex items-center gap-2">
            <Link
              to="/dashboard"
              className="hidden rounded px-3 py-2 text-sm text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-900 sm:inline-flex"
            >
              Dashboard
            </Link>
            <Link
              to="/sentinel"
              className="inline-flex items-center gap-2 rounded bg-gray-900 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
            >
              Live status
              <ArrowRight className="h-4 w-4" />
            </Link>
          </nav>
        </div>
      </header>

      <section className="border-b border-gray-200 bg-white">
        <div className="mx-auto grid max-w-[1500px] gap-10 px-5 py-10 sm:px-8 lg:min-h-[680px] lg:grid-cols-[0.86fr_1.14fr] lg:items-center lg:py-14">
          <div className="max-w-2xl">
            <div className="mb-5 inline-flex items-center gap-2 rounded border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-600">
              <Sparkles className="h-3.5 w-3.5 text-orange-500" />
              Self-healing infra for unattended agents
            </div>
            <h1 className="max-w-xl text-5xl font-light leading-[1.03] tracking-normal text-gray-950 sm:text-6xl lg:text-7xl">
              Sentinel
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-8 text-gray-600">
              Watches long-running agents, finds the exact failure step, proposes a code fix, and proves recovery.
            </p>

            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Link
                to="/sentinel"
                className="inline-flex items-center justify-center gap-2 rounded bg-gray-900 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-gray-800"
              >
                See the repair loop
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                to="/dashboard"
                className="inline-flex items-center justify-center gap-2 rounded border border-gray-300 bg-white px-5 py-3 text-sm font-medium text-gray-800 transition-colors hover:bg-gray-50"
              >
                Open dashboard
                <Activity className="h-4 w-4" />
              </Link>
            </div>

            <div className="mt-10 grid max-w-lg grid-cols-3 divide-x divide-gray-200 border-y border-gray-200">
              {proofPoints.map((item) => (
                <div key={item.label} className="px-4 py-4 first:pl-0">
                  <div className="text-2xl font-light text-gray-950">{item.value}</div>
                  <div className="mt-1 text-xs font-medium uppercase text-gray-500">{item.label}</div>
                </div>
              ))}
            </div>
          </div>

          <HeroDemo />
        </div>
      </section>

      <section className="mx-auto grid max-w-[1500px] gap-8 px-5 py-10 sm:px-8 lg:grid-cols-[0.95fr_1.05fr]">
        <div>
          <div className="mb-4 flex items-center gap-2 text-sm font-medium text-gray-500">
            <Radar className="h-4 w-4 text-blue-500" />
            Purpose
          </div>
          <h2 className="max-w-xl text-3xl font-light leading-tight text-gray-950 sm:text-4xl">
            Agents should not need a human staring at Grafana.
          </h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <SignalCard
            icon={<Activity className="h-4 w-4" />}
            title="Observe"
            copy="Memory, CPU, lag, FDs, threads, spans."
          />
          <SignalCard
            icon={<GitPullRequest className="h-4 w-4" />}
            title="Reason"
            copy="Correlates symptoms to the offending operation."
          />
          <SignalCard
            icon={<Wrench className="h-4 w-4" />}
            title="Repair"
            copy="Ships a reviewable patch and verifies the metric."
          />
        </div>
      </section>

      <section className="border-y border-gray-200 bg-white">
        <div className="mx-auto max-w-[1500px] px-5 py-10 sm:px-8">
          <div className="mb-6 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
            <div>
              <div className="text-sm font-medium text-gray-500">Demo arc</div>
              <h2 className="mt-1 text-3xl font-light text-gray-950">Climb. Diagnose. Patch. Flatten.</h2>
            </div>
            <Link
              to="/sentinel"
              className="inline-flex items-center gap-2 self-start rounded border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-800 transition-colors hover:bg-gray-50 sm:self-auto"
            >
              Run it live
              <Zap className="h-4 w-4" />
            </Link>
          </div>

          <div className="grid gap-4 lg:grid-cols-4">
            {timeline.map((item, index) => (
              <div key={item.label} className="rounded-lg border border-gray-200 bg-white p-5">
                <div className="mb-5 flex items-center justify-between">
                  <span className={`h-3 w-3 rounded-full ${item.tone}`} />
                  <span className="text-xs font-medium text-gray-400">0{index + 1}</span>
                </div>
                <div className="text-lg font-medium text-gray-950">{item.label}</div>
                <div className="mt-2 text-sm leading-6 text-gray-500">{item.detail}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="mx-auto flex max-w-[1500px] flex-col gap-3 px-5 py-8 text-sm text-gray-500 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <span>Built for agents that keep working after the demo ends.</span>
        <div className="flex gap-4">
          <Link to="/dashboard" className="hover:text-gray-900">
            Dashboard
          </Link>
          <Link to="/sentinel" className="hover:text-gray-900">
            Sentinel status
          </Link>
        </div>
      </footer>
    </main>
  );
}

function HeroDemo() {
  return (
    <div className="relative">
      <div className="absolute -left-4 top-10 hidden h-24 w-[1px] bg-orange-300 lg:block" />
      <div className="grid gap-4">
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-gray-950 text-white shadow-2xl shadow-gray-900/10">
          <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded bg-white/10">
                <TerminalSquare className="h-4 w-4" />
              </div>
              <div>
                <div className="text-sm font-medium">Document-QA Agent</div>
                <div className="text-xs text-gray-400">process_batch</div>
              </div>
            </div>
            <div className="rounded bg-red-500/15 px-2.5 py-1 text-xs font-medium text-red-200">
              leak detected
            </div>
          </div>

          <div className="grid gap-0 lg:grid-cols-[0.92fr_1.08fr]">
            <div className="border-b border-white/10 p-5 lg:border-b-0 lg:border-r">
              <MetricVisual label="RSS memory" value="412 MB" bars={memoryBars} tone="bg-red-400" />
              <div className="mt-5 rounded border border-white/10 bg-white/[0.04] p-4">
                <div className="mb-3 flex items-center justify-between text-xs text-gray-400">
                  <span>Cause fingerprint</span>
                  <span className="text-blue-300">94%</span>
                </div>
                <div className="space-y-2">
                  <FingerprintLine label="span attr" value="history_len" />
                  <FingerprintLine label="matched rule" value="unbounded_collection" />
                  <FingerprintLine label="trace" value="retrieval.prepare_context" />
                </div>
              </div>
            </div>

            <div className="p-5">
              <div className="mb-4 flex items-center justify-between gap-4">
                <div>
                  <div className="text-xs font-medium uppercase text-gray-500">Proposed patch</div>
                  <div className="mt-1 text-sm text-gray-200">Bound retained messages before retry.</div>
                </div>
                <div className="shrink-0 rounded bg-amber-400/15 px-2.5 py-1 text-xs font-medium text-amber-200">
                  review
                </div>
              </div>
              <div className="overflow-hidden rounded border border-white/10 bg-[#111827] font-mono text-[12px] leading-5">
                <div className="flex items-center justify-between border-b border-white/10 px-3 py-2 text-gray-400">
                  <span>agents/document_qa.py</span>
                  <span>Line 88</span>
                </div>
                <div className="p-3">
                  <CodeLine prefix="-" tone="text-red-300" text="self.history.append(turn)" />
                  <CodeLine prefix="+" tone="text-green-300" text="self.history.append(turn)" />
                  <CodeLine prefix="+" tone="text-green-300" text="self.history = self.history[-24:]" />
                  <CodeLine prefix="+" tone="text-green-300" text="await verify_recovery(signal='rss')" />
                </div>
              </div>
              <div className="mt-4 flex items-center gap-2 rounded border border-green-400/20 bg-green-400/10 px-3 py-2 text-sm text-green-200">
                <Check className="h-4 w-4" />
                Fix verified. Growth returned to baseline.
              </div>
            </div>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <MiniPanel title="Event-loop stall" status="recovered">
            <MetricVisual compact label="Loop lag" value="0.8 ms" bars={cpuBars} tone="bg-blue-400" />
          </MiniPanel>
          <MiniPanel title="Weave trace" status="linked">
            <div className="space-y-2">
              {['collect metrics', 'correlate span', 'apply patch'].map((step, index) => (
                <div key={step} className="flex items-center gap-3 rounded bg-gray-50 px-3 py-2">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-gray-900 text-[10px] text-white">
                    {index + 1}
                  </span>
                  <span className="text-sm text-gray-700">{step}</span>
                </div>
              ))}
            </div>
          </MiniPanel>
        </div>
      </div>
    </div>
  );
}

function SignalCard({ icon, title, copy }: { icon: ReactNode; title: string; copy: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <div className="mb-5 flex h-9 w-9 items-center justify-center rounded bg-gray-100 text-gray-700">
        {icon}
      </div>
      <div className="text-base font-medium text-gray-950">{title}</div>
      <p className="mt-2 text-sm leading-6 text-gray-500">{copy}</p>
    </div>
  );
}

function MiniPanel({ title, status, children }: { title: string; status: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="text-sm font-medium text-gray-900">{title}</div>
        <div className="rounded bg-green-50 px-2 py-1 text-xs font-medium text-green-700">{status}</div>
      </div>
      {children}
    </div>
  );
}

function MetricVisual({
  label,
  value,
  bars,
  tone,
  compact = false,
}: {
  label: string;
  value: string;
  bars: number[];
  tone: string;
  compact?: boolean;
}) {
  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <div className={compact ? 'text-xs font-medium uppercase text-gray-500' : 'text-xs font-medium uppercase text-gray-400'}>
          {label}
        </div>
        <div className={compact ? 'text-xl font-light text-gray-900' : 'text-2xl font-light text-white'}>{value}</div>
      </div>
      <div className={`flex items-end gap-1 ${compact ? 'h-20' : 'h-36'}`}>
        {bars.map((height, index) => (
          <div
            key={`${label}-${index}`}
            className={`w-full rounded-t ${tone} ${compact ? 'opacity-70' : 'opacity-90'}`}
            style={{ height: `${height}%` }}
          />
        ))}
      </div>
    </div>
  );
}

function FingerprintLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 text-xs">
      <span className="text-gray-500">{label}</span>
      <span className="truncate text-gray-200">{value}</span>
    </div>
  );
}

function CodeLine({ prefix, tone, text }: { prefix: string; tone: string; text: string }) {
  return (
    <div className={`${tone} grid grid-cols-[16px_minmax(0,1fr)] gap-2`}>
      <span>{prefix}</span>
      <span className="truncate">{text}</span>
    </div>
  );
}
