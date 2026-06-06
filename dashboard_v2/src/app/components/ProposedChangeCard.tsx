import { useState } from 'react';
import { ProposedChange } from '../sentinelTypes';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/dialog';

interface ProposedChangeCardProps {
  change: ProposedChange;
  onApprove?: (id: string) => void;
  onReject?: (id: string) => void;
}

export function ProposedChangeCard({ change, onApprove, onReject }: ProposedChangeCardProps) {
  const [showCode, setShowCode] = useState(false);

  return (
    <>
      <div className="bg-white border border-amber-200 rounded-lg p-5 space-y-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <div className="text-sm font-medium text-gray-900">{change.agentName}</div>
              <div className={`text-xs px-2 py-0.5 rounded ${
                change.severity === 'critical'
                  ? 'bg-red-50 text-red-700'
                  : 'bg-amber-50 text-amber-700'
              }`}>
                {change.severity}
              </div>
            </div>
            <div className="text-xs text-gray-500">{change.issue}</div>
          </div>
        </div>

        {/* Fix description */}
        <div>
          <div className="text-xs font-medium text-gray-500 mb-1">Proposed Fix</div>
          <div className="text-sm text-gray-700">{change.proposedFix}</div>
        </div>

        {/* Code preview */}
        <div className="bg-gray-50 border border-gray-200 rounded p-3">
          <div className="text-xs text-gray-500 mb-2">
            {change.code.file} · Line {change.code.line}
          </div>
          <button
            onClick={() => setShowCode(true)}
            className="text-xs font-medium text-blue-600 hover:text-blue-700"
          >
            View code changes →
          </button>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 pt-2">
          <button
            onClick={() => onApprove?.(change.id)}
            className="flex-1 px-4 py-2 bg-gray-900 text-white text-sm font-medium rounded hover:bg-gray-800 transition-colors"
          >
            Approve & Apply
          </button>
          <button
            onClick={() => onReject?.(change.id)}
            className="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded hover:bg-gray-50 transition-colors"
          >
            Reject
          </button>
        </div>
      </div>

      {/* Code dialog */}
      <Dialog open={showCode} onOpenChange={setShowCode}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-auto bg-white">
          <DialogHeader>
            <DialogTitle className="text-base font-medium text-gray-900">
              Proposed Code Changes
            </DialogTitle>
            <div className="text-sm text-gray-500">
              {change.code.file} · Line {change.code.line}
            </div>
          </DialogHeader>

          <div className="space-y-4 mt-4">
            <div>
              <div className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wide">
                Before
              </div>
              <pre className="bg-red-50 border border-red-100 rounded p-3 text-xs overflow-x-auto">
                <code className="text-gray-800">{change.code.before}</code>
              </pre>
            </div>

            <div>
              <div className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wide">
                After
              </div>
              <pre className="bg-green-50 border border-green-100 rounded p-3 text-xs overflow-x-auto">
                <code className="text-gray-800">{change.code.after}</code>
              </pre>
            </div>

            <div className="bg-amber-50 border border-amber-200 rounded p-3">
              <div className="text-xs font-medium text-amber-900 mb-1">Fix Summary</div>
              <div className="text-sm text-amber-800">{change.proposedFix}</div>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
