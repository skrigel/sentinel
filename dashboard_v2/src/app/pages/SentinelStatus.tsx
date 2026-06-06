import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Settings } from 'lucide-react';
import { mockSentinelPlan, mockProposedChanges } from '../sentinelMockData';
import { ProposedChangeCard } from '../components/ProposedChangeCard';
import { StateMachineGraph } from '../components/StateMachineGraph';
import { HorizontalActionTimeline } from '../components/HorizontalActionTimeline';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { usePolling } from '../hooks/usePolling';
import { fetchSentinelState } from '../services/sentinelApi';
import { ActionType } from '../sentinelTypes';

export function SentinelStatus() {
  const [autoApprove, setAutoApprove] = useState(false);
  const [proposedChanges, setProposedChanges] = useState(mockProposedChanges);
  const [filterState, setFilterState] = useState<ActionType | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  // Poll for Sentinel state every 3 seconds
  const { data, lastUpdated, isLoading } = usePolling({
    fetchFn: fetchSentinelState,
    interval: 3000,
  });

  const handleApprove = (id: string) => {
    setProposedChanges(prev => prev.filter(c => c.id !== id));
  };

  const handleReject = (id: string) => {
    setProposedChanges(prev => prev.filter(c => c.id !== id));
  };

  const handleStateClick = (state: ActionType) => {
    setFilterState(filterState === state ? null : state);
  };

  const formatLastUpdated = (date: Date | null) => {
    if (!date) return '';
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  };

  const filteredActions = filterState
    ? data?.recentActions.filter(a => a.type === filterState) || []
    : data?.recentActions || [];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="px-8 py-6">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-4">
              <Link to="/" className="text-blue-600 hover:text-blue-700 text-sm">
                ← Dashboard
              </Link>
            </div>
            <div className="flex items-center gap-4">
              {lastUpdated && (
                <div className="flex items-center gap-2 text-xs text-gray-500">
                  <div className={`w-2 h-2 rounded-full ${isLoading ? 'bg-orange-500 animate-pulse' : 'bg-green-500'}`} />
                  Last updated: {formatLastUpdated(lastUpdated)}
                </div>
              )}
              <button
                onClick={() => setShowSettings(true)}
                className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors"
                aria-label="Settings"
              >
                <Settings className="w-5 h-5" />
              </button>
            </div>
          </div>
          <h1 className="text-2xl font-light text-gray-900">Sentinel Status</h1>
          <p className="text-sm text-gray-500 mt-1">Self-healing agent monitoring and intervention</p>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-[1600px] mx-auto p-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Left Column: Status & Plan */}
          <div className="lg:col-span-1 space-y-6">
            {/* Combined Status & Plan */}
            <div>
              <h2 className="text-lg font-medium text-gray-900 mb-4">Status & Plan</h2>
              <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-5">
                {/* Current Status */}
                <div>
                  <div className="flex items-center gap-3 mb-2">
                    <div className="w-3 h-3 rounded-full bg-orange-500 animate-pulse" />
                    <div className="text-sm font-medium text-gray-900">Active</div>
                  </div>
                  <div className="text-sm text-gray-600 leading-relaxed">
                    {mockSentinelPlan.current}
                  </div>
                </div>

                {/* Divider */}
                <div className="border-t border-gray-200" />

                {/* Current Plan Steps */}
                <div className="space-y-3">
                  {mockSentinelPlan.steps.map((step, index) => (
                    <div key={index} className="flex items-start gap-3">
                      <div className="shrink-0 mt-1">
                        {step.status === 'completed' && (
                          <div className="w-5 h-5 rounded-full bg-green-100 flex items-center justify-center">
                            <svg className="w-3 h-3 text-green-600" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                            </svg>
                          </div>
                        )}
                        {step.status === 'active' && (
                          <div className="w-5 h-5 rounded-full bg-orange-500 flex items-center justify-center">
                            <div className="w-2 h-2 rounded-full bg-white animate-pulse" />
                          </div>
                        )}
                        {step.status === 'pending' && (
                          <div className="w-5 h-5 rounded-full border-2 border-gray-300" />
                        )}
                      </div>
                      <div className={`text-sm ${
                        step.status === 'completed' ? 'text-gray-500' :
                        step.status === 'active' ? 'text-gray-900 font-medium' :
                        'text-gray-400'
                      }`}>
                        {step.step}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Right Column: State Machine & Timeline */}
          <div className="lg:col-span-2 space-y-6">
            {/* Proposed Changes */}
            {proposedChanges.length > 0 && (
              <div>
                <h2 className="text-lg font-medium text-gray-900 mb-4">
                  Pending Approval
                  <span className="ml-2 text-sm font-normal text-amber-600">
                    ({proposedChanges.length})
                  </span>
                </h2>
                <div className="space-y-3">
                  {proposedChanges.map(change => (
                    <ProposedChangeCard
                      key={change.id}
                      change={change}
                      onApprove={handleApprove}
                      onReject={handleReject}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* State Machine Graph */}
            <div>
              <h2 className="text-lg font-medium text-gray-900 mb-4">
                Workflow State
                {filterState && (
                  <span className="ml-2 text-sm font-normal text-gray-500">
                    (Filtered: {filterState})
                  </span>
                )}
              </h2>
              <StateMachineGraph
                currentState={data?.state.currentState || 'proposing'}
                onStateClick={handleStateClick}
              />
            </div>

            {/* Horizontal Action Timeline */}
            <div>
              <h2 className="text-lg font-medium text-gray-900 mb-4">Action History</h2>
              <div className="bg-white border border-gray-200 rounded-lg p-6 overflow-x-auto">
                <HorizontalActionTimeline actions={filteredActions} />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Settings Dialog */}
      <Dialog open={showSettings} onOpenChange={setShowSettings}>
        <DialogContent className="max-w-md bg-white">
          <DialogHeader>
            <DialogTitle className="text-base font-medium text-gray-900">Settings</DialogTitle>
          </DialogHeader>

          <div className="space-y-6 mt-4">
            {/* Auto-approve toggle */}
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="text-sm font-medium text-gray-900 mb-1">
                  Auto-approve fixes
                </div>
                <div className="text-xs text-gray-500 leading-relaxed">
                  Automatically apply proposed changes without manual approval
                </div>
              </div>
              <button
                onClick={() => setAutoApprove(!autoApprove)}
                className={`shrink-0 w-11 h-6 rounded-full transition-colors ${
                  autoApprove ? 'bg-gray-900' : 'bg-gray-300'
                }`}
              >
                <div className={`w-4 h-4 bg-white rounded-full transition-transform ${
                  autoApprove ? 'translate-x-6' : 'translate-x-1'
                }`} />
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
