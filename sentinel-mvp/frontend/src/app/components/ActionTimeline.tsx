import { SentinelAction } from '../sentinelTypes';

interface ActionTimelineProps {
  actions: SentinelAction[];
}

export function ActionTimeline({ actions }: ActionTimelineProps) {
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

  const getStatusLabel = (type: SentinelAction['type']) => {
    switch (type) {
      case 'completed':
        return 'Completed';
      case 'verifying':
        return 'Verifying';
      case 'applying':
        return 'Applying';
      case 'proposing':
        return 'Proposing';
      case 'analyzing':
        return 'Analyzing';
      case 'detecting':
        return 'Detecting';
      default:
        return type;
    }
  };

  return (
    <div className="space-y-0">
      {actions.map((action, index) => (
        <div key={action.id} className="relative">
          {/* Vertical line */}
          {index < actions.length - 1 && (
            <div className="absolute left-[15px] top-8 bottom-0 w-[1px] bg-gray-200" />
          )}

          <div className="flex gap-4 pb-6">
            {/* Status dot */}
            <div className="relative shrink-0">
              <div className={`w-8 h-8 rounded-full ${getStatusColor(action.type)} flex items-center justify-center`}>
                <div className="w-3 h-3 rounded-full bg-white" />
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 pt-0.5">
              <div className="flex items-center gap-2 mb-1">
                <div className="text-sm font-medium text-gray-900">
                  {action.description}
                </div>
                <div className="text-xs text-gray-400">
                  {formatTime(action.timestamp)}
                </div>
                {action.duration && (
                  <div className="text-xs text-gray-400">
                    ({formatDuration(action.duration)})
                  </div>
                )}
              </div>

              <div className="text-xs text-gray-500 mb-2">
                {action.agentName}
              </div>

              {action.details && (
                <div className="text-sm text-gray-600 bg-gray-50 rounded px-3 py-2 mt-2">
                  {action.details}
                </div>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
