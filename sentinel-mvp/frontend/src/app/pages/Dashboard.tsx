import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Trash2 } from 'lucide-react';
import { MetricChart } from '../components/MetricChart';
import { KernelSignalsCard, FingerprintCard } from '../components/KernelSignals';
import { InterventionCard } from '../components/InterventionCard';
import { IssueNotification } from '../components/IssueNotification';
import { FileSelector } from '../components/FileUpload';
import { usePolling } from '../hooks/usePolling';
import {
  buildAgent,
  deleteAgent,
  extractFingerprint,
  fetchAgentMemoryMetrics,
  fetchAgents,
  fetchIncident,
  fetchInterventions,
  fetchKernelSignals,
  hasActiveIssue,
  updateAgent,
  uploadAgents,
} from '../services/sentinelApi';

export function Dashboard() {
  const [dismissedIssue, setDismissedIssue] = useState(false);
  const [selectedMemoryAgentIds, setSelectedMemoryAgentIds] = useState<string[]>([]);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [agentName, setAgentName] = useState('Document-QA Agent');
  const [entryPoint, setEntryPoint] = useState('process_batch');

  const { data: incident } = usePolling({ fetchFn: fetchIncident, interval: 1000 });
  const { data: agentList, refetch: refetchAgents } = usePolling({ fetchFn: fetchAgents, interval: 5000 });
  const { data: agentMemory, refetch: refetchAgentMemory } = usePolling({
    fetchFn: fetchAgentMemoryMetrics,
    interval: 1000,
  });
  // Durable list of past + active interventions (persists across incidents/reset).
  const { data: interventionList } = usePolling({ fetchFn: fetchInterventions, interval: 1000 });
  // Extra kernel signals (USS / CPU% / FDs / threads) from GET /api/procstat.
  const { data: kernelSignals } = usePolling({ fetchFn: fetchKernelSignals, interval: 2000 });

  const agents = agentList ?? [];
  const monitoredAgents = agents.filter((item) => item.monitored);
  const memorySeries = agentMemory ?? [];
  const primarySeries = memorySeries.find((series) => series.data.length > 0) ?? memorySeries[0];
  const agentLabel = (item: { filename?: string; display_name: string }) =>
    item.display_name || item.filename || 'Agent';
  const agent = {
    ...buildAgent(incident ?? null, primarySeries?.data ?? []),
    id: primarySeries?.agent.id ?? 'victim',
    name: primarySeries ? agentLabel(primarySeries.agent) : 'Document-QA Agent',
  };
  const interventions = interventionList ?? [];
  const fingerprint = extractFingerprint(incident ?? null);
  const signals = kernelSignals ?? { uss: [], cpuPct: [], numFds: [], numThreads: [] };
  const showNotification = !dismissedIssue && hasActiveIssue(incident ?? null);
  const selectedSeries = memorySeries.filter((series) =>
    selectedMemoryAgentIds.includes(series.agent.id)
  );

  useEffect(() => {
    if (!memorySeries.length) return;
    const monitoredIds = memorySeries.map((series) => series.agent.id);
    setSelectedMemoryAgentIds((current) => {
      const stillVisible = current.filter((id) => monitoredIds.includes(id));
      return stillVisible.length > 0 ? stillVisible : monitoredIds.slice(0, 1);
    });
  }, [memorySeries]);

  const handleUpload = async (files: File[]) => {
    if (!files.length) return;
    const name = agentName.trim();
    const monitoredOp = entryPoint.trim();
    if (!name) {
      setUploadStatus('Enter an agent name before uploading');
      return;
    }
    if (!monitoredOp) {
      setUploadStatus('Enter the op to monitor before uploading');
      return;
    }
    setUploadStatus('Uploading...');
    try {
      const uploaded = await uploadAgents(files, monitoredOp, name);
      await Promise.all([refetchAgents(), refetchAgentMemory()]);
      const sourceOnly = uploaded.some((item) => item.runtime_status === 'source_only');
      const message = uploaded[0]?.runtime_message;
      setUploadStatus(
        sourceOnly
          ? message ?? `${name} uploaded for source diagnosis`
          : `${name} uploaded and running ${monitoredOp}`
      );
    } catch (error) {
      setUploadStatus(error instanceof Error ? error.message : 'Upload failed');
    }
  };

  const handleMonitorToggle = async (agentId: string, monitored: boolean) => {
    await updateAgent(agentId, { monitored });
    await Promise.all([refetchAgents(), refetchAgentMemory()]);
    setSelectedMemoryAgentIds((current) =>
      monitored
        ? Array.from(new Set([...current, agentId]))
        : current.filter((id) => id !== agentId)
    );
  };

  const handleDelete = async (agentId: string) => {
    await deleteAgent(agentId);
    await Promise.all([refetchAgents(), refetchAgentMemory()]);
    setSelectedMemoryAgentIds((current) => current.filter((id) => id !== agentId));
  };

  const handleEntryPointUpdate = async (agentId: string, value: string) => {
    const monitoredOp = value.trim();
    if (!monitoredOp) {
      setUploadStatus('Entry point cannot be empty');
      return;
    }
    try {
      await updateAgent(agentId, { entry_point: monitoredOp });
      await refetchAgents();
      setUploadStatus(`Monitoring op updated to ${monitoredOp}`);
    } catch (error) {
      setUploadStatus(error instanceof Error ? error.message : 'Entry point update failed');
    }
  };

  const toggleMemorySeries = (agentId: string) => {
    setSelectedMemoryAgentIds((current) =>
      current.includes(agentId)
        ? current.filter((id) => id !== agentId)
        : [...current, agentId]
    );
  };

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
            <div className="flex items-center gap-2">
              <Link
                to="/"
                className="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded hover:bg-gray-50 transition-colors"
              >
                Home
              </Link>
              <Link
                to="/sentinel"
                className="px-4 py-2 bg-gray-900 text-white text-sm font-medium rounded hover:bg-gray-800 transition-colors"
              >
                Sentinel Status
              </Link>
            </div>
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
              Monitored Agents
            </div>
            <div className="mb-4">
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Agent name
                  </span>
                  <input
                    type="text"
                    value={agentName}
                    onChange={(event) => setAgentName(event.target.value)}
                    placeholder="Document-QA Agent"
                    className="w-full rounded border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition-colors focus:border-gray-900"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Entry point / op
                  </span>
                  <input
                    type="text"
                    value={entryPoint}
                    onChange={(event) => setEntryPoint(event.target.value)}
                    placeholder="process_batch, run_agent, main"
                    className="w-full rounded border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition-colors focus:border-gray-900"
                  />
                </label>
                <FileSelector
                  accept=".py"
                  label="Upload agent"
                  onFilesSelected={handleUpload}
                />
              </div>
              {uploadStatus && <div className="mt-2 text-xs text-gray-500">{uploadStatus}</div>}
            </div>
            <div className="space-y-2">
              {agents.map((item) => (
                <div key={item.id} className="flex flex-col gap-3 px-3 py-2 rounded bg-gray-100 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-gray-900">{agentLabel(item)}</div>
                    <div className="truncate text-xs text-gray-500">
                      {item.runtime_message ?? (item.monitored ? 'Running in the victim loop' : 'Not running')}
                    </div>
                    <label className="mt-2 flex max-w-sm items-center gap-2 text-xs text-gray-500">
                      <span className="shrink-0">op</span>
                      <input
                        type="text"
                        defaultValue={item.entry_point}
                        onBlur={(event) => {
                          if (event.currentTarget.value.trim() !== item.entry_point) {
                            void handleEntryPointUpdate(item.id, event.currentTarget.value);
                          }
                        }}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') event.currentTarget.blur();
                        }}
                        className="min-w-0 flex-1 rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 outline-none transition-colors focus:border-gray-900"
                      />
                    </label>
                  </div>
                  <div className="flex items-center gap-2">
                    {item.runtime_status === 'source_only' ? (
                      <span className="text-xs px-2 py-1 rounded bg-gray-200 text-gray-600">
                        Source only
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleMonitorToggle(item.id, !item.monitored)}
                        className={`text-xs px-2 py-1 rounded transition-colors ${
                          item.monitored
                            ? 'bg-green-50 text-green-700 hover:bg-green-100'
                            : 'bg-gray-200 text-gray-600 hover:bg-gray-300'
                        }`}
                      >
                        {item.monitored ? 'Monitoring' : 'Paused'}
                      </button>
                    )}
                    {item.id !== 'victim' && (
                      <button
                        type="button"
                        onClick={() => handleDelete(item.id)}
                        className="p-1.5 rounded text-gray-400 hover:bg-red-50 hover:text-red-600"
                        aria-label={`Delete ${agentLabel(item)}`}
                        title="Delete agent"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </div>
              ))}
              {agents.length === 0 && (
                <div className="px-3 py-2 rounded bg-gray-100 text-sm text-gray-500">
                  No agents configured yet
                </div>
              )}
            </div>
          </div>

          {/* Memory chart (real RSS). The backend does not expose a CPU series. */}
          <div className="bg-white border border-gray-200 rounded-lg p-6">
            <div className="mb-4 flex flex-wrap gap-2">
              {monitoredAgents.map((item) => {
                const selected = selectedMemoryAgentIds.includes(item.id);
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => toggleMemorySeries(item.id)}
                    className={`text-xs px-3 py-1.5 rounded border transition-colors ${
                      selected
                        ? 'border-gray-900 bg-gray-900 text-white'
                        : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    {agentLabel(item)}
                  </button>
                );
              })}
            </div>
            <div className="space-y-6">
              {selectedSeries.map((series) => (
                <MetricChart
                  key={series.agent.id}
                  data={series.data}
                  type="memory"
                  status={agent.status}
                  label={agentLabel(series.agent)}
                />
              ))}
              {selectedSeries.length === 0 && (
                <div className="py-12 text-center text-sm text-gray-500">
                  Select a monitored agent to show memory usage
                </div>
              )}
            </div>
          </div>

          {/* Cause fingerprint (deterministic classification from the signals). */}
          <FingerprintCard
            fingerprint={fingerprint}
            subcause={incident?.suspected_subcause}
            confidence={incident?.confidence}
          />

          {/* Extra kernel signals pulled from the OS by the collector. */}
          <KernelSignalsCard signals={signals} status={agent.status} />
        </div>

        {/* Right: Agent Activity */}
        <div className="space-y-6">
          <h2 className="text-lg font-medium text-gray-900">Agent Activity</h2>

          <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
            {interventions.length > 0 ? (
              interventions.map(intervention => (
                <div key={intervention.id} className="border border-gray-200 rounded-lg overflow-hidden">
                  <InterventionCard intervention={intervention} />
                </div>
              ))
            ) : (
              <div className="bg-white border border-gray-200 rounded-lg p-8 text-center">
                <div className="text-sm text-gray-500">No interventions recorded yet</div>
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
