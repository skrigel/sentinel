import { ActionType, SentinelAction, SentinelPlan, SentinelState, ProposedChange } from '../sentinelTypes';
import { Agent, Intervention, MetricDataPoint } from '../types';
import {
  ApplyResponse,
  IncidentDocument,
  IncidentResponse,
  IncidentStatus,
  RssSample,
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

export interface SentinelStateResponse {
  state: SentinelState;
  recentActions: SentinelAction[];
}

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

const PHASE_LABEL: Record<ActionType, string> = {
  detecting: 'Anomaly detected',
  analyzing: 'Attributing root cause',
  proposing: 'Proposing fix',
  applying: 'Applying fix',
  verifying: 'Verifying recovery',
  completed: 'Incident resolved',
};

function phaseDetail(phase: ActionType, inc: IncidentDocument): string | undefined {
  const ev = inc.evidence?.[inc.evidence.length - 1];
  switch (phase) {
    case 'detecting': {
      const a = inc.anomaly;
      if (!a) return undefined;
      return `${a.type} · slope ${(a.slope / 1024 / 1024).toFixed(2)} MB/s · ${a.severity}`;
    }
    case 'analyzing':
      if (inc.blamed_op) {
        const pct = inc.pct_explained ?? ev?.pct_of_growth_explained;
        return pct != null
          ? `${inc.blamed_op} explains ${pct.toFixed(0)}% of RSS growth`
          : `Blamed op: ${inc.blamed_op}`;
      }
      return undefined;
    case 'proposing':
      return inc.proposed_fix?.fix_strategy || inc.proposed_fix?.summary || undefined;
    case 'applying':
      return 'Flipped victim to fixed mode';
    case 'verifying': {
      const v = inc.verification;
      if (!v) return undefined;
      return `Slope ${(v.slope_after / 1024 / 1024).toFixed(2)} MB/s · ${v.reduction_pct.toFixed(0)}% reduction`;
    }
    case 'completed': {
      const v = inc.verification;
      if (isFailureTerminal(inc.status)) return inc.next_action || 'Recovery not confirmed';
      return v ? `Recovered: ${v.reduction_pct.toFixed(0)}% slope reduction` : undefined;
    }
  }
}

/** Build a timeline of the phases reached so far, timestamped off the anomaly. */
export function buildActions(inc: IncidentDocument): SentinelAction[] {
  const current = statusToPhase(inc.status);
  const currentIdx = phaseIndex(current);
  const baseMs = (inc.anomaly?.start_ts ?? Date.now() / 1000) * 1000;
  const STEP_MS = 3000;

  return PHASES.slice(0, currentIdx + 1).map((phase, i) => {
    const reached = i < currentIdx; // earlier phases are done
    return {
      id: `${inc.incident_id ?? 'inc'}-${phase}`,
      timestamp: baseMs + i * STEP_MS,
      // A completed earlier phase reads as 'completed'; the live phase keeps its own type.
      type: reached ? 'completed' : phase,
      agentId: VICTIM_AGENT_ID,
      agentName: VICTIM_AGENT_NAME,
      description: PHASE_LABEL[phase],
      details: phaseDetail(phase, inc),
      traceId: inc.incident_id,
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

/** Current incident as a single Intervention card (0 or 1), for the activity feed. */
export function buildInterventions(inc: IncidentDocument | null): Intervention[] {
  if (!inc || !inc.status || inc.status === 'IDLE') return [];
  const fix = inc.proposed_fix;
  const v = inc.verification;
  const phase = statusToPhase(inc.status);
  return [
    {
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
      metricsBefore: inc.anomaly ? +(inc.anomaly.slope / 1024 / 1024).toFixed(2) : 0,
      metricsAfter: v ? +(v.slope_after / 1024 / 1024).toFixed(2) : undefined,
    },
  ];
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

/** Keeps the existing usePolling contract used by SentinelStatus. */
export async function fetchSentinelState(): Promise<SentinelStateResponse> {
  const inc = await fetchIncident();
  if (!inc) {
    return {
      state: {
        currentState: 'detecting',
        activeAgent: null,
        transitions: [],
        lastUpdated: Date.now(),
      },
      recentActions: [],
    };
  }
  return { state: buildSentinelState(inc), recentActions: buildActions(inc) };
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
