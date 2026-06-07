import { Agent, Intervention, MetricDataPoint } from './types';

const generateMetricData = (
  points: number,
  baseValue: number,
  trend: 'stable' | 'rising' | 'spike' | 'recovery'
): MetricDataPoint[] => {
  const now = Date.now();
  const interval = 30000; // 30 seconds

  return Array.from({ length: points }, (_, i) => {
    let value = baseValue;

    if (trend === 'rising') {
      value = baseValue + (i * 2);
    } else if (trend === 'spike') {
      if (i < points / 2) {
        value = baseValue + (i * 4);
      } else {
        value = baseValue + (points / 2) * 4 - ((i - points / 2) * 3);
      }
    } else if (trend === 'recovery') {
      if (i < points * 0.6) {
        value = baseValue + (i * 3);
      } else {
        value = baseValue + (points * 0.6) * 3 - ((i - points * 0.6) * 8);
      }
    } else {
      value = baseValue + (Math.random() * 5 - 2.5);
    }

    return {
      timestamp: now - (points - i) * interval,
      value: Math.max(0, value),
    };
  });
};

export const mockAgents: Agent[] = [
  {
    id: 'agent-1',
    name: 'DataPipeline-01',
    status: 'recovering',
    metrics: {
      memory: generateMetricData(60, 250, 'recovery'),
      cpu: generateMetricData(60, 35, 'stable'),
    },
  },
  {
    id: 'agent-2',
    name: 'EventProcessor-02',
    status: 'healthy',
    metrics: {
      memory: generateMetricData(60, 180, 'stable'),
      cpu: generateMetricData(60, 22, 'stable'),
    },
  },
  {
    id: 'agent-3',
    name: 'QueryEngine-03',
    status: 'warning',
    metrics: {
      memory: generateMetricData(60, 300, 'rising'),
      cpu: generateMetricData(60, 45, 'stable'),
    },
  },
];

export const mockInterventions: Intervention[] = [
  {
    id: 'int-1',
    timestamp: Date.now() - 180000,
    agentId: 'agent-1',
    agentName: 'DataPipeline-01',
    type: 'memory',
    severity: 'critical',
    issue: 'Memory leak detected',
    rootCause: 'Unbounded message history in span attribute trajectory',
    proposedFix: 'Implement ring buffer with 1000-message cap + summarization',
    status: 'verified',
    code: {
      file: 'src/pipeline/processor.py',
      before: `class MessageProcessor:
    def __init__(self):
        self.history = []

    def process(self, message):
        self.history.append(message)
        return self.analyze(self.history)`,
      after: `class MessageProcessor:
    def __init__(self):
        self.history = deque(maxlen=1000)
        self.summarized_old = []

    def process(self, message):
        if len(self.history) >= 1000:
            self.summarized_old.append(
                self.summarize(list(self.history)[:100])
            )
        self.history.append(message)
        return self.analyze(self.history)`,
      line: 42,
    },
    metricsBefore: 847,
    metricsAfter: 312,
  },
  {
    id: 'int-2',
    timestamp: Date.now() - 3600000,
    agentId: 'agent-2',
    agentName: 'EventProcessor-02',
    type: 'cpu',
    severity: 'warning',
    issue: 'Event loop stall detected',
    rootCause: 'Blocking synchronous file I/O in async event handler',
    proposedFix: 'Move file operations to executor thread pool',
    status: 'verified',
    code: {
      file: 'src/events/handler.py',
      before: `async def handle_event(self, event):
    data = self.read_file(event.path)
    await self.process(data)`,
      after: `async def handle_event(self, event):
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None, self.read_file, event.path
    )
    await self.process(data)`,
      line: 78,
    },
    metricsBefore: 245,
    metricsAfter: 12,
  },
  {
    id: 'int-3',
    timestamp: Date.now() - 300000,
    agentId: 'agent-3',
    agentName: 'QueryEngine-03',
    type: 'memory',
    severity: 'warning',
    issue: 'Memory growth detected',
    rootCause: 'Cached query results not being evicted',
    proposedFix: 'Add TTL-based eviction with Redis EXPIRE',
    status: 'proposed',
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
    metricsBefore: 421,
  },
];
