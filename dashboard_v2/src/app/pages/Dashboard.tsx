import { useState } from 'react';
import { Link } from 'react-router-dom';
import { mockAgents, mockInterventions } from '../mockData';
import { MetricChart } from '../components/MetricChart';
import { InterventionCard } from '../components/InterventionCard';
import { IssueNotification } from '../components/IssueNotification';
import { TimeScale } from '../types';

export function Dashboard() {
  const [selectedAgent, setSelectedAgent] = useState(mockAgents[0].id);
  const [timeScale, setTimeScale] = useState<TimeScale>('1h');
  const [showNotification, setShowNotification] = useState(true);

  const agent = mockAgents.find(a => a.id === selectedAgent) || mockAgents[0];
  const agentInterventions = mockInterventions.filter(i => i.agentId === selectedAgent);

  const timeScales: { value: TimeScale; label: string }[] = [
    { value: '5m', label: '5m' },
    { value: '15m', label: '15m' },
    { value: '1h', label: '1h' },
    { value: '6h', label: '6h' },
    { value: '24h', label: '24h' },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-light text-gray-900">Sentinel</h1>
              <p className="text-sm text-gray-500 mt-1">Agent monitoring and self-healing system</p>
            </div>
            <Link
              to="/sentinel"
              className="px-4 py-2 bg-gray-900 text-white text-sm font-medium rounded hover:bg-gray-800 transition-colors"
            >
              Sentinel Status
            </Link>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 p-8 max-w-[1800px] mx-auto">
        {/* Left: Metrics Dashboard */}
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-medium text-gray-900">Resource Metrics</h2>

            {/* Time Scale Selector */}
            <div className="flex items-center gap-1 bg-white border border-gray-200 rounded p-1">
              {timeScales.map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setTimeScale(value)}
                  className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                    timeScale === value
                      ? 'bg-gray-900 text-white'
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Agent Selector */}
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">
              Agents
            </div>
            <div className="space-y-2">
              {mockAgents.map(a => (
                <button
                  key={a.id}
                  onClick={() => setSelectedAgent(a.id)}
                  className={`w-full text-left px-3 py-2 rounded transition-colors ${
                    selectedAgent === a.id
                      ? 'bg-gray-100'
                      : 'hover:bg-gray-50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-900">{a.name}</span>
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      a.status === 'healthy' ? 'bg-green-50 text-green-700' :
                      a.status === 'warning' ? 'bg-amber-50 text-amber-700' :
                      a.status === 'critical' ? 'bg-red-50 text-red-700' :
                      'bg-blue-50 text-blue-700'
                    }`}>
                      {a.status}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Metric Charts */}
          <div className="space-y-4">
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <MetricChart
                data={agent.metrics.memory}
                type="memory"
                status={agent.status}
              />
            </div>

            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <MetricChart
                data={agent.metrics.cpu}
                type="cpu"
                status={agent.status}
              />
            </div>
          </div>
        </div>

        {/* Right: Agent Activity */}
        <div className="space-y-6">
          <h2 className="text-lg font-medium text-gray-900">Agent Activity</h2>

          {/* Activity Feed */}
          <div className="space-y-3">
            {agentInterventions.length > 0 ? (
              agentInterventions.map(intervention => (
                <div key={intervention.id} className="border border-gray-200 rounded-lg overflow-hidden">
                  <InterventionCard intervention={intervention} />
                </div>
              ))
            ) : (
              <div className="bg-white border border-gray-200 rounded-lg p-8 text-center">
                <div className="text-sm text-gray-500">No interventions for this agent</div>
              </div>
            )}
          </div>

          {/* All Recent Activity */}
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-3">All Recent Activity</h3>
            <div className="space-y-3">
              {mockInterventions
                .filter(i => i.agentId !== selectedAgent)
                .slice(0, 3)
                .map(intervention => (
                  <div key={intervention.id} className="border border-gray-200 rounded-lg overflow-hidden">
                    <InterventionCard intervention={intervention} />
                  </div>
                ))}
            </div>
          </div>
        </div>
      </div>

      {/* Issue Notification */}
      {showNotification && (
        <IssueNotification
          agentName="QueryEngine-03"
          issue="Memory growth detected - cache eviction needed"
          severity="warning"
          onDismiss={() => setShowNotification(false)}
        />
      )}
    </div>
  );
}
