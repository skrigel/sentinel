import { useEffect, useMemo, useRef, useState } from 'react';
import * as monaco from 'monaco-editor';
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import { DiffEditor, loader } from '@monaco-editor/react';
import { Check, Loader2, X } from 'lucide-react';
import { ProposedChange } from '../sentinelTypes';

// Bundle Monaco (and its diff/editor worker) locally instead of the default CDN
// loader, so the live demo renders even with no network. The editor worker is
// what computes the red/green diff, so it must be wired up explicitly.
(self as unknown as { MonacoEnvironment?: monaco.Environment }).MonacoEnvironment = {
  getWorker: () => new editorWorker(),
};
loader.config({ monaco });

/** Where the incident is in its lifecycle, projected onto the diff visual. */
export type DiffPhase = 'pending' | 'applying' | 'resolved';

interface LiveDiffApprovalProps {
  change: ProposedChange & { code: NonNullable<ProposedChange['code']> };
  phase: DiffPhase;
  onApprove: () => void;
  onReject: () => void;
  /** Recovery reduction (%) to surface once resolved. */
  reductionPct?: number;
}

// Characters typed per animation tick, and the tick interval — tuned to read as
// fast "AI typing" while staying short enough to finish within an APPLYING_FIX.
const TYPE_CHARS_PER_TICK = 2;
const TYPE_TICK_MS = 16;

const LINE_HEIGHT = 19;

export function LiveDiffApproval({
  change,
  phase,
  onApprove,
  onReject,
  reductionPct,
}: LiveDiffApprovalProps) {
  const { file, before, after, line } = change.code;

  // The text shown on the "modified" side. During APPLYING_FIX we retype it from
  // scratch (the money shot); otherwise it's the full proposed result.
  const [typed, setTyped] = useState(phase === 'applying' ? '' : after);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);

    if (phase !== 'applying') {
      setTyped(after);
      return;
    }

    setTyped('');
    let i = 0;
    intervalRef.current = setInterval(() => {
      i += TYPE_CHARS_PER_TICK;
      if (i >= after.length) {
        setTyped(after);
        if (intervalRef.current) clearInterval(intervalRef.current);
      } else {
        setTyped(after.slice(0, i));
      }
    }, TYPE_TICK_MS);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [phase, after]);

  // Inline diff stacks removed + added lines, so size to both sides.
  const height = useMemo(() => {
    const lines = before.split('\n').length + after.split('\n').length + 1;
    return Math.min(Math.max(lines * LINE_HEIGHT + 16, 120), 360);
  }, [before, after]);

  const lang = file.endsWith('.py') ? 'python' : 'typescript';

  return (
    <div
      className={`bg-white border rounded-lg overflow-hidden ${
        phase === 'resolved'
          ? 'border-green-300'
          : phase === 'applying'
            ? 'border-indigo-300'
            : 'border-amber-200'
      }`}
    >
      {/* Header: who/what + lifecycle banner */}
      <div className="px-5 pt-4 pb-3 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <div className="text-sm font-medium text-gray-900">{change.agentName}</div>
              <div
                className={`text-xs px-2 py-0.5 rounded ${
                  change.severity === 'critical'
                    ? 'bg-red-50 text-red-700'
                    : 'bg-amber-50 text-amber-700'
                }`}
              >
                {change.severity}
              </div>
            </div>
            <div className="text-xs text-gray-500">{change.issue}</div>
          </div>
          <PhaseBadge phase={phase} reductionPct={reductionPct} />
        </div>

        <div>
          <div className="text-xs font-medium text-gray-500 mb-1">Proposed Fix</div>
          <div className="text-sm text-gray-700">{change.proposedFix}</div>
        </div>
      </div>

      {/* The Monaco IDE diff */}
      <div className="border-y border-gray-200 bg-[#1e1e1e]">
        <div className="flex items-center justify-between px-4 py-1.5 text-xs text-gray-400 border-b border-black/30">
          <span className="font-mono">{file}</span>
          <span>Line {line}</span>
        </div>
        <DiffEditor
          height={height}
          language={lang}
          original={before}
          modified={typed}
          theme="vs-dark"
          options={{
            renderSideBySide: false,
            readOnly: true,
            domReadOnly: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            lineNumbers: 'on',
            fontSize: 13,
            renderOverviewRuler: false,
            scrollbar: { vertical: 'hidden', horizontal: 'auto' },
            folding: false,
            glyphMargin: false,
            guides: { indentation: false },
          }}
        />
      </div>

      {/* Actions — only while awaiting human authorization */}
      {phase === 'pending' && (
        <div className="flex items-center gap-2 px-5 py-4">
          <button
            onClick={onApprove}
            className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2 bg-gray-900 text-white text-sm font-medium rounded hover:bg-gray-800 transition-colors"
          >
            <Check className="w-4 h-4" />
            Approve & Apply
          </button>
          <button
            onClick={onReject}
            className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded hover:bg-gray-50 transition-colors"
          >
            <X className="w-4 h-4" />
            Reject
          </button>
        </div>
      )}
      {phase === 'applying' && (
        <div className="flex items-center gap-2 px-5 py-4 text-sm text-indigo-700">
          <Loader2 className="w-4 h-4 animate-spin" />
          Applying fix — writing changes to {file}…
        </div>
      )}
      {phase === 'resolved' && (
        <div className="flex items-center gap-2 px-5 py-4 text-sm text-green-700">
          <Check className="w-4 h-4" />
          Applied &amp; verified
          {typeof reductionPct === 'number' && (
            <span className="text-green-600">· {reductionPct}% growth reduction</span>
          )}
        </div>
      )}
    </div>
  );
}

function PhaseBadge({ phase, reductionPct }: { phase: DiffPhase; reductionPct?: number }) {
  if (phase === 'applying') {
    return (
      <span className="shrink-0 inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded bg-indigo-50 text-indigo-700">
        <Loader2 className="w-3 h-3 animate-spin" />
        Applying
      </span>
    );
  }
  if (phase === 'resolved') {
    return (
      <span className="shrink-0 inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded bg-green-50 text-green-700">
        <Check className="w-3 h-3" />
        {typeof reductionPct === 'number' ? `Recovered ${reductionPct}%` : 'Resolved'}
      </span>
    );
  }
  return (
    <span className="shrink-0 inline-flex items-center text-xs font-medium px-2 py-1 rounded bg-amber-50 text-amber-700">
      Awaiting approval
    </span>
  );
}
