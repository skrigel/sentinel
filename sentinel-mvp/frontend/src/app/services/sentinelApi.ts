import { ActionType, SentinelAction, SentinelPlan, SentinelState, ProposedChange } from '../sentinelTypes';
import { Agent, Intervention, MetricDataPoint } from '../types';
import {
  ApplyResponse,
  IncidentDocument,
  IncidentResponse,
  IncidentStatus,
  RssSample,
  TimelineEvent,
} from './backendTypes';

/**
 * Real Sentinel backend client (graph orchestrator).
 *
 * The dashboard's view models (SentinelState / SentinelAction / ProposedChange /
 * MetricDataPoint) are derived here from the backend's IncidentDocument so the
 * pages stay agnostic to the wire format. Polling stays in the existing usePolling
 * hook; this module only does fetch + normalization.
 */

const API_BASE: string =
  (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE ||
  'http://localhost:8000';

// Backend has one instrumented victim (the document-QA agent), not a fleet.
const VICTIM_AGENT_ID = 'victim';
const VICTIM_AGENT_NAME = 'Document-QA Agent';

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Status mapping: the backend's fine-grained graph status -> the dashboard's
// six-phase action timeline.
// ---------------------------------------------------------------------------

const PHASES: ActionType[] = [
  'detecting',
  'analyzing',
  'proposing',
  'applying',
  'verifying',
  'completed',
];

const STATUS_TO_PHASE: Record<IncidentStatus, ActionType> = {
  IDLE: 'detecting',
  DETECTED: 'detecting',
  TRIAGING: 'analyzing',
  INVESTIGATING: 'analyzing',
  NEEDS_MORE_EVIDENCE: 'analyzing',
  CLASSIFYING_CAUSE: 'analyzing',
  LOOKING_UP_PRIOR_FIXES: 'proposing',
  PLANNING_FIX: 'proposing',
  CHECKING_DIAGNOSIS: 'proposing',
  TESTING_FIX: 'proposing',
  AWAITING_APPROVAL: 'proposing',
  APPLYING_FIX: 'applying',
  VERIFYING_RECOVERY: 'verifying',
  RESOLVED: 'completed',
  // Failure terminals collapse to the final node; severity is surfaced elsewhere.
  REVERTING: 'verifying',
  REPORT_UNRESOLVED: 'completed',
};

function statusToPhase(status: IncidentStatus | undefined): ActionType {
  return STATUS_TO_PHASE[status ?? 'IDLE'] ?? 'detecting';
}

function phaseIndex(phase: ActionType): number {
  const i = PHASES.indexOf(phase);
  return i < 0 ? 0 : i;
}

function isFailureTerminal(status: IncidentStatus | undefined): boolean {
  return status === 'REVERTING' || status === 'REPORT_UNRESOLVED';
}

// ---------------------------------------------------------------------------
// Adapters: IncidentDocument -> dashboard view models.
// ---------------------------------------------------------------------------

// Each graph node maps to a timeline phase (for the dot color / state filter)
// and a human-readable agent name (backend/graph/nodes.py).
const NODE_TO_PHASE: Record<string, ActionType> = {
  triage: 'detecting',
  memory_investigate: 'analyzing',
  evidence_collector: 'analyzing',
  classify_cause: 'analyzing',
  retrieve_fix: 'proposing',
  plan_fix: 'proposing',
  check_diagnosis: 'proposing',
  self_test: 'proposing',
  await_approval: 'proposing',
  apply: 'applying',
  verify: 'verifying',
  store_learning: 'completed',
  rollback: 'verifying',
  report_unresolved: 'completed',
};

const NODE_LABEL: Record<string, string> = {
  triage: 'Triage',
  memory_investigate: 'Attribution',
  evidence_collector: 'Evidence collector',
  classify_cause: 'Cause classifier',
  retrieve_fix: 'Fix retrieval',
  plan_fix: 'Diagnostician',
  check_diagnosis: 'Hallucination gate',
  self_test: 'Self-test',
  await_approval: 'Approval gate',
  apply: 'Apply',
  verify: 'Verifier',
  store_learning: 'Memory writer',
  rollback: 'Rollback',
  report_unresolved: 'Report',
};

/** Real per-node agent activity (GET /api/timeline) -> timeline actions. */
export function timelineToActions(events: TimelineEvent[]): SentinelAction[] {
  return events.map((e, i) => {
    const label = NODE_LABEL[e.node] ?? e.node;
    return {
      id: `${e.incident_id ?? 'inc'}-${i}-${e.node}`,
      timestamp: e.timestamp * 1000,
      type: NODE_TO_PHASE[e.node] ?? 'analyzing',
      agentId: VICTIM_AGENT_ID,
      agentName: label,
      description: `${label}: ${e.decision}`,
      details: e.reason,
    } satisfies SentinelAction;
  });
}

export function buildSentinelState(inc: IncidentDocument): SentinelState {
  const current = statusToPhase(inc.status);
  return {
    currentState: current,
    activeAgent: inc.status && inc.status !== 'IDLE' ? VICTIM_AGENT_ID : null,
    transitions: [],
    lastUpdated: Date.now(),
  };
}

const PLAN_STEPS: { phase: ActionType; step: string }[] = [
  { phase: 'detecting', step: 'Detect sustained RSS slope anomaly' },
  { phase: 'analyzing', step: 'Attribute growth to the offending op' },
  { phase: 'proposing', step: 'Diagnose root cause and plan a fix' },
  { phase: 'proposing', step: 'Self-test the fix; await approval' },
  { phase: 'applying', step: 'Apply fix (flip victim to fixed mode)' },
  { phase: 'verifying', step: 'Verify recovery on the live RSS slope' },
];

export function buildSentinelPlan(inc: IncidentDocument | null): SentinelPlan {
  const current = inc ? statusToPhase(inc.status) : 'detecting';
  const currentIdx = phaseIndex(current);
  const awaiting = inc?.status === 'AWAITING_APPROVAL';
  const resolved = inc?.status === 'RESOLVED';

  return {
    current: planHeadline(inc),
    steps: PLAN_STEPS.map((s, i) => {
      const stepIdx = phaseIndex(s.phase);
      let status: 'pending' | 'active' | 'completed';
      if (resolved) status = 'completed';
      else if (stepIdx < currentIdx) status = 'completed';
      else if (stepIdx > currentIdx) status = 'pending';
      // The two 'proposing' steps: the second ("await approval") only goes active
      // once the backend is actually AWAITING_APPROVAL.
      else if (s.step.includes('await approval')) status = awaiting ? 'active' : 'pending';
      else status = 'active';
      return { step: s.step, status };
    }),
  };
}

function planHeadline(inc: IncidentDocument | null): string {
  if (!inc || !inc.status || inc.status === 'IDLE') return 'Monitoring victim — no active incident';
  if (inc.status === 'RESOLVED') return 'Incident resolved — recovery confirmed';
  if (isFailureTerminal(inc.status)) return inc.next_action || 'Incident unresolved — manual review needed';
  const op = inc.blamed_op ? ` in ${inc.blamed_op}` : '';
  return `Handling ${inc.symptom_type ?? 'anomaly'}${op}`;
}

function severityFromAnomaly(inc: IncidentDocument): 'warning' | 'critical' {
  return inc.anomaly?.severity === 'HIGH' ? 'critical' : 'warning';
}

/** A pending approval card, present only while the backend awaits human approval. */
export function buildProposedChanges(inc: IncidentDocument | null): ProposedChange[] {
  if (!inc || inc.status !== 'AWAITING_APPROVAL' || !inc.proposed_fix) return [];
  const fix = inc.proposed_fix;
  return [
    {
      id: inc.incident_id ?? 'pending',
      timestamp: (inc.anomaly?.start_ts ?? Date.now() / 1000) * 1000,
      agentId: VICTIM_AGENT_ID,
      agentName: VICTIM_AGENT_NAME,
      issue: inc.suspected_subcause || inc.symptom_type || 'anomaly',
      severity: severityFromAnomaly(inc),
      proposedFix: fix.fix_strategy || fix.summary || 'Apply pre-written fixed mode',
      diagnosis: fix.diagnosis,
      rootCause: fix.root_cause,
      blamedOp: inc.blamed_op ?? fix.blamed_op,
      code: fix.code ?? undefined,
      autoApproved: false,
    },
  ];
}

// ---------------------------------------------------------------------------
// Dashboard adapters: the single instrumented victim as one Agent + intervention.
// ---------------------------------------------------------------------------

function agentStatus(inc: IncidentDocument | null): Agent['status'] {
  if (!inc || !inc.status || inc.status === 'IDLE' || inc.status === 'RESOLVED') return 'healthy';
  if (inc.status === 'APPLYING_FIX' || inc.status === 'VERIFYING_RECOVERY') return 'recovering';
  if (isFailureTerminal(inc.status)) return 'critical';
  return inc.anomaly?.severity === 'HIGH' ? 'critical' : 'warning';
}

/** The victim as the dashboard's single Agent, with real RSS memory series. */
export function buildAgent(inc: IncidentDocument | null, memory: MetricDataPoint[]): Agent {
  return {
    id: VICTIM_AGENT_ID,
    name: VICTIM_AGENT_NAME,
    status: agentStatus(inc),
    // The backend exposes RSS only; CPU/loop-lag are not on a REST endpoint yet.
    metrics: { memory, cpu: [] },
  };
}

const PHASE_TO_INTERVENTION_STATUS: Record<ActionType, Intervention['status']> = {
  detecting: 'detected',
  analyzing: 'detected',
  proposing: 'proposed',
  applying: 'applied',
  verifying: 'verified',
  completed: 'verified',
};

/** Map one incident document to an Intervention card view model. */
export function incidentToIntervention(inc: IncidentDocument): Intervention {
  const fix = inc.proposed_fix;
  const v = inc.verification;
  const phase = statusToPhase(inc.status);
  return {
    id: inc.incident_id ?? 'inc',
    timestamp: (inc.anomaly?.start_ts ?? Date.now() / 1000) * 1000,
    agentId: VICTIM_AGENT_ID,
    agentName: VICTIM_AGENT_NAME,
    type: 'memory',
    severity: severityFromAnomaly(inc),
    issue: inc.suspected_subcause || inc.symptom_type || 'anomaly',
    rootCause: fix?.root_cause || fix?.diagnosis || 'Attributing root cause…',
    proposedFix: fix?.fix_strategy || fix?.summary || 'Pending diagnosis',
    status: PHASE_TO_INTERVENTION_STATUS[phase],
    // Carry the diff through apply/verify/resolved so it stays viewable after
    // the victim is flipped to fixed mode.
    code: fix?.code ?? undefined,
    metricsBefore: inc.anomaly ? +(inc.anomaly.slope / 1024 / 1024).toFixed(2) : 0,
    metricsAfter: v ? +(v.slope_after / 1024 / 1024).toFixed(2) : undefined,
  };
}

/** True while an active, unresolved incident warrants the issue toast. */
export function hasActiveIssue(inc: IncidentDocument | null): boolean {
  return (
    !!inc &&
    !!inc.status &&
    inc.status !== 'IDLE' &&
    inc.status !== 'RESOLVED'
  );
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Current incident document, or null when IDLE / no incident yet. */
export async function fetchIncident(): Promise<IncidentDocument | null> {
  const { incident, state } = await getJson<IncidentResponse>('/api/incident');
  if (!incident || Object.keys(incident).length === 0) {
    return state && state !== 'IDLE' ? { status: state } : null;
  }
  return { status: state, ...incident };
}

/** Real per-node agent activity log for the current incident, oldest-first. */
export async function fetchTimeline(): Promise<SentinelAction[]> {
  const events = await getJson<TimelineEvent[]>('/api/timeline');
  return timelineToActions(events);
}

/** Durable, cross-incident agent activity (SQLite-backed), oldest-first. */
export async function fetchActivity(limit = 300): Promise<SentinelAction[]> {
  const events = await getJson<TimelineEvent[]>(`/api/activity?limit=${limit}`);
  return timelineToActions(events);
}

/** Durable per-incident interventions (newest-first) for the Agent Activity feed. */
export async function fetchInterventions(limit = 50): Promise<Intervention[]> {
  const docs = await getJson<IncidentDocument[]>(`/api/interventions?limit=${limit}`);
  return docs
    .filter((d) => d.status && d.status !== 'IDLE')
    .map(incidentToIntervention);
}

/** RSS memory series (MB) for the live chart, oldest-first. */
export async function fetchMemoryMetrics(): Promise<MetricDataPoint[]> {
  const samples = await getJson<RssSample[]>('/api/metrics');
  return samples.map((s) => ({
    timestamp: s.timestamp * 1000,
    value: s.rss / 1024 / 1024,
  }));
}

/** Approve and apply the fix (flag-flip + live verification on the backend). */
export async function applyFix(): Promise<ApplyResponse> {
  const res = await fetch(`${API_BASE}/api/apply`, { method: 'POST' });
  return res.json() as Promise<ApplyResponse>;
}

/** Demo-safety override: force the detector to fire an anomaly. */
export async function forceDetection(): Promise<void> {
  await fetch(`${API_BASE}/api/force-detection`, { method: 'POST' });
}

/** Reset the incident + victim back to buggy mode. */
export async function resetIncident(): Promise<void> {
  await fetch(`${API_BASE}/api/reset`, { method: 'POST' });
}

/** Whether the backend auto-applies fixes (overrides the manual-approval gate). */
export async function fetchAutoApprove(): Promise<boolean> {
  try {
    const { auto_approve } = await getJson<{ auto_approve: boolean }>('/api/settings');
    return !!auto_approve;
  } catch {
    return false;
  }
}

export async function setAutoApprove(value: boolean): Promise<void> {
  await fetch(`${API_BASE}/api/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auto_approve: value }),
  });
}
