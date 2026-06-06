import { useState } from 'react';
import { Intervention } from '../types';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/dialog';

interface InterventionCardProps {
  intervention: Intervention;
}

export function InterventionCard({ intervention }: InterventionCardProps) {
  const [showCode, setShowCode] = useState(false);

  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(minutes / 60);

    if (hours > 0) return `${hours}h ago`;
    if (minutes > 0) return `${minutes}m ago`;
    return 'just now';
  };

  const getStatusColor = () => {
    if (intervention.status === 'verified') return 'text-green-700';
    if (intervention.status === 'applied') return 'text-blue-700';
    if (intervention.status === 'proposed') return 'text-amber-700';
    return 'text-gray-700';
  };

  const getStatusBg = () => {
    if (intervention.status === 'verified') return 'bg-green-50';
    if (intervention.status === 'applied') return 'bg-blue-50';
    if (intervention.status === 'proposed') return 'bg-amber-50';
    return 'bg-gray-50';
  };

  return (
    <>
      <div className="bg-white p-4 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <div className="text-sm font-medium text-gray-900">
                {intervention.agentName}
              </div>
              <div className="text-xs text-gray-400">
                {formatTime(intervention.timestamp)}
              </div>
            </div>
            <div className="text-xs text-gray-500 mt-0.5">
              {intervention.issue}
            </div>
          </div>
          <div className={`text-xs font-medium px-2 py-1 rounded shrink-0 ${getStatusBg()} ${getStatusColor()}`}>
            {intervention.status}
          </div>
        </div>

        <div className="space-y-2 text-sm">
          <div>
            <div className="text-xs font-medium text-gray-500 mb-1">Root Cause</div>
            <div className="text-gray-700 leading-relaxed">{intervention.rootCause}</div>
          </div>

          <div>
            <div className="text-xs font-medium text-gray-500 mb-1">Proposed Fix</div>
            <div className="text-gray-700 leading-relaxed">{intervention.proposedFix}</div>
          </div>

          {intervention.metricsAfter && (
            <div className="flex items-center gap-4 pt-1">
              <div className="text-xs text-gray-500">
                Before: <span className="font-medium text-gray-900">{intervention.metricsBefore}</span>
              </div>
              <div className="text-xs text-green-600">
                After: <span className="font-medium">{intervention.metricsAfter}</span>
              </div>
            </div>
          )}
        </div>

        {intervention.code && (
          <button
            onClick={() => setShowCode(true)}
            className="text-xs font-medium text-blue-600 hover:text-blue-700 transition-colors"
          >
            View code changes →
          </button>
        )}
      </div>

      {intervention.code && (
        <Dialog open={showCode} onOpenChange={setShowCode}>
          <DialogContent className="max-w-3xl max-h-[80vh] overflow-auto bg-white">
            <DialogHeader>
              <DialogTitle className="text-base font-medium text-gray-900">
                Code Changes
              </DialogTitle>
              <div className="text-sm text-gray-500">
                {intervention.code.file} · Line {intervention.code.line}
              </div>
            </DialogHeader>

            <div className="space-y-4 mt-4">
              <div>
                <div className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wide">
                  Before
                </div>
                <pre className="bg-red-50 border border-red-100 rounded p-3 text-xs overflow-x-auto">
                  <code className="text-gray-800">{intervention.code.before}</code>
                </pre>
              </div>

              <div>
                <div className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wide">
                  After
                </div>
                <pre className="bg-green-50 border border-green-100 rounded p-3 text-xs overflow-x-auto">
                  <code className="text-gray-800">{intervention.code.after}</code>
                </pre>
              </div>

              <div className="bg-gray-50 border border-gray-100 rounded p-3">
                <div className="text-xs font-medium text-gray-700 mb-1">Impact</div>
                <div className="text-sm text-gray-600">
                  {intervention.rootCause}
                </div>
                {intervention.metricsAfter && (
                  <div className="text-xs text-gray-500 mt-2">
                    Metrics improved from {intervention.metricsBefore} to {intervention.metricsAfter}
                  </div>
                )}
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
