export type ActionType = 'detecting' | 'analyzing' | 'proposing' | 'applying' | 'verifying' | 'completed';

export interface SentinelAction {
  id: string;
  timestamp: number;
  type: ActionType;
  agentId: string;
  agentName: string;
  description: string;
  details?: string;
  duration?: number;
  traceId?: string;
}

export interface StateTransition {
  fromState: ActionType;
  toState: ActionType;
  timestamp: number;
  triggeredBy: string;
}

export interface SentinelState {
  currentState: ActionType;
  activeAgent: string | null;
  transitions: StateTransition[];
  lastUpdated: number;
}

export interface SentinelPlan {
  current: string;
  steps: {
    step: string;
    status: 'pending' | 'active' | 'completed';
  }[];
}

export interface ProposedChange {
  id: string;
  timestamp: number;
  agentId: string;
  agentName: string;
  issue: string;
  severity: 'warning' | 'critical';
  proposedFix: string;
  // Real diagnostician output from the backend (no code diff is produced).
  diagnosis?: string;
  rootCause?: string;
  blamedOp?: string | null;
  // Optional code diff; the backend does not produce one, so it may be absent.
  code?: {
    file: string;
    before: string;
    after: string;
    line: number;
  };
  autoApproved: boolean;
}
