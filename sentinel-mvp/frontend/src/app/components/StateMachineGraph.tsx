import { ActionType } from '../sentinelTypes';

interface StateMachineGraphProps {
  currentState: ActionType;
  onStateClick?: (state: ActionType) => void;
}

const STATES: { type: ActionType; label: string }[] = [
  { type: 'detecting', label: 'Detecting' },
  { type: 'analyzing', label: 'Analyzing' },
  { type: 'proposing', label: 'Proposing' },
  { type: 'applying', label: 'Applying' },
  { type: 'verifying', label: 'Verifying' },
  { type: 'completed', label: 'Completed' },
];

export function StateMachineGraph({ currentState, onStateClick }: StateMachineGraphProps) {
  const currentIndex = STATES.findIndex(s => s.type === currentState);

  const getNodeColor = (index: number) => {
    if (index === currentIndex) return '#f59e0b'; // amber/orange - active
    if (index < currentIndex) return '#10b981'; // green - completed
    return '#d1d5db'; // gray - pending
  };

  const getNodeBorderColor = (index: number) => {
    if (index === currentIndex) return '#d97706';
    if (index < currentIndex) return '#059669';
    return '#9ca3af';
  };

  const getTextColor = (index: number) => {
    if (index === currentIndex) return '#92400e'; // dark amber
    if (index < currentIndex) return '#047857'; // dark green
    return '#6b7280'; // medium gray
  };

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <div className="flex items-center justify-between">
        {STATES.map((state, index) => (
          <div key={state.type} className="flex items-center">
            {/* State Node */}
            <button
              onClick={() => onStateClick?.(state.type)}
              className="flex flex-col items-center group cursor-pointer"
            >
              {/* Circle */}
              <div className="relative">
                <svg width="48" height="48" className="mb-2">
                  {/* Outer ring for active state */}
                  {index === currentIndex && (
                    <circle
                      cx="24"
                      cy="24"
                      r="22"
                      fill="none"
                      stroke={getNodeBorderColor(index)}
                      strokeWidth="1"
                      opacity="0.3"
                      className="animate-pulse"
                    />
                  )}

                  {/* Main circle */}
                  <circle
                    cx="24"
                    cy="24"
                    r="16"
                    fill={getNodeColor(index)}
                    className="transition-all group-hover:r-[18]"
                  />

                  {/* Inner circle */}
                  <circle
                    cx="24"
                    cy="24"
                    r="10"
                    fill="white"
                    opacity={index === currentIndex ? "0.8" : index < currentIndex ? "1" : "0.5"}
                  />

                  {/* Checkmark for completed states */}
                  {index < currentIndex && (
                    <path
                      d="M18 24 L22 28 L30 20"
                      fill="none"
                      stroke={getNodeBorderColor(index)}
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  )}

                  {/* Pulse dot for active state */}
                  {index === currentIndex && (
                    <circle
                      cx="24"
                      cy="24"
                      r="6"
                      fill={getNodeBorderColor(index)}
                      className="animate-pulse"
                    />
                  )}
                </svg>
              </div>

              {/* Label */}
              <div
                className={`text-xs font-medium transition-colors ${
                  index === currentState ? 'font-semibold' : ''
                }`}
                style={{ color: getTextColor(index) }}
              >
                {state.label}
              </div>
            </button>

            {/* Arrow connector */}
            {index < STATES.length - 1 && (
              <svg width="60" height="48" className="mx-2">
                <line
                  x1="10"
                  y1="24"
                  x2="50"
                  y2="24"
                  stroke={index < currentIndex ? '#10b981' : '#d1d5db'}
                  strokeWidth="2"
                  strokeDasharray={index < currentIndex ? 'none' : '4 4'}
                />
                <polygon
                  points="50,24 45,20 45,28"
                  fill={index < currentIndex ? '#10b981' : '#d1d5db'}
                />
              </svg>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
