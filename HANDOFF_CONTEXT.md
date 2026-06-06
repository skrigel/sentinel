# Sentinel Handoff Context

Date: June 6, 2026

This file summarizes the current project state and the ideas discussed for turning the MVP into a stronger hackathon demo. It is meant as context for a new chat or teammate.

## Project

Sentinel is a self-healing agent monitor for WeaveHacks. The current MVP watches a victim Python agent, detects a memory leak, attributes it to the exact operation, asks an LLM for diagnosis, lets a human approve the fix, flips the victim into fixed mode, and verifies recovery on a live graph.

Core thesis:

```text
The watchdog that watches the watchdogs: observe -> reason -> act -> verify.
```

## Current Repo Layout

Important folders:

```text
weavehacks-secret-project/
  CLAUDE.md
  sentinel_implementation_plan.md
  docs/
  sentinel-mvp/
    docker-compose.yml
    backend/
    frontend/
    victim/
```

Important source files:

```text
sentinel-mvp/victim/main.py
sentinel-mvp/victim/ops.py
sentinel-mvp/victim/instrument.py
sentinel-mvp/victim/collector.py
sentinel-mvp/backend/main.py
sentinel-mvp/backend/agents/detector.py
sentinel-mvp/backend/agents/attributor.py
sentinel-mvp/backend/agents/diagnostician.py
sentinel-mvp/backend/agents/supervisor.py
sentinel-mvp/frontend/app/page.tsx
```

## Current MVP Workflow

The current implementation is a Phase A memory-leak demo.

Runtime flow:

```text
Redis + victim + backend start with docker compose
frontend runs separately with Next.js dev server
victim starts in buggy mode
victim loop runs initialize -> process_batch -> cleanup
instrumentation records per-op tracemalloc deltas to Redis and Weave
collector records RSS and loop-lag to Redis streams
detector watches RSS slope
attributor ranks Redis attribution zset
diagnostician asks GPT-4o for grounded diagnosis
supervisor transitions incident state and streams updates to frontend
human clicks Apply Fix
supervisor sets Redis victim:mode = fixed
victim exits and Docker restarts it in fixed mode
supervisor verifies RSS slope reduction
frontend shows recovery stats
```

Current state machine:

```text
IDLE -> DETECTED -> DIAGNOSED -> AWAITING_APPROVAL -> APPLYING -> RESOLVED | FAILED
```

Current backend endpoints:

```text
GET  /api/health
GET  /api/metrics
GET  /api/incident
GET  /api/events
POST /api/apply
POST /api/force-detection
POST /api/reset
```

## Current Demo Story

1. Victim starts in buggy mode.
2. `process_batch` appends a new large embedding batch to `conversation_history` every loop.
3. RSS rises on the frontend graph.
4. Detector fires when RSS slope is high and linear.
5. Attributor blames `process_batch` using cumulative `attrib:mem` evidence.
6. Diagnostician reads the blamed source and produces structured diagnosis.
7. UI shows alert, evidence, diagnosis, Weave eval result, and Apply Fix button.
8. Human approves.
9. Victim restarts in fixed mode.
10. Fixed mode keeps only a sliding window of the last 8 batches.
11. RSS slope flattens.
12. UI shows recovery confirmation.

## Current Strengths

- Real process isolation via Docker.
- Redis blackboard for streams, state, attribution, and pub/sub.
- Causal attribution instead of simple correlation.
- Weave instrumentation hooks exist for victim and backend agents.
- The only LLM call is the Diagnostician, keeping orchestration deterministic.
- Human approval makes the demo safer and easier to pace.
- Force Detection button exists as a demo safety override.

## Current Gaps / Likely Blockers

- Frontend components import `../lib/api`, but `sentinel-mvp/frontend/lib/api.ts` was not present in the workspace listing. Add this first if the frontend build fails.
- CPU/event-loop hot-path beat is not implemented yet; loop-lag stream exists but detection/routing does not.
- Shadow replay is documented as Phase B but not implemented.
- CopilotKit chat integration is not implemented and should stay low priority.
- SQLite durable incident/trend storage is not implemented yet.
- Redis health/usage monitoring is not surfaced yet.
- Weave trace links are not surfaced in the frontend yet.
- If OpenAI fails, the current fallback proposal is not demo-polished. Add a clean canned fallback for the known memory leak.

## Best Immediate Hackathon Improvements

Prioritize by impact per hour:

1. Fix/add frontend API helper if missing.
2. Add agent activity timeline showing each state and decision.
3. Add Demo Control panel with Reset, Force Detection, victim mode, backend health, Redis health, latest RSS slope.
4. Add polished fallback diagnosis for the known memory leak.
5. Add Weave trace/eval links or badges in the UI.
6. Add Redis fix memory/cache for known problem types.
7. Add SQLite incident history and trends.
8. Add self-test gate before Apply.
9. Stretch: simplified shadow verification.
10. Stretch: CPU/event-loop hot-path route.

## Better Architecture Idea

The better approach is not a linear agent pipeline. It should become a stateful diagnostic graph with conditional routing and loops.

Recommended framework: LangGraph.

Why LangGraph:

- Explicit states.
- Conditional edges.
- Loops and retries.
- Human approval gates.
- Streaming state updates.
- Works well with Redis/SQLite persistence.
- Better fit than CrewAI/AutoGen for incident response workflows.

Improved thesis:

```text
Sentinel does not run agents in a fixed chain. It routes incidents through a graph of specialists, loops back when evidence is weak, retrieves prior fixes from Redis, tests candidate repairs, and only applies them after confidence is high.
```

## Proposed Agent Graph

Recommended MVP+ flow:

```text
OBSERVE
-> DETECT
-> TRIAGE_ROUTER
-> INVESTIGATE
-> CLASSIFY_SUBCAUSE
-> RETRIEVE_SIMILAR_FIXES_FROM_REDIS
-> PLAN_FIX
-> SELF_TEST
-> AWAIT_APPROVAL
-> APPLY
-> VERIFY
-> STORE_LEARNING
-> REPORT
```

Important conditional loops:

```text
INVESTIGATE -> EVIDENCE_COLLECTOR -> INVESTIGATE
INVESTIGATE -> TRIAGE_ROUTER
CLASSIFY_SUBCAUSE -> EVIDENCE_COLLECTOR
SELF_TEST -> PLAN_FIX
VERIFY -> TRIAGE_ROUTER
VERIFY -> OBSERVE_MORE
```

Example graph route:

```text
OBSERVE
  ↓
DETECT
  ↓
TRIAGE_ROUTER
  ├─ memory_leak -> MEMORY_INVESTIGATOR
  ├─ cpu_hotpath -> CPU_INVESTIGATOR
  ├─ event_loop_lag -> ASYNC_INVESTIGATOR
  ├─ redis_pressure -> REDIS_INVESTIGATOR
  └─ unknown -> EVIDENCE_COLLECTOR

MEMORY_INVESTIGATOR
  ├─ enough_evidence -> CAUSE_CLASSIFIER
  ├─ not_enough_evidence -> EVIDENCE_COLLECTOR
  ├─ contradictory_evidence -> TRIAGE_ROUTER
  └─ unknown_subcause -> DEEP_MEMORY_INVESTIGATOR

CAUSE_CLASSIFIER
  ├─ known_subcause -> REDIS_FIX_MEMORY
  ├─ unknown_subcause -> INVESTIGATOR
  ├─ low_confidence -> EVIDENCE_COLLECTOR
  └─ high_confidence -> FIX_PLANNER

REDIS_FIX_MEMORY
  ├─ similar_fix_found -> FIX_PLANNER
  └─ no_match -> FIX_PLANNER_WITH_LLM

FIX_PLANNER
  ├─ safe_known_fix -> SELF_TEST
  ├─ risky_fix -> HUMAN_REVIEW
  ├─ no_fix_possible -> REPORT_UNRESOLVED
  └─ need_more_context -> INVESTIGATOR

SELF_TEST
  ├─ tests_pass -> AWAIT_APPROVAL
  ├─ tests_fail -> FIX_PLANNER
  └─ inconclusive -> INVESTIGATOR

APPLY_FIX
  ↓
VERIFY_RECOVERY
  ├─ recovered -> STORE_LEARNING -> RESOLVED
  ├─ not_recovered -> ROLLBACK -> TRIAGE_ROUTER
  └─ unclear -> OBSERVE_MORE
```

## Proposed States

Use states like:

```text
OBSERVING
DETECTING
TRIAGING
INVESTIGATING
CLASSIFYING_CAUSE
LOOKING_UP_PRIOR_FIXES
PLANNING_FIX
PROPOSING_FIX
TESTING_FIX
AWAITING_APPROVAL
APPLYING_FIX
VERIFYING_RECOVERY
REPORTING
RESOLVED
FAILED
NEEDS_MORE_EVIDENCE
OBSERVE_MORE
REPORT_UNRESOLVED
```

## Proposed Agent Roles

Observer Agent:

- Watches RSS, CPU, loop lag, Redis latency, stream lengths, error rate.
- Mostly deterministic.

Detector Agent:

- Converts metrics into incident candidates.
- Example: RSS slope rising 1.8 MB/s with R2 0.93.

Triage Router:

- Routes incident to the right specialist.
- Could use deterministic rules first, LLM fallback second.

Memory Investigator:

- Reads `attrib:mem`, `metrics:rss`, source snippets, traces, and Redis history.
- Decides if evidence is strong enough or if it needs another route.

CPU / Async Investigator:

- Future route for loop-lag or CPU hot-path problems.
- Looks for sync blocking, CPU-heavy functions, or slow ops.

Redis Investigator:

- Checks Redis memory, stream lengths, pub/sub health, key growth, and latency.
- Useful because Redis is both app memory and orchestration substrate.

Cause Classifier:

- Maps symptoms to subcauses, such as:
  - `unbounded_collection`
  - `cache_without_ttl`
  - `large_object_retention`
  - `native_memory_growth`
  - `event_loop_blocking`
  - `sync_io_in_async_loop`
  - `redis_queue_backlog`
  - `unknown`

Redis Fix Memory Agent:

- Queries Redis for prior similar incidents and cached fixes.
- Example keys:

```text
fix_cache:memory_leak:unbounded_collection:process_batch
fix_cache:cpu_hotpath:sync_json_dumps
incident_context:{incident_id}
```

Fix Planner:

- Produces a fix plan:
  - suspected cause
  - proposed change
  - risk
  - expected impact
  - test plan
  - rollback plan

Patch / Apply Agent:

- For MVP, keep the safe flag-flip to `fixed` mode.
- Later, generate patches and show diffs in UI.

Self-Test Agent:

- Runs tests before approval/apply.
- Could run unit tests, targeted simulation, lint/typecheck, or replay.
- Emits structured output:

```json
{
  "tests_passed": true,
  "rss_slope_before": 1840000,
  "rss_slope_after": 120000,
  "confidence": "high"
}
```

Verifier Agent:

- Deterministically checks live recovery after apply.

Reporter Agent:

- Writes human-readable summary and stores incident learning.

## Shared Incident State

Each node should update a shared state object and return a next route.

Suggested shape:

```python
IncidentState = {
    "incident_id": str,
    "status": str,
    "symptom_type": "memory_leak | cpu_hotpath | event_loop_lag | redis_pressure | unknown",
    "suspected_subcause": str | None,
    "confidence": float,
    "evidence": list,
    "attempted_routes": list,
    "rejected_routes": list,
    "proposed_fix": dict | None,
    "test_result": dict | None,
    "verification": dict | None,
    "next_action": str | None,
}
```

Important fields for avoiding loops and explaining decisions:

```text
confidence
evidence
attempted_routes
rejected_routes
next_action
```

Each node should produce structured output like:

```json
{
  "node": "memory_investigator",
  "status": "complete",
  "confidence": 0.42,
  "summary": "Python attribution is weak; process_batch explains only 12% of RSS growth.",
  "evidence_added": [
    {
      "type": "attribution",
      "key": "attrib:mem",
      "value": "process_batch: 12%"
    }
  ],
  "decision": "back_to_triage",
  "reason": "RSS is rising but Python retained-memory attribution is too low."
}
```

## Conditional Routing Pattern

Example logic:

```python
def route_after_memory_investigation(state):
    pct = state["latest_evidence"].get("pct_explained", 0)

    if pct > 60:
        return "classify_cause"
    if pct < 20:
        return "back_to_triage"
    return "collect_more_evidence"
```

In LangGraph:

```python
graph.add_conditional_edges(
    "memory_investigator",
    route_after_memory_investigation,
    {
        "classify_cause": "cause_classifier",
        "collect_more_evidence": "evidence_collector",
        "back_to_triage": "triage_router",
        "deep_memory": "deep_memory_investigator",
    },
)
```

## Loop Budgets

Avoid infinite loops with budgets:

```text
max_triage_rounds = 3
max_investigation_rounds = 4
max_fix_attempts = 2
max_observe_more_seconds = 60
```

If exhausted, transition to `REPORT_UNRESOLVED` with useful reasoning.

Example unresolved summary:

```text
Could not resolve automatically. Best evidence points to native memory growth. Python tracemalloc explains only 6% of RSS increase. Recommend checking C-extension allocations.
```

## Redis vs SQLite

Use Redis for fast operational memory:

- current incident state
- live metric streams
- pub/sub updates
- attribution zsets
- short-term context
- cached fixes
- prior incident snippets for retrieval
- Redis health snapshots

Use SQLite for durable analytics:

- incidents
- metric rollups
- agent step timings
- fix success/failure
- trend summaries
- recovery time history
- confidence vs outcome

Suggested SQLite tables:

```sql
CREATE TABLE incidents (
  id TEXT PRIMARY KEY,
  type TEXT,
  subcause TEXT,
  blamed_op TEXT,
  started_at REAL,
  resolved_at REAL,
  status TEXT
);

CREATE TABLE agent_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT,
  agent_name TEXT,
  state TEXT,
  started_at REAL,
  ended_at REAL,
  confidence REAL,
  decision TEXT,
  reason TEXT
);

CREATE TABLE metric_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT,
  metric TEXT,
  before_value REAL,
  after_value REAL
);

CREATE TABLE fixes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT,
  fix_type TEXT,
  summary TEXT,
  tests_passed INTEGER,
  verified INTEGER
);

CREATE TABLE redis_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp REAL,
  used_memory INTEGER,
  ops_per_sec REAL,
  stream_lengths TEXT
);
```

## Weave Strategy

Unique story: use Weave to monitor Sentinel's own agents, not only the victim.

Wrap every agent/node as a Weave op:

```text
sentinel.observe
sentinel.detect_anomaly
sentinel.triage_incident
sentinel.memory_investigate
sentinel.retrieve_prior_fixes
sentinel.classify_cause
sentinel.plan_fix
sentinel.self_test
sentinel.verify_recovery
sentinel.report
```

For each agent step, log:

- input evidence
- Redis keys touched
- retrieved Redis context
- prompt and output for LLM-backed steps
- route decision
- confidence
- latency
- token usage
- test result
- metric impact
- final state

Weave eval ideas:

- Did the classifier choose the right incident type?
- Did the subcause match known ground truth?
- Did the fix plan address the actual cause?
- Did the self-test pass before apply?
- Did live recovery happen?
- Did Redis memory/cache usage stay healthy?

Pitch line:

```text
Sentinel monitors agents, and Weave monitors Sentinel's agents.
```

## Redis Monitoring Ideas

Because Redis is both orchestration and memory, monitor it visibly.

Track:

- `INFO memory` used memory
- `INFO stats` ops/sec
- stream lengths for `metrics:rss`, `metrics:looplag`
- pub/sub event counts
- cache hit/miss for fix memory
- slow Redis operations if possible

UI panel:

```text
Redis Health
- connected: yes
- used memory: 12.4 MB
- metric stream length: 317
- fix-memory hit: yes
- pub/sub events: 8
```

## UI Improvements

Best panels to add:

1. Agent Timeline
   - Shows each node lighting up with status, duration, decision, and confidence.

2. Evidence Board
   - RSS slope, blamed op, attribution percent, source snippet, suspected subcause.

3. Memory Recall
   - Shows Redis found prior similar incidents or cached fix patterns.

4. Fix Preview
   - Fix strategy, risk level, expected impact, rollback plan.

5. Self-Test Result
   - Tests passed, simulated/replayed slope improvement, Redis healthy, confidence.

6. Recovery Stats
   - Slope before, slope after, percent improvement, time to recovery, stored learning.

7. Demo Control
   - Reset, Force Detection, current victim mode, backend health, Redis connected, latest RSS slope.

## Complexity Options

Option 1: Polish current pipeline

- Complexity: low.
- Usefulness: medium.
- Demo impact: medium.
- Add timeline, Redis fix cache, SQLite history, Weave spans.

Option 2: LangGraph around current agents

- Complexity: medium.
- Usefulness: high.
- Demo impact: high.
- Recommended approach.
- Keep current detector/attributor/diagnostician/supervisor logic, but route through a state graph.

Option 3: Full autonomous code patching

- Complexity: high.
- Usefulness: high but risky.
- Demo impact: very high if it works.
- Safer version: generate and display patch diff, but still apply via known fixed mode.

Option 4: Multi-incident production monitor

- Complexity: high.
- Usefulness: high.
- Demo impact: medium.
- Useful but less flashy than a clean self-healing flow.

## Recommended Build Order

Recommended order from here:

1. Add/fix `frontend/lib/api.ts` if missing.
2. Add Agent Timeline UI.
3. Add Redis health and Demo Control panel.
4. Add polished fallback diagnosis.
5. Add Weave trace/eval links or badges.
6. Add Redis fix memory cache.
7. Add SQLite incident history.
8. Add Self-Test Agent gate.
9. Wrap each agent step as a Weave op with structured decision logs.
10. Add LangGraph orchestration around current agents.
11. Stretch: simplified shadow verification.
12. Stretch: CPU/event-loop hot-path route.

## Suggested Pitch

Short version:

```text
Sentinel is a LangGraph-powered incident response agent for AI systems. It observes a running agent, detects failures from live metrics, routes investigation through specialist agents, retrieves prior fixes from Redis memory, validates candidate repairs with tests, applies only after human approval, verifies live recovery, stores learning in SQLite, and traces every decision in Weave.
```

Current MVP pitch:

```text
Sentinel watches an agent, detects a real memory leak from process RSS, causally attributes it to one operation, asks an LLM for a grounded diagnosis, lets a human approve, then verifies the system healed.
```

## Important Scope Advice

Do not abandon the current memory-leak MVP. Keep it as the reliable demo path.

The best upgrade is to make the existing path look and behave like conditional multi-agent orchestration. Add routing, memory, timeline, self-test, and tracing around the current successful core before attempting fully autonomous patch generation.

Highest-value hackathon story:

```text
observe -> detect -> route -> investigate -> recall prior fix -> plan -> self-test -> approve -> apply -> verify -> store learning
```
