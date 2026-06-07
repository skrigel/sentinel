/**
 * Wire types for the Sentinel backend's `graph` orchestrator.
 *
 * These mirror the JSON shapes emitted by backend/graph (IncidentState, broadcast
 * via /api/events and read via /api/incident) and backend/main.py. Field names and
 * value strings are the contract — keep them in sync with backend/graph/state.py,
 * backend/graph/nodes.py, and backend/agents/*.
 */

/** Every `status` string a graph node can set (backend/graph/nodes.py). */
export type IncidentStatus =
  | 'DETECTED'
  | 'TRIAGING'
  | 'INVESTIGATING'
  | 'NEEDS_MORE_EVIDENCE'
  | 'CLASSIFYING_CAUSE'
  | 'LOOKING_UP_PRIOR_FIXES'
  | 'PLANNING_FIX'
  | 'CHECKING_DIAGNOSIS'
  | 'TESTING_FIX'
  | 'AWAITING_APPROVAL'
  | 'APPLYING_FIX'
  | 'VERIFYING_RECOVERY'
  | 'RESOLVED'
  | 'REVERTING'
  | 'REPORT_UNRESOLVED'
  | 'IDLE';

/** Attributor evidence block (backend/agents/attributor.py). */
export interface AttributionEvidence {
  cumulative_bytes?: number;
  invocations?: number;
  per_call_avg?: number;
  total_rss_growth?: number;
  pct_of_growth_explained?: number;
  // evidence[] may also contain free-form notes: {type, value}
  type?: string;
  value?: string;
}

/** Detector anomaly (backend/agents/detector.py). */
export interface Anomaly {
  type: string;
  start_ts: number; // seconds
  severity: 'HIGH' | 'MEDIUM';
  slope: number; // bytes/sec
  r2: number;
  forced?: boolean;
}

/** A proposed fix — either an LLM diagnosis or a cache/memory recall. */
export interface ProposedFix {
  source: 'llm' | 'cache' | 'memory' | string;
  // LLM diagnosis fields (backend/agents/diagnostician.py)
  diagnosis?: string;
  root_cause?: string;
  fix_strategy?: string;
  confidence?: 'high' | 'medium' | 'low' | 'failed' | string;
  agent_id?: string;
  agent_name?: string;
  entry_point?: string;
  blamed_op?: string;
  evidence?: AttributionEvidence;
  eval?: {
    accuracy: number | null;
    mentioned_correct_op: boolean | null;
    identified_cause: boolean | null;
    skipped?: string;
  };
  // cache/memory recall fields
  summary?: string;
  similarity?: number;
  // Concrete before/after diff for the scoped fix (diagnostician._fix_code_diff).
  code?: {
    file: string;
    before: string;
    after: string;
    line: number;
  } | null;
}

export interface SelfTestResult {
  tests_passed: boolean;
  rss_slope_before: number;
  rss_slope_after: number;
  confidence: string;
}

export interface Verification {
  slope_before: number;
  slope_after: number;
  reduction_pct: number;
  recovered: boolean;
}

/** The full incident document broadcast by backend/graph/broadcast.py. */
export interface IncidentDocument {
  incident_id?: string;
  status?: IncidentStatus;
  anomaly?: Anomaly;
  symptom_type?: string;
  blamed_op?: string | null;
  suspected_subcause?: string | null;
  confidence?: number;
  pct_explained?: number;
  evidence?: AttributionEvidence[];
  attempted_routes?: string[];
  rejected_routes?: string[];
  proposed_fix?: ProposedFix | null;
  diagnosis_grounded?: boolean;
  hallucination?: Record<string, unknown>;
  test_result?: SelfTestResult | null;
  verification?: Verification | null;
  next_action?: string | null;
  triage_rounds?: number;
  investigation_rounds?: number;
  fix_attempts?: number;
}

/** GET /api/incident */
export interface IncidentResponse {
  state: IncidentStatus;
  incident: IncidentDocument | null;
}

/** One RSS sample from GET /api/metrics (oldest-first). */
export interface RssSample {
  timestamp: number; // seconds
  rss: number; // bytes
}

/** One kernel process-stat sample from GET /api/procstat (oldest-first).
 *  Any field can be null when the OS read failed (utils/redis_client.py). */
export interface ProcstatSample {
  timestamp: number; // seconds
  uss: number | null; // unique set size, bytes
  cpu_pct: number | null; // process CPU %
  num_fds: number | null; // open file descriptors
  num_threads: number | null; // thread count
}

/** One uploaded/default monitor target from GET /api/agents. */
export interface AgentRecord {
  id: string;
  display_name: string;
  filename: string;
  entry_point: string;
  runtime_status?: 'running' | 'ready' | 'source_only' | string;
  runtime_message?: string;
  content_type?: string | null;
  source_path?: string | null;
  monitored: boolean;
  created_at: number;
  updated_at: number;
}

/** Per-agent RSS samples from GET /api/agents/metrics. */
export interface AgentMetricSeries {
  agent: AgentRecord;
  samples: RssSample[];
}

/** One per-node agent activity event from GET /api/timeline (oldest-first). */
export interface TimelineEvent {
  node: string;
  decision: string;
  reason: string;
  confidence: string | null;
  status: IncidentStatus | null;
  incident_id: string | null;
  timestamp: number; // seconds
}

/** POST /api/apply */
export interface ApplyResponse {
  status: 'done' | 'error';
  verification?: Verification | null;
  error?: string;
}
