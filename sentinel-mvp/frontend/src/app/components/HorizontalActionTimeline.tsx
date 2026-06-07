import { ExternalLink } from 'lucide-react';
import { SentinelAction } from '../sentinelTypes';

interface HorizontalActionTimelineProps {
  actions: SentinelAction[];
  /** Weave project URL (GET /api/config); one link for all actions. */
  weaveUrl?: string | null;
}

export function HorizontalActionTimeline({ actions, weaveUrl }: HorizontalActionTimelineProps) {
  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  };

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const getStatusColor = (type: SentinelAction['type']) => {
    switch (type) {
      case 'completed':
        return 'bg-green-500';
      case 'verifying':
      case 'applying':
        return 'bg-amber-500';
      case 'proposing':
      case 'analyzing':
        return 'bg-orange-500';
      case 'detecting':
        return 'bg-yellow-500';
      default:
        return 'bg-gray-400';
    }
  };

  console.log("ACTION", actions)

  return (
    <div className="relative">
      {/* Horizontal connecting line */}
      <div className="absolute top-4 left-4 right-4 h-[1px] bg-gray-200" />

      {/* Timeline items */}
      <div className="flex gap-8 overflow-x-auto pb-4">
        {actions.map((action, index) => (
          <div key={action.id} className="relative flex-shrink-0" style={{ minWidth: '200px' }}>
            {/* Status dot */}
            <div className="relative flex justify-center mb-4">
              <div className={`w-8 h-8 rounded-full ${getStatusColor(action.type)} flex items-center justify-center z-10`}>
                <div className="w-3 h-3 rounded-full bg-white" />
              </div>
            </div>

            {/* Content card */}
            <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-2 mb-1">
                <div className="text-sm font-medium text-gray-900">
                  {action.description}
                </div>
              </div>

              <div className="text-xs text-gray-500">
                {action.agentName}
              </div>

              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span>{formatTime(action.timestamp)}</span>
                {action.duration && (
                  <>
                    <span>·</span>
                    <span>({formatDuration(action.duration)})</span>
                  </>
                )}
              </div>

              {action.details && (
                <div className="text-sm text-gray-600 bg-gray-50 rounded px-3 py-2 mt-2">
                  {action.details}
                </div>
              )}

              {/* Weave trace link — one project URL for all actions. */}
              {weaveUrl && (
                <a
                  href={weaveUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 transition-colors mt-2"
                >
                  View trace in Weave
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
