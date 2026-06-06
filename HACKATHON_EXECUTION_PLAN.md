# Sentinel Hackathon Execution Plan

Date: June 6, 2026

This is the practical plan after merging the two architecture ideas:

1. Conditional multi-agent graph with routing, loops, Redis memory, SQLite trends, self-tests, and Weave traces.
2. Production-style orchestrator-worker system with deterministic transition table, Redis blackboard, stateless workers, and per-incident workflows.

## Decision

For the hackathon, do **not** fully rewrite around LangGraph yet.

Build the **orchestrator-worker skeleton** using the current FastAPI async backend, Redis blackboard, and existing worker modules. Make it look and behave like a state graph by adding explicit transitions, worker step records, UI timeline, Redis memory, and self-test gates.

This is easier, safer, and still gives the stronger architecture story.

Framework position:

```text
The architecture is engine-agnostic: deterministic transition table + stateless workers + Redis blackboard.
LangGraph is the natural next engine, but the MVP can implement the same graph directly in FastAPI/asyncio.
```

That lets the project sound mature without taking on a risky framework migration during the hackathon.

## Best Hackathon Story

```text
Sentinel is a self-healing incident-response engine for AI agents. It watches a live agent, detects a failure from process metrics, routes the incident through specialist workers, retrieves prior fix knowledge from Redis, validates a candidate fix with a self-test, asks for human approval, applies the fix, verifies live recovery, stores the learning, and traces every Sentinel worker in Weave.
```

Shorter demo line:

```text
Observe -> detect -> investigate -> recall -> plan -> self-test -> approve -> apply -> verify -> learn.
```

## What To Build Now

Build the minimum version that proves the better architecture while keeping the current memory-leak path reliable.

### Phase 1: Make Current Demo Work Reliably

Must finish first.

1. Add missing frontend API helper if needed: `sentinel-mvp/frontend/lib/api.ts`.
2. Run backend/victim/Redis with Docker Compose.
3. Run frontend.
4. Confirm happy path:
   - RSS rises.
   - Detection fires.
   - Attribution blames `process_batch`.
   - Diagnosis appears.
   - Apply Fix flips victim to fixed mode.
   - Recovery card shows slope reduction.
5. Add polished fallback diagnosis for OpenAI failure.

Success condition:

```text
The original memory demo works even if the LLM/API/network is flaky.
```

### Phase 2: Add Graph-Like Orchestration Without Rewriting Everything

Do this inside the current backend.

Add explicit worker-step records. Every worker writes a structured step to Redis and, later, SQLite:

```json
{
  "incident_id": "current",
  "worker": "memory_investigator",
  "state": "INVESTIGATING",
  "status": "complete",
  "confidence": 0.91,
  "decision": "classify_cause",
  "reason": "process_batch explains most retained memory growth",
  "started_at": 0,
  "ended_at": 0
}
```

This gives the UI a real agent timeline and makes the system feel multi-agent immediately.

Recommended MVP states:

```text
OBSERVING
DETECTING
TRIAGING
INVESTIGATING
CLASSIFYING_CAUSE
LOOKING_UP_PRIOR_FIXES
PLANNING_FIX
SELF_TESTING
AWAITING_APPROVAL
APPLYING_FIX
VERIFYING_RECOVERY
STORING_LEARNING
RESOLVED
FAILED
```

For the hackathon, most states can be deterministic wrappers around current behavior.

### Phase 3: Add Redis Fix Memory

Store a small known-fix cache in Redis.

Example key:

```text
fix_cache:memory_leak:unbounded_collection:process_batch
```

Example value:

```json
{
  "subcause": "unbounded_collection",
  "fix_strategy": "Use a sliding window to bound retained conversation history.",
  "known_safe_mode": "fixed",
  "expected_reduction_pct": 80,
  "risk": "low"
}
```

In the UI, show:

```text
Memory Recall: Found prior fix pattern for unbounded collection in process_batch.
```

This is high impact because it makes the system feel like it learns.

### Phase 4: Add Self-Test Gate

Do not build full generated-code testing yet.

For the MVP, add a deterministic self-test before enabling approval:

```text
Self-Test: Candidate fix strategy matches known safe fixed mode.
Expected RSS slope reduction: >=80%.
Prior fix memory: found.
Risk: low.
Result: passed.
```

This can later become real shadow replay or unit tests.

The key demo idea is:

```text
Sentinel checks its own fix plan before letting a human apply it.
```

### Phase 5: Add UI Timeline

This is the biggest visible improvement.

Show cards like:

```text
Detector
RSS slope exceeded threshold: 1.7 MB/s

Triage Router
Routed to Memory Investigator
Reason: RSS rising, loop lag normal

Memory Investigator
process_batch explains 91% of growth

Redis Fix Memory
Found prior fix pattern: sliding window retention

Self-Test
Passed: low-risk known fix

Verifier
RSS slope reduced 92%
```

This makes the architecture understandable to judges.

### Phase 6: Add Weave Tracing Around Sentinel Workers

Wrap existing backend worker functions with Weave ops and log structured step attributes.

Trace names:

```text
sentinel.detect_anomaly
sentinel.triage_incident
sentinel.memory_investigate
sentinel.retrieve_prior_fix
sentinel.plan_fix
sentinel.self_test
sentinel.apply_fix
sentinel.verify_recovery
```

Log:

- incident id
- state
- worker
- confidence
- decision
- reason
- Redis keys read/written
- before/after metrics
- test result

Pitch line:

```text
Weave traces not just the victim agent, but Sentinel's own incident-response agents.
```

### Phase 7: SQLite If Time Allows

SQLite is useful, but lower priority than timeline + Redis memory + self-test.

If added, use it for durable history only:

- incident started/resolved
- worker steps
- recovery metrics
- fix outcomes

Do not let SQLite block the live demo.

## What Not To Build Yet

Avoid these until the demo is solid:

- Full LangGraph migration.
- Full autonomous patch editing.
- Multi-incident concurrency.
- Real shadow replay sandbox.
- CPU hot-path route.
- CopilotKit chat.
- Complex SQLite analytics.

These are good stretch features, but they can break the core story if started too early.

## Simplified State Graph For Demo

Use this for the actual implementation and UI:

```text
OBSERVING
  -> DETECTING
  -> TRIAGING
  -> INVESTIGATING
  -> LOOKING_UP_PRIOR_FIXES
  -> PLANNING_FIX
  -> SELF_TESTING
  -> AWAITING_APPROVAL
  -> APPLYING_FIX
  -> VERIFYING_RECOVERY
  -> STORING_LEARNING
  -> RESOLVED
```

Failure routes to support without fully implementing every branch:

```text
INVESTIGATING -> TRIAGING              if evidence is weak
SELF_TESTING -> PLANNING_FIX           if self-test fails
VERIFYING_RECOVERY -> TRIAGING         if recovery fails
ANY_STATE -> FAILED                    if budget exhausted
```

For the demo, the happy path is enough. Show the fallback routes in the architecture diagram or pitch.

## Implementation Shape

Keep current files and add small modules.

Suggested backend additions:

```text
backend/agents/triage.py
backend/agents/fix_memory.py
backend/agents/fix_planner.py
backend/agents/self_tester.py
backend/utils/agent_steps.py
backend/utils/redis_health.py
```

Suggested frontend additions:

```text
frontend/lib/api.ts
frontend/components/AgentTimeline.tsx
frontend/components/DemoControl.tsx
frontend/components/RedisHealth.tsx
frontend/components/FixMemoryPanel.tsx
frontend/components/SelfTestPanel.tsx
```

Backend endpoint additions:

```text
GET /api/agent-steps
GET /api/redis-health
GET /api/fix-memory
```

Keep `/api/events` as the main live update channel.

## Complexity / Value Ranking

Build order by value per hour:

1. `frontend/lib/api.ts` if missing.
2. Polished fallback diagnosis.
3. Agent timeline using Redis step records.
4. Redis fix memory panel.
5. Self-test gate.
6. Redis health panel.
7. Weave worker traces.
8. SQLite durable incident history.
9. LangGraph migration.
10. Shadow replay.
11. CPU route.

## Final Recommendation

The easier and better path is:

```text
Do not rebuild the engine right now.
Keep FastAPI + Redis + existing workers.
Add explicit graph states, worker step records, Redis fix memory, self-test, and UI timeline.
Pitch it as an engine-agnostic orchestrator-worker architecture that can later run on LangGraph.
```

That gives the hackathon judges the smarter multi-agent story without risking the working MVP.
