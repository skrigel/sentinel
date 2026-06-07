import { SentinelAction, SentinelPlan, ProposedChange, SentinelState } from './sentinelTypes';

const now = Date.now();

export const mockSentinelActions: SentinelAction[] = [
  {
    id: 'action-1',
    timestamp: now - 600000,
    type: 'completed',
    agentId: 'agent-1',
    agentName: 'DataPipeline-01',
    description: 'Memory leak resolved',
    details: 'Applied ring buffer pattern to message history',
    duration: 45000,
    traceId: 'trace-memory-leak-1',
  },
  {
    id: 'action-2',
    timestamp: now - 580000,
    type: 'completed',
    agentId: 'agent-1',
    agentName: 'DataPipeline-01',
    description: 'Verifying metric recovery',
    details: 'RSS slope returned to 0.2 MB/min',
    duration: 15000,
    traceId: 'trace-memory-leak-1',
  },
  {
    id: 'action-3',
    timestamp: now - 240000,
    type: 'completed',
    agentId: 'agent-2',
    agentName: 'EventProcessor-02',
    description: 'Event loop stall detected',
    details: 'Loop lag spike: 245ms',
    duration: 5000,
    traceId: 'trace-cpu-stall-1',
  },
  {
    id: 'action-4',
    timestamp: now - 235000,
    type: 'completed',
    agentId: 'agent-2',
    agentName: 'EventProcessor-02',
    description: 'Analyzing span self-time',
    details: 'Correlated blocking file I/O with lag spikes',
    duration: 8000,
    traceId: 'trace-cpu-stall-1',
  },
  {
    id: 'action-5',
    timestamp: now - 227000,
    type: 'completed',
    agentId: 'agent-2',
    agentName: 'EventProcessor-02',
    description: 'Fix applied',
    details: 'Moved file operations to executor pool',
    duration: 12000,
    traceId: 'trace-cpu-stall-1',
  },
  {
    id: 'action-6',
    timestamp: now - 120000,
    type: 'analyzing',
    agentId: 'agent-3',
    agentName: 'QueryEngine-03',
    description: 'Memory growth trend detected',
    details: 'RSS slope: 2.1 MB/min over 10 minutes',
    traceId: 'trace-memory-growth-1',
  },
  {
    id: 'action-7',
    timestamp: now - 60000,
    type: 'proposing',
    agentId: 'agent-3',
    agentName: 'QueryEngine-03',
    description: 'Proposing fix',
    details: 'Add TTL-based cache eviction',
    traceId: 'trace-memory-growth-1',
  },
];

export const mockSentinelState: SentinelState = {
  currentState: 'proposing',
  activeAgent: 'agent-3',
  transitions: [
    {
      fromState: 'completed',
      toState: 'detecting',
      timestamp: now - 120000,
      triggeredBy: 'agent-3',
    },
    {
      fromState: 'detecting',
      toState: 'analyzing',
      timestamp: now - 115000,
      triggeredBy: 'agent-3',
    },
    {
      fromState: 'analyzing',
      toState: 'proposing',
      timestamp: now - 60000,
      triggeredBy: 'agent-3',
    },
  ],
  lastUpdated: now,
};

export const mockSentinelPlan: SentinelPlan = {
  current: 'Analyzing QueryEngine-03 memory pattern',
  steps: [
    { step: 'Collect RSS trajectory data', status: 'completed' },
    { step: 'Correlate with span attributes', status: 'completed' },
    { step: 'Identify unbounded growth source', status: 'completed' },
    { step: 'Generate fix proposal', status: 'active' },
    { step: 'Present to user for approval', status: 'pending' },
    { step: 'Apply fix and monitor', status: 'pending' },
  ],
};

export const mockProposedChanges: ProposedChange[] = [
  {
    id: 'proposed-1',
    timestamp: now - 60000,
    agentId: 'agent-3',
    agentName: 'QueryEngine-03',
    issue: 'Unbounded cache growth',
    severity: 'warning',
    proposedFix: 'Add TTL-based eviction with Redis EXPIRE',
    code: {
      file: 'src/query/cache.py',
      before: `def cache_result(self, key, result):
    self.redis.set(key, result)`,
      after: `def cache_result(self, key, result):
    self.redis.setex(
        key,
        timedelta(minutes=30),
        result
    )`,
      line: 156,
    },
    autoApproved: false,
  },
];
