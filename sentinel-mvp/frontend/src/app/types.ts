export type MetricType = 'memory' | 'cpu';

export interface MetricDataPoint {
  timestamp: number;
  value: number;
}

export interface Agent {
  id: string;
  name: string;
  status: 'healthy' | 'warning' | 'critical' | 'recovering';
  metrics: {
    memory: MetricDataPoint[];
    cpu: MetricDataPoint[];
  };
}

export interface Intervention {
  id: string;
  timestamp: number;
  agentId: string;
  agentName: string;
  type: MetricType;
  severity: 'warning' | 'critical';
  issue: string;
  rootCause: string;
  proposedFix: string;
  status: 'detected' | 'proposed' | 'applied' | 'verified';
  code?: {
    file: string;
    before: string;
    after: string;
    line: number;
  };
  metricsBefore: number;
  metricsAfter?: number;
}

export type TimeScale = '5m' | '15m' | '1h' | '6h' | '24h';
