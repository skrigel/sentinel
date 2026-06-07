import { useState } from 'react';
import { Link } from 'react-router-dom';
import { MetricChart } from '../components/MetricChart';
import { InterventionCard } from '../components/InterventionCard';
import { IssueNotification } from '../components/IssueNotification';
import { usePolling } from '../hooks/usePolling';
import {
  buildAgent,
  buildInterventions,
  fetchIncident,
  fetchMemoryMetrics,
  hasActiveIssue,
} from '../services/sentinelApi';

export function Dashboard() {
  const [dismissedIssue, setDismissedIssue] = useState(false);

  const { data: incident } = usePolling({ fetchFn: fetchIncident, interval: 2000 });
  const { data: memory } = usePolling({ fetchFn: fetchMemoryMetrics, interval: 2000 });

  const agent = buildAgent(incident ?? null, memory ?? []);
  const interventions = buildInterventions(incident ?? null);
  const showNotification = !dismissedIssue && hasActiveIssue(incident ?? null);

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
          <h2 className="text-lg font-medium text-gray-900">Resource Metrics</h2>

          {/* Agent status */}
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">
              Monitored Agent
            </div>
            <div className="flex items-center justify-between px-3 py-2 rounded bg-gray-100">
              <span className="text-sm font-medium text-gray-900">{agent.name}</span>
              <span className={`text-xs px-2 py-0.5 rounded ${
                agent.status === 'healthy' ? 'bg-green-50 text-green-700' :
                agent.status === 'warning' ? 'bg-amber-50 text-amber-700' :
                agent.status === 'critical' ? 'bg-red-50 text-red-700' :
                'bg-blue-50 text-blue-700'
              }`}>
                {agent.status}
              </span>
            </div>
          </div>

          {/* Memory chart (real RSS). The backend does not expose a CPU series. */}
          <div className="bg-white border border-gray-200 rounded-lg p-6">
            <MetricChart
              data={agent.metrics.memory}
              type="memory"
              status={agent.status}
            />
          </div>
        </div>

        {/* Right: Agent Activity */}
        <div className="space-y-6">
          <h2 className="text-lg font-medium text-gray-900">Agent Activity</h2>

          <div className="space-y-3">
            {interventions.length > 0 ? (
              interventions.map(intervention => (
                <div key={intervention.id} className="border border-gray-200 rounded-lg overflow-hidden">
                  <InterventionCard intervention={intervention} />
                </div>
              ))
            ) : (
              <div className="bg-white border border-gray-200 rounded-lg p-8 text-center">
                <div className="text-sm text-gray-500">No active interventions</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Issue Notification */}
      {showNotification && (
        <IssueNotification
          agentName={agent.name}
          issue={interventions[0]?.issue ?? 'Anomaly detected'}
          severity={interventions[0]?.severity ?? 'warning'}
          onDismiss={() => setDismissedIssue(true)}
        />
      )}
    </div>
  );
}
