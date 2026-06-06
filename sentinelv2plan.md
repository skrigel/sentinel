# Sentinel v2 — Implementation Plan

> The watchdog that watches the watchdogs: **observe → reason → act → verify**, applied to other AI agents.
>
> This plan supersedes the Phase-A MVP framing in `sentinel_implementation_plan.md`. It is **grounded in the running code** (the stack was built and run; findings below) and folds in three decisions made during planning: (1) a **deterministic incident graph** as the orchestration model, (2) **disciplined sponsor-tool leverage** (Weave + Redis used for real capability, not for show), and (3) **MVP = the full architecture with the dials set to minimum** — nothing is thrown away when we scale up.

---

## 0. What changed from the MVP

The MVP is a linear pipeline that reveals a *pre-written* fix. v2 is a **stateful diagnostic graph** that *searches* for a fix and *proves* it:

- **Correlation-rank → counterfactual attribution.** Not "this op ranks highest," but "without this op, the metric is flat."
- **Pre-written flag-flip → generated-and-verified fix.** The LLM proposes a patch; a self-test/shadow gate proves it helps *before* it touches live. Flag-flip remains the safe fallback.
- **One-shot chain → bounded iterative loop.** `DIAGNOSE → VERIFY → (fail) → DIAGNOSE(with failure context)` up to a budget. This loop is the system's intelligence.
- **Single demo case → eval harness.** A dataset of injected bugs proves Sentinel generalizes, not just rehearses.

Guiding principle throughout: **intelligence lives in the nodes; routing stays deterministic.** The LLM writes patches and diagnoses. It never decides who runs next — every edge is driven by a measured signal. "Our orchestration cannot hallucinate" is both a safety property and a pitch line.

---

## 1. Grounded current-state truth (from actually running it)

| Component | Status | Evidence |
|---|---|---|
| Docker stack (redis + victim + backend) | ✅ builds & runs | all 3 up; `/api/health` → `{"ok":true}` |
| Victim leak + instrumentation | ✅ real | RSS 91 MB → 1.17 GB; `attrib:mem` = `process_batch` 102 MB |
| Attributor | ✅ correct | blames `process_batch`, ~6 invocations, sane evidence |
| **Detector** | 🔴 **broken on restart** | stayed `IDLE` 70 s+; stale pre-restart samples in `metrics:rss` straddle a 1.8 GB→91 MB cliff → R² collapses → never fires |
| **`frontend/lib/api.ts`** | 🔴 **missing** | 6 files import `../lib/api` (page + 5 components) → frontend will not build |
| Diagnostician fallback | 🟡 unpolished | bare error string when OpenAI key absent |
| Weave traces | 🟡 needs creds | `weave.init` fails without `WANDB_API_KEY` + `WANDB_ENTITY` |
| CopilotKit | ⚪ not installed | `package.json` = next/react/recharts only → **drop from scope** |
| Leak rate | ℹ️ ~12 MB/s, not 4 | Python `float` ≈ 24 B; code comment underestimates (harmless) |

**Two P0 blockers exist before any new feature:** the detector PID bug and the missing `lib/api.ts`.

---

## 2. Target architecture (layers)

```
L4 INTERFACE   pub/sub narration → Agent Timeline · SSE state · REST actions      (observe only)
L3 ORCHESTRATOR  IncidentWorkflow graph (deterministic edges) + loop budgets       (NO LLM routing)
L2 WORKERS     Detector · Attributor · Diagnostician(LLM) · SelfTest/Shadow ·
               Applier · Verifier · Reporter                                       (intelligence here)
L1 BLACKBOARD  Redis: metric streams (PID-segmented) · attrib · semantic fix-memory ·
               IncidentState                                                       (durable, fast)
L1' DURABLE    SQLite: incidents · agent_steps · fixes  (analytics, off critical path)
L0 DATA PLANE  victim instrumentation → L1
```

**Layering discipline (the rule that makes parallel work safe):** workers never call each other. Each reads from L1, computes, writes to L1. L3 is the only thing that knows the order. L4 only observes. Calls go *down*, never sideways.

**Orchestration engine.** The architecture *is* the transition table + worker contracts (§4), which is engine-agnostic. LangGraph is the chosen engine (cycles, retries, human-in-the-loop `interrupt()`, streaming, Redis checkpointer all built-in) — but every conditional edge reads a measured field, never an LLM. The engine is swappable; the table is the truth.

---

## 3. The scoped incident graph (full topology, live vs stub)

Build the full *shape* so "routes incidents through specialists" is true; light up only the scoped paths (CLAUDE.md #7: one leak + one hot-path).

```
OBSERVE → DETECT → TRIAGE_ROUTER ─┬─ memory_leak   → MEMORY_INVESTIGATOR    ★ LIVE
                                  ├─ cpu_hotpath   → CPU_INVESTIGATOR       ◇ STRETCH
                                  └─ redis/async/unknown                    ○ STUB → REPORT_UNRESOLVED

MEMORY_INVESTIGATOR ─(pct>60)→ CAUSE_CLASSIFIER ─(known)→ RETRIEVE_FIX(Redis) ─(hit)→ PLAN_FIX
                    ─(pct<20)→ back to TRIAGE                               ─(miss)→ PLAN_FIX_WITH_LLM
                    ─(else)→  EVIDENCE_COLLECTOR ↺ (budget)

PLAN_FIX → SELF_TEST ─(pass)→ AWAIT_APPROVAL → APPLY → VERIFY ─(recovered)→ STORE_LEARNING → RESOLVED
                     ─(fail)→ PLAN_FIX ↺ (budget)            ─(not)→ ROLLBACK → TRIAGE / ESCALATE
```

**Live path for the demo:** `OBSERVE→DETECT→TRIAGE→MEMORY_INVESTIGATOR→CAUSE_CLASSIFIER→RETRIEVE_FIX→PLAN_FIX→SELF_TEST→AWAIT_APPROVAL→APPLY→VERIFY→STORE_LEARNING→RESOLVED`, **plus the `SELF_TEST→PLAN_FIX` retry edge** — that one cycle is what proves it's a graph, not a chain.

### Transition table (the architecture in one place)

| State | Signal (measured) | → Next |
|---|---|---|
| DETECTED | classified | TRIAGING |
| TRIAGING | symptom_type=memory_leak | INVESTIGATING |
| TRIAGING | other type | REPORT_UNRESOLVED (stub) |
| INVESTIGATING | pct_explained > 60 | CLASSIFYING_CAUSE |
| INVESTIGATING | pct_explained < 20 | TRIAGING (re-route) |
| INVESTIGATING | otherwise + budget | NEEDS_MORE_EVIDENCE ↺ |
| CLASSIFYING_CAUSE | known subcause | LOOKING_UP_PRIOR_FIXES |
| LOOKING_UP_PRIOR_FIXES | semantic hit + relevant | PLANNING_FIX (reuse) |
| LOOKING_UP_PRIOR_FIXES | miss | PLANNING_FIX (LLM) |
| PLANNING_FIX | patch ready | TESTING_FIX |
| TESTING_FIX | tests_passed & not hallucinated | AWAITING_APPROVAL |
| TESTING_FIX | fail + fix_attempts left | PLANNING_FIX ↺ |
| TESTING_FIX | fail + budget spent | REPORT_UNRESOLVED |
| AWAITING_APPROVAL | human approve | APPLYING_FIX |
| APPLYING_FIX | applied | VERIFYING_RECOVERY |
| VERIFYING_RECOVERY | slope reduction ≥ target | STORE_LEARNING → RESOLVED |
| VERIFYING_RECOVERY | regressed | ROLLBACK → TRIAGING / ESCALATE |

### Loop budgets (prevent infinite cycling)

```
max_triage_rounds        = 3
max_investigation_rounds = 4
max_fix_attempts         = 2
max_observe_more_seconds = 60
```

On exhaustion → `REPORT_UNRESOLVED` with useful reasoning (e.g. *"tracemalloc explains only 6% of RSS growth; suspect native allocation — check C-extensions"*).

---

## 4. Shared contract — lock this FIRST

This is the integration seam that lets three people build in parallel. **Freeze it before anyone writes a node.**

### IncidentState (persisted to Redis as JSON under `incident:current` and `incident_context:{id}`)

```python
IncidentState = {
  "incident_id": str, "status": str,
  "symptom_type": "memory_leak|cpu_hotpath|event_loop_lag|redis_pressure|unknown",
  "suspected_subcause": str | None,     # see CAUSE_CLASSIFIER taxonomy
  "confidence": float,
  "evidence": list,                     # accrues across nodes
  "attempted_routes": list, "rejected_routes": list,   # loop-avoidance + explainability
  "proposed_fix": dict | None,
  "test_result": dict | None,           # {tests_passed, rss_slope_before, rss_slope_after, confidence}
  "verification": dict | None,
  "next_action": str | None,
}
```

### Node decision envelope (every node returns this; published to `events:narration` + appended to SQLite `agent_steps`)

```json
{
  "node": "memory_investigator", "status": "complete", "confidence": 0.42,
  "summary": "process_batch explains 12% of RSS growth; Python attribution weak.",
  "evidence_added": [{"type":"attribution","key":"attrib:mem","value":"process_batch: 12%"}],
  "decision": "back_to_triage", "reason": "RSS rising but retained-memory attribution too low."
}
```

### Subcause taxonomy (CAUSE_CLASSIFIER)

```
unbounded_collection · cache_without_ttl · large_object_retention ·
native_memory_growth · event_loop_blocking · sync_io_in_async_loop ·
redis_queue_backlog · unknown
```

### Redis key contract (extends current `redis_keys.py`)

```
metrics:rss · metrics:looplag            (streams, XADD MAXLEN; PID-segmented reads)
attrib:mem · attrib:invocations          (zset / hash)
baseline:rss_slope                       (hash)
incident:current · incident_context:{id} (hash / json)
fix_cache:{type}:{subcause}:{op}         (exact-key fast path)
incident_vec:{id}                        (hash: embedding + signature, for semantic recall)
events:anomaly|enriched|proposal|state|narration  (pub/sub)
```

---

## 5. Agent / node roles

| Node | LLM? | Reads | Writes |
|---|---|---|---|
| **Observer/Collector** | no | psutil RSS/CPU, loop-lag | `metrics:*` (with `pid`) |
| **Detector** | no | `metrics:*` (PID-segmented), `baseline:*` | `symptom_type`, severity → `events:anomaly` |
| **Triage Router** | no (LLM fallback only) | symptom_type, attempted/rejected routes | route decision |
| **Memory Investigator** | no | `attrib:mem`, `metrics:rss`, source, history | counterfactual evidence, `pct_explained` |
| **Cause Classifier** | optional LLM | evidence + source | `suspected_subcause`, confidence |
| **Retrieve-Fix (Redis memory)** | no | `fix_cache:*`, `incident_vec:*` | candidate fix (reuse) |
| **Fix Planner** | **yes** | evidence + source + **fix-attempt history** | `proposed_fix` (diff) + risk + test plan + rollback |
| **Self-Test / Shadow** | no | proposed_fix, replay tape | `test_result` {pass, slope_before/after, confidence} |
| **Applier** | no | approved fix | flag-flip `victim:mode=fixed` (MVP) |
| **Verifier** | no | live `metrics:rss` (PID-segmented) | `verification` {reduction_pct, duration} |
| **Reporter / Store-Learning** | no | full incident | SQLite rows + `fix_cache` + `incident_vec` |

---

## 6. Sponsor-tool leverage (real capability, not checkbox)

Principle: extract *full* capability toward the goal; deliberately leave irrelevant features on the shelf.

### Weave — three layers (only one is "evals")

1. **System-of-record (tracing).** Wrap every node as `@weave.op()`:
   `sentinel.observe · detect · triage · memory_investigate · retrieve_fix · classify_cause · plan_fix · self_test · verify · report`.
   The trace tree becomes the audit trail, the **visualization of the retry loop** (re-entrant nested calls), and per-node latency/token observability. This realizes *"Sentinel monitors agents; Weave monitors Sentinel's agents."* For each step log: input evidence, Redis keys touched, prompt+output (LLM steps), route decision, confidence, latency, test result, metric impact.

2. **Scorers as critical-path gates (not reports).** Exactly two fit:
   - **`WeaveHallucinationScorerV1`** (local, HHEM 2.1, no API) — **the headline.** `context = evidence + blamed-op source`, `output = diagnosis`. **Fail ⇒ graph does not advance to AWAITING_APPROVAL.** Weave as a gate that prevents acting on a hallucinated fix. Local ⇒ runs on CPU (coheres with running our own model locally).
   - **`WeaveContextRelevanceScorerV1`** (local) — gates fix-memory retrieval: is the recalled prior fix actually relevant to *this* incident before reuse?
   - Cheap insurance only: `ValidJSONScorer` / `PydanticScorer` (schema already enforced by `response_format`).
   - **Deliberately NOT used** (checkbox traps for our use case): Summarization, Toxicity, Bias, Fluency, Coherence, PII/Presidio, Moderation — Sentinel emits no user-facing prose that can be toxic/biased.

3. **Evaluation harness (generalization proof).** Upgrade the hand-rolled `evaluate_diagnosis` into a `weave.Evaluation`: a **Dataset of injected bug scenarios** (leak variants + CPU hotpath), the graph as the model, scorers = {right op? right subcause? fix verified?}. Use **`EvaluationLogger`** (imperative) to also log every *live* incident as a scored prediction — the bridge from offline eval to online monitoring.

   Weave eval questions: did the classifier pick the right type? did subcause match ground truth? did the fix plan address the actual cause? did self-test pass before apply? did live recovery happen?

*Setup grounding:* Weave traces require `WANDB_API_KEY` **and** `WANDB_ENTITY` (or `entity/project` in `weave.init`). Without the entity it silently no-ops — make this a real env task, not best-effort, since Weave is judged.

### Redis — three layers, and one honest "no"

1. **Operational substrate (keep).** Streams + ZSet + Hash + pub/sub is already load-bearing, good Redis usage.
2. **Semantic incident memory (the upgrade).** Replace exact-key fix lookup with *"have we seen an incident like this?"*: embed each incident signature (symptom + evidence + blamed op), store in Redis, retrieve by **cosine similarity**. Powers the "second occurrence recalls the first" beat robustly.
3. **Semantic LLM cache (LangCache-style).** Cache Diagnostician outputs by evidence-similarity → recurring leak resolves **without an LLM call**; show the cache hit in the UI.

**The honest "no":** skip **Redis Context Retriever / Iris** — it's a preview, schema-first, MCP-tool-generating, enterprise multi-DB product (Redis Cloud / private preview) for "tool-zoo sprawl." Not our problem; adopting it is pure checkbox. Also: real vector indexing needs `redis/redis-stack` (compose uses `redis:7-alpine`, no search module). **At demo scale (a handful of incidents) use embeddings + brute-force cosine stored in Redis — you get the genuine semantic-memory capability without premature ANN infra.** Switch to `redis-stack` only if you specifically want the Redis-Vector badge.

### How they compose (one loop, fully traced)

```
new incident → embed signature → Redis semantic recall ─┬─ hit → ContextRelevance gate → reuse fix
                                                        └─ miss → Fix Planner (LLM)
                                          → Hallucination gate (must pass to proceed)
                                          → self-test / verify → on success: embed + store in Redis (learning)
                                          → EvaluationLogger logs the scored resolution
        ── every step wrapped in @weave.op() = full trace tree ──
```

Redis = the memory (don't re-reason what you've seen). Weave = the conscience + system-of-record (don't act on a hallucination; prove you generalize).

---

## 7. Data model — Redis vs SQLite

**Redis (fast, operational):** incident state, live metric streams, pub/sub, attribution zsets, short-term context, cached + semantic fix memory, Redis health snapshots.

**SQLite (durable analytics, off critical path):** incidents, agent-step timings, fix success/failure, recovery-time history, confidence-vs-outcome. **Start minimal — `incidents` + `fixes` only**; defer the full analytics suite.

```sql
CREATE TABLE incidents (id TEXT PRIMARY KEY, type TEXT, subcause TEXT, blamed_op TEXT,
  started_at REAL, resolved_at REAL, status TEXT);
CREATE TABLE agent_steps (id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT,
  agent_name TEXT, state TEXT, started_at REAL, ended_at REAL, confidence REAL,
  decision TEXT, reason TEXT);
CREATE TABLE fixes (id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT, fix_type TEXT,
  summary TEXT, tests_passed INTEGER, verified INTEGER);
```

---

## 8. Build order (sequenced, with gates) — scoped to ~8–16 hrs

### Phase 0 — Unblock (must do first, ~1–2 hrs)
| # | Task | File | Gate |
|---|---|---|---|
| 0.1 | **Detector PID-segmentation:** in `get_last_n_rss`, take newest sample's `pid`, walk back, stop at first `pid` change → window only ever holds the current victim. Fixes detect-on-restart **and** between-run pollution in one shot. | `backend/utils/redis_client.py` | leak fires reliably after a restart |
| 0.2 | **Write `frontend/lib/api.ts`** — exports `API_BASE, fetchMetrics, fetchIncident, applyFix, forceDetection, resetIncident` + types `Metric, Incident, IncidentState, …` | `frontend/lib/api.ts` | `npm run dev` builds |
| 0.3 | Polished canned fallback diagnosis for the known leak | `backend/agents/diagnostician.py` | demo works with OpenAI down |

### Phase 1 — Graph migration (the architecture)
- 1.1 Define `IncidentState` + transition table + loop budgets (§3/§4).
- 1.2 Re-host existing agents as graph nodes; Supervisor → graph executor. Deterministic edges only.
- 1.3 Wire the `TESTING_FIX → PLANNING_FIX` retry loop (the one cycle that must work).
- 1.4 Expand frontend `STATE_ORDER` + gating to the new states.
- **Gate:** memory beat runs end-to-end through the graph; Agent Timeline shows nodes lighting up.

### Phase 2 — Differentiators + sponsor leverage
- 2.1 **Weave: wrap every node `@weave.op()`** with structured decision logs (set `WANDB_ENTITY`).
- 2.2 **Hallucination scorer as the diagnosis gate** (local; blocks AWAITING_APPROVAL on fail).
- 2.3 **Redis semantic incident memory** (embeddings + cosine, no redis-stack) + RETRIEVE_FIX + recall UI beat (needs 2-run choreography).
- 2.4 **Self-Test gate** emitting `{tests_passed, rss_slope_before/after, confidence}` (MVP = lightweight; honest = mini shadow-replay).
- 2.5 **Weave Evaluation harness** over a small injected-bug dataset (generalization proof). *(if time)*

### Phase 3 — Polish & durability (parallel, off critical path)
- 3.1 Agent Timeline + Demo Control + Redis Health panels.
- 3.2 SQLite (`incidents` + `fixes` first).
- 3.3 Evidence Board / Memory Recall / Fix Preview / Recovery Stats panels.
- 3.4 Context-relevance gate on retrieval + semantic LLM cache.

### Stretch (only if green)
- CPU / loop-lag route live (sync `json.dumps` → `run_in_executor`).
- Full shadow-replay sandbox (subprocess replays recorded trace).

---

## 9. Three-person workstream split

Lock the §4 contract together first, then parallelize:

- **Person A — Orchestration:** LangGraph graph, IncidentState, transition table, loop budgets, Supervisor→executor migration, HITL `interrupt()` for approval.
- **Person B — Workers + data:** 0.1 / 0.3, counterfactual attribution, Redis semantic memory, self-test, Weave node-wrapping + scorers + eval harness, SQLite.
- **Person C — Frontend + demo:** 0.2, Agent Timeline, Demo Control, Redis Health, evidence/recall/fix-preview panels, demo choreography + backup video.

---

## 10. UI panels (priority order)

1. **Agent Timeline** — each node lights up with status, duration, decision, confidence (drives the "graph of specialists" story).
2. **Demo Control** — Reset · Force Detection · victim mode · backend health · Redis health · latest RSS slope.
3. **Evidence Board** — RSS slope, blamed op, attribution %, source snippet, subcause.
4. **Memory Recall** — Redis found a similar prior incident / cached fix.
5. **Fix Preview** — strategy, risk, expected impact, rollback.
6. **Self-Test Result** — tests passed, simulated/replayed slope improvement, confidence.
7. **Recovery Stats** — slope before/after, % improvement, time-to-recovery, stored learning.

(CopilotKit is **not** in scope — not installed; plain dashboard is the baseline.)

---

## 11. Guardrails & risks (grounded)

- **Graph sprawl = #1 demo killer.** Stubs stay stubs; resist lighting up redis/async/deep investigators (CLAUDE.md #7).
- **Keep the old pub/sub path runnable** until the graph demos cleanly — don't delete working code first.
- **Verify a clean second run** — the PID fix (0.1) should make `reset` not needing to clear `metrics:rss`; confirm it.
- **Weave needs `WANDB_ENTITY`** or the headline trace story silently no-ops.
- **No LLM on the routing path** — Triage's LLM fallback stays a fallback; all primary edges read measured fields.
- **tracemalloc is Python-only** — demo leak is pure-Python by design; state the native-memory limitation honestly in Q&A.

---

## 12. Pitch

**Full vision:**
> Sentinel is an incident-response agent for AI systems. It observes a running agent, detects failures from live metrics, routes investigation through specialist nodes, recalls similar past incidents from Redis semantic memory, has an LLM plan a fix, **gates that fix against hallucination and proves it on a self-test before any human approves**, applies it, verifies live recovery, stores the learning, and traces every decision in Weave — so Sentinel monitors agents, and Weave monitors Sentinel.

**Current demo (honest):**
> Sentinel watches an agent, detects a real memory leak from process RSS, causally attributes it to one operation, diagnoses it with a grounded (hallucination-gated) LLM call, lets a human approve, then verifies the system healed — on a live graph, every step visible in Weave.
