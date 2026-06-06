# Sentinel MVP - Design Specification

**Date:** 2026-06-06
**Scope:** Minimal Viable Demo (Phase A, Memory Leak Beat Only)
**Target:** Hackathon demo in ~16 active hours

---

## Overview

Sentinel is a self-healing agent monitoring system that automatically detects performance degradation (memory leaks, CPU hotspots), diagnoses root causes using causal attribution and LLM analysis, and applies fixes with verification. This spec covers the **minimal viable demo**: memory leak detection → diagnosis → manual approval → fix application → recovery confirmation.

**Demo narrative:**
1. Victim agent runs with intentional memory leak
2. After ~45 seconds, Sentinel detects anomaly (RSS slope exceeds baseline)
3. Attribution identifies the leaking operation with measured evidence
4. LLM diagnostician explains what's wrong and how to fix it
5. Human approves fix via dashboard button
6. Sentinel switches victim to fixed mode, verifies recovery
7. Dashboard shows before/after metrics confirming the heal

---

## 1. System Architecture

### 1.1 Deployment Model

**Hybrid architecture:** Single backend process + isolated victim process + Redis blackboard.

```
┌─────────────────────────────────────────────────────────────────┐
│ Docker Compose                                                   │
│                                                                   │
│  ┌──────────────┐    ┌──────────────────────────────────────┐  │
│  │ Redis        │◄───┤ Victim Process (victim/)             │  │
│  │ :6379        │    │ - Instrumented ops (@weave.op)       │  │
│  │              │    │ - tracemalloc deltas → Redis zsets   │  │
│  │ Streams      │    │ - Collector: RSS/loop-lag → streams  │  │
│  │ Pub/Sub      │    │ - Buggy mode (leak) / fixed mode     │  │
│  │ ZSets        │    └──────────────────────────────────────┘  │
│  │ Hashes       │                                               │
│  └───┬──────────┘                                               │
│      │                                                           │
│      │    ┌──────────────────────────────────────────────────┐ │
│      └───►│ Backend (backend/)                               │ │
│           │ FastAPI app with 4 agent modules:                │ │
│           │  - Detector: slope + lag → events:anomaly        │ │
│           │  - Attributor: zset rank → events:enriched       │ │
│           │  - Diagnostician: LLM → events:proposal          │ │
│           │  - Supervisor: state machine + SSE               │ │
│           │ All share process, communicate via Redis pub/sub │ │
│           └───────────────────┬──────────────────────────────┘ │
│                               │ SSE                              │
└───────────────────────────────┼──────────────────────────────────┘
                                │
                    ┌───────────▼──────────────┐
                    │ Frontend (frontend/)     │
                    │ Next.js 14               │
                    │ - Live RSS graph         │
                    │ - Alert card             │
                    │ - Diagnosis panel        │
                    │ - "Apply Fix" button     │
                    │ - Recovery confirmation  │
                    └──────────────────────────┘
```

**Components:**
- **3 Docker containers:** Redis (official image), Victim (Python), Backend (FastAPI)
- **Frontend:** Next.js dev server running locally (`npm run dev`), connects to backend:8000
- **Network:** All containers on same Docker network, service discovery via names

**Why this architecture:**
- Real process isolation for victim (required for accurate psutil RSS measurement)
- Event-driven coordination via Redis pub/sub (multi-agent feel)
- Consolidated backend agents (easier debugging, fewer failure modes)
- Persistent state in Redis (survives backend restarts)

### 1.2 Technology Stack

| Component | Technology | Justification |
|-----------|-----------|---------------|
| Victim instrumentation | tracemalloc + psutil | Python-native, line-accurate attribution; OS-truth for alarms |
| Tracing | W&B Weave | Sponsor tool; captures per-op deltas, LLM calls, evals |
| Blackboard/memory | Redis (Streams, ZSets, Hashes, Pub/Sub) | Single store for metrics, attribution, state, events |
| LLM diagnostician | OpenAI GPT-4o | Strong structured output via `response_format` |
| Backend | FastAPI + SSE | Async-native, SSE is one decorator |
| Frontend | Next.js 14 + Recharts + Tailwind | Modern stack, Recharts for live graphs |

---

## 2. Component Responsibilities

### 2.1 Victim Process

**File:** `victim/main.py`

**Core loop:**
```python
@weave.op()
def initialize():
    # Load embeddings, setup, etc.
    pass

@weave.op()
@instrument_memory()
def process_batch():
    # BUGGY MODE: append to global list (leak)
    # FIXED MODE: clear list each iteration
    pass

@weave.op()
def cleanup():
    pass

# Main loop
while True:
    initialize()
    process_batch()
    cleanup()
    time.sleep(1)
```

**Instrumentation (`@instrument_memory()`):**
```python
def instrument_memory():
    def decorator(fn):
        async def wrapper(*args, **kwargs):
            snap0 = tracemalloc.take_snapshot()
            t0 = time.perf_counter()

            result = await fn(*args, **kwargs)

            self_time = time.perf_counter() - t0
            snap1 = tracemalloc.take_snapshot()
            diff = snap1.compare_to(snap0, "lineno")
            py_delta = sum(s.size_diff for s in diff)
            top_alloc = diff[0] if diff else None

            # Write to Weave span
            weave.attributes({
                "mem_delta_py": py_delta,
                "self_time": self_time,
                "top_alloc": str(top_alloc),
                "mode": get_mode()
            })

            # Write to Redis attribution
            redis.zincrby("attrib:mem", py_delta, fn.__name__)
            redis.hincrby("attrib:invocations", fn.__name__, 1)

            return result
        return wrapper
    return decorator
```

**Collector thread:**
```python
def collector_thread():
    proc = psutil.Process()
    while True:
        rss = proc.memory_info().rss
        lag = measure_loop_lag()  # Custom shim

        redis.xadd("metrics:rss", {"timestamp": time.time(), "rss": rss})
        redis.xadd("metrics:looplag", {"timestamp": time.time(), "lag": lag})

        time.sleep(2)
```

**Mode control:**
```python
def check_mode():
    mode = redis.get("victim:mode")  # "buggy" or "fixed"
    if mode != current_mode:
        sys.exit(0)  # Docker restarts with new mode
```

**Demo leak:**
- `process_batch()` in buggy mode: `global_cache.append(generate_embeddings(batch))`
- `process_batch()` in fixed mode: `global_cache.clear()`
- Leak accumulates ~4-5 MB/iteration, triggers detection in ~45 seconds

### 2.2 Backend Agents

All agents run as async tasks in the same FastAPI process, subscribe to Redis pub/sub.

#### 2.2.1 Detector

**File:** `backend/agents/detector.py`

**Responsibility:** Monitor RSS stream, detect anomalous slope.

**Algorithm:**
```python
@weave.op()
async def detect_anomaly():
    # Establish baseline (first 30 seconds)
    baseline_slope, baseline_stddev = calculate_baseline()
    redis.hset("baseline:rss_slope", {"mean": baseline_slope, "stddev": baseline_stddev})

    # Monitor loop
    async for entry in redis_stream("metrics:rss"):
        window = get_last_n_samples(30)  # 60 seconds at 2s intervals
        slope, r2 = linregress([s.timestamp for s in window], [s.rss for s in window])

        threshold = baseline_slope + 3 * baseline_stddev

        if slope > threshold and r2 > 0.85 and duration >= 30:
            anomaly = {
                "type": "memory_leak",
                "start_ts": time.time(),
                "severity": "HIGH" if slope > threshold * 2 else "MEDIUM",
                "slope": slope
            }
            redis.publish("events:anomaly", json.dumps(anomaly))
            break  # One detection per run
```

**Triggers:**
- RSS slope > baseline + 3σ
- R² > 0.85 (strong linear correlation)
- Sustained for ≥30 seconds

#### 2.2.2 Attributor

**File:** `backend/agents/attributor.py`

**Responsibility:** Identify which operation caused the leak using measured attribution.

```python
@weave.op()
async def attribute_anomaly(anomaly):
    # Get top suspect from cumulative attribution
    results = redis.zrevrange("attrib:mem", 0, 0, withscores=True)
    blamed_op, cumulative_bytes = results[0]

    # Calculate evidence
    invocations = int(redis.hget("attrib:invocations", blamed_op))
    per_call_avg = cumulative_bytes / invocations

    # Cross-check against total RSS growth
    window = get_last_n_samples(30)
    total_rss_growth = window[-1].rss - window[0].rss
    pct_explained = (cumulative_bytes / total_rss_growth) * 100

    enriched = {
        "blamed_op": blamed_op,
        "evidence": {
            "cumulative_bytes": cumulative_bytes,
            "invocations": invocations,
            "per_call_avg": per_call_avg,
            "pct_of_growth_explained": pct_explained
        }
    }

    redis.publish("events:enriched", json.dumps(enriched))
```

**Output:** Causal evidence (not correlation) - "process_batch retained 4.1 MB × 40 calls = 92% of growth"

#### 2.2.3 Diagnostician

**File:** `backend/agents/diagnostician.py`

**Responsibility:** Use LLM to explain root cause and propose fix.

```python
@weave.op()
async def diagnose(enriched):
    blamed_op = enriched["blamed_op"]
    evidence = enriched["evidence"]

    # Read source code (victim codebase mounted as volume or hardcoded)
    source = read_op_source(blamed_op)

    # LLM prompt
    system_prompt = """You are a Python memory profiling expert.
    Given an operation's source code and measured memory attribution evidence,
    diagnose the root cause of the memory leak and explain how to fix it."""

    user_prompt = f"""
    Operation: {blamed_op}
    Evidence:
    - Retained {evidence['per_call_avg']:.1f} MB per call
    - {evidence['invocations']} invocations
    - Explains {evidence['pct_of_growth_explained']:.0f}% of total RSS growth

    Source code:
    ```python
    {source}
    ```

    Provide:
    1. What is happening (diagnosis)
    2. Why it's happening (root cause)
    3. How to fix it (fix strategy)
    4. Confidence level (high/medium/low)
    """

    # Structured output
    response = await openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "diagnosis",
                "schema": {
                    "type": "object",
                    "properties": {
                        "diagnosis": {"type": "string"},
                        "root_cause": {"type": "string"},
                        "fix_strategy": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]}
                    },
                    "required": ["diagnosis", "root_cause", "fix_strategy", "confidence"]
                }
            }
        }
    )

    proposal = json.loads(response.choices[0].message.content)

    # Weave eval: Did it identify the correct operation?
    eval_result = await evaluate_diagnosis(proposal, ground_truth={
        "expected_op": "process_batch",
        "expected_cause": "unbounded list growth"
    })

    proposal["eval"] = eval_result
    redis.publish("events:proposal", json.dumps(proposal))
```

**Weave Integration:**
- `@weave.op()` captures LLM call (input, output, tokens, latency)
- Eval checks if diagnosis mentions correct op and cause
- Eval results displayed in frontend

#### 2.2.4 Supervisor

**File:** `backend/agents/supervisor.py`

**Responsibility:** State machine coordination, SSE to frontend, apply fix.

**State machine:**
```
IDLE → DETECTED → DIAGNOSED → AWAITING_APPROVAL → APPLYING → RESOLVED
```

**Implementation:**
```python
class Supervisor:
    def __init__(self):
        self.state = "IDLE"
        self.incident = {}

    async def run(self):
        # Subscribe to all events
        pubsub = redis.pubsub()
        pubsub.subscribe("events:anomaly", "events:enriched", "events:proposal")

        async for message in pubsub.listen():
            await self.handle_event(message)

    async def handle_event(self, message):
        channel = message["channel"]
        data = json.loads(message["data"])

        if channel == "events:anomaly":
            self.state = "DETECTED"
            self.incident["anomaly"] = data

        elif channel == "events:enriched":
            self.incident["enriched"] = data

        elif channel == "events:proposal":
            self.state = "DIAGNOSED"
            self.incident["proposal"] = data
            await asyncio.sleep(1)
            self.state = "AWAITING_APPROVAL"

        # Persist to Redis
        redis.hset("incident:current", "state", self.state)
        redis.hset("incident:current", "data", json.dumps(self.incident))

        # Emit SSE
        await self.broadcast_sse({"new_state": self.state, "incident": self.incident})

    async def apply_fix(self):
        if self.state != "AWAITING_APPROVAL":
            raise ValueError("Cannot apply fix in current state")

        self.state = "APPLYING"
        await self.broadcast_sse({"new_state": self.state})

        # Set flag to fixed mode
        redis.set("victim:mode", "fixed")

        # Wait for victim to restart and stabilize
        await asyncio.sleep(30)

        # Verify recovery
        window_before = self.incident["anomaly"]["slope"]
        window_after = get_current_slope()

        if window_after < window_before * 0.2:  # 80% reduction
            self.state = "RESOLVED"
            self.incident["verification"] = {
                "slope_before": window_before,
                "slope_after": window_after,
                "reduction_pct": (1 - window_after / window_before) * 100
            }
        else:
            self.state = "FAILED"

        await self.broadcast_sse({"new_state": self.state, "incident": self.incident})
```

### 2.3 Backend API

**File:** `backend/main.py`

**Endpoints:**

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json

app = FastAPI()

@app.get("/api/metrics")
async def get_metrics():
    """Return last 100 RSS samples for graph"""
    samples = redis.xrevrange("metrics:rss", count=100)
    return [{"timestamp": s["timestamp"], "rss": s["rss"]} for s in samples]

@app.get("/api/incident")
async def get_incident():
    """Return current incident state"""
    state = redis.hget("incident:current", "state")
    data = redis.hget("incident:current", "data")
    return {"state": state, "incident": json.loads(data) if data else None}

@app.get("/api/events")
async def sse_events():
    """Server-Sent Events stream for real-time updates"""
    async def event_stream():
        pubsub = redis.pubsub()
        pubsub.subscribe("events:state")
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield f"data: {message['data']}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/api/apply")
async def apply_fix():
    """Trigger fix application"""
    await supervisor.apply_fix()
    return {"status": "applying"}
```

---

## 3. Data Flow & Redis Schema

### 3.1 Redis Data Structures

```python
# Metrics (time-series)
metrics:rss          # Stream: {timestamp, rss_bytes, pid}
metrics:looplag      # Stream: {timestamp, lag_ms}

# Attribution (cumulative scores)
attrib:mem           # ZSet: {op_name: cumulative_bytes}
attrib:invocations   # Hash: {op_name: call_count}

# Baseline (for anomaly detection)
baseline:rss_slope   # Hash: {mean, stddev, samples}

# Incident tracking
incident:current     # Hash: {state, data_json}

# Control flags
victim:mode          # String: "buggy" | "fixed"

# Pub/Sub channels
events:anomaly       # {type, start_ts, severity, slope}
events:enriched      # {blamed_op, evidence}
events:proposal      # {diagnosis, root_cause, fix_strategy, confidence, eval}
events:state         # {new_state, incident}
```

### 3.2 Event Flow Sequence

```
1. Victim writes metrics every 2s
   → XADD metrics:rss {ts, rss}
   → XADD metrics:looplag {ts, lag}

2. Victim ops write attribution
   → ZINCRBY attrib:mem <delta> process_batch
   → HINCRBY attrib:invocations process_batch 1

3. Detector polls metrics:rss stream
   → Calculates slope on new entry
   → Anomaly detected (slope > threshold)
   → PUBLISH events:anomaly {...}
   → Supervisor: IDLE → DETECTED

4. Attributor reacts to events:anomaly
   → ZREVRANGE attrib:mem 0 0 WITHSCORES
   → Top op = process_batch (with evidence)
   → PUBLISH events:enriched {...}

5. Diagnostician reacts to events:enriched
   → Read op source, call OpenAI
   → Run Weave eval on diagnosis
   → PUBLISH events:proposal {...}
   → Supervisor: DETECTED → DIAGNOSED → AWAITING_APPROVAL

6. Frontend displays "Apply Fix" button
   → User clicks
   → POST /api/apply

7. Supervisor applies fix
   → SET victim:mode "fixed"
   → Victim detects change, exits
   → Docker restarts victim in fixed mode
   → Supervisor: AWAITING_APPROVAL → APPLYING

8. Supervisor waits 30s, verifies recovery
   → Confirms slope < 20% of original
   → Supervisor: APPLYING → RESOLVED
   → Frontend shows "✅ Recovery confirmed"
```

### 3.3 Baseline Establishment

- First 30 seconds of victim runtime: Detector calculates baseline RSS slope
- Stored in `baseline:rss_slope` with mean + 3*stddev threshold
- Anomaly detection starts after baseline established
- Demo mode (`DEMO_MODE=true`): Uses hardcoded threshold, skips baseline

---

## 4. Weave Integration & Evals

### 4.1 Tracing

**Victim:**
- `weave.init("sentinel-victim")` on startup
- Every op decorated with `@weave.op()`
- Span attributes: `mem_delta_py`, `self_time`, `top_alloc`, `mode`
- Trace shows leak accumulating (mem_delta growing per call)

**Backend:**
- `weave.init("sentinel-backend")` on startup
- Each agent function wrapped in `@weave.op()`
- LLM call automatically traced (input, output, tokens, latency)
- Entire incident lifecycle becomes a single trace

### 4.2 Evals

**1. Diagnosis Quality Eval:**
```python
@weave.op()
def evaluate_diagnosis(proposal, ground_truth):
    """Check if LLM correctly identified the problem"""
    score = 0

    # Did it mention the correct operation?
    if ground_truth["expected_op"] in proposal["diagnosis"].lower():
        score += 0.5

    # Did it identify the root cause mechanism?
    if ground_truth["expected_cause"] in proposal["root_cause"].lower():
        score += 0.5

    return {
        "accuracy": score,
        "mentioned_correct_op": ground_truth["expected_op"] in proposal["diagnosis"].lower(),
        "identified_cause": ground_truth["expected_cause"] in proposal["root_cause"].lower()
    }
```

**2. Fix Effectiveness Eval:**
```python
@weave.op()
def evaluate_fix_effectiveness(slope_before, slope_after):
    """Measure RSS slope reduction after fix"""
    reduction_pct = (1 - slope_after / slope_before) * 100

    return {
        "slope_reduction_pct": reduction_pct,
        "target_met": reduction_pct >= 80,  # Target: 80% reduction
        "slope_before_mb_s": slope_before / 1024 / 1024,
        "slope_after_mb_s": slope_after / 1024 / 1024
    }
```

**3. End-to-End Eval:**
```python
@weave.op()
def evaluate_end_to_end(detection_ts, resolution_ts):
    """Measure time from detection to resolution"""
    duration = resolution_ts - detection_ts

    return {
        "duration_seconds": duration,
        "target_met": duration <= 90,  # Target: <90s from detect to resolve
    }
```

### 4.3 Frontend Integration

- Eval badges in diagnosis panel: "✅ Diagnosis Accuracy: 100%"
- Click "View Trace in W&B" → opens Weave dashboard with incident trace
- Click "View Eval Results" → shows detailed eval metrics

---

## 5. Error Handling & Resilience

### 5.1 Victim Process Failures

**Weave API unreachable:**
- Graceful degradation: ops still run, spans aren't sent
- Log warning, continue execution
- Attribution still works (writes to Redis directly)

**Redis connection lost:**
- Victim crashes immediately (can't write metrics/attribution)
- Docker restart policy: `restart: always` brings it back
- Supervisor detects gap in metrics stream, logs incident

**Instrumentation overhead timeout:**
- Each op has 30s timeout wrapper
- If exceeded: log error span, skip attribution for that call
- Process continues (don't let measurement kill the victim)

### 5.2 Backend Agent Failures

**Detector misses anomaly (false negative):**
- Not critical for MVP - manual "Force Detection" button in frontend
- All detection results logged to Redis for post-mortem

**Attributor finds no clear culprit:**
- If top op accounts for <30% of growth: emit low-confidence enriched event
- Diagnostician notes this, suggests manual investigation

**Diagnostician LLM call fails:**
- Retry once with exponential backoff (5s wait)
- If still fails: emit proposal with `confidence: "failed"`, diagnosis = error message
- Supervisor transitions to AWAITING_APPROVAL anyway (human can read error)

**OpenAI rate limit / quota exceeded:**
- Same as LLM failure: log error, emit failed proposal
- Frontend shows "Diagnosis failed - manual review needed"

**Supervisor state corruption:**
- All state in Redis, persisted across restarts
- If backend crashes mid-incident: restart reads `incident:current`, resumes from last state
- Each state transition is idempotent (safe to replay)

### 5.3 Frontend Failures

**SSE connection dropped:**
- Auto-reconnect with exponential backoff (max 30s)
- On reconnect: fetch current incident state via GET `/api/incident`
- Seamless recovery for user

**Apply action fails:**
- Backend returns 500 → frontend shows error toast
- Retry button appears
- Supervisor remains in AWAITING_APPROVAL (user can retry)

### 5.4 Demo Safety

**Pre-flight check:**
- `docker-compose up` runs health checks before starting victim:
  - Redis ping succeeds
  - Weave API key valid
  - OpenAI API key valid
- Fail fast with clear error messages

**Demo mode:**
- Environment variable `DEMO_MODE=true`:
  - Skips baseline calculation, uses hardcoded threshold
  - Guaranteed leak trigger timing
  - Pre-recorded backup data available if live detection fails

**Manual overrides:**
- Frontend "Force Detection" button (bypass timing)
- Backend endpoint to inject fake anomaly (testing)

---

## 6. Frontend Design

### 6.1 Tech Stack

- **Next.js 14** (App Router)
- **Recharts** for live RSS graph
- **Tailwind CSS** for styling
- **EventSource API** for SSE

### 6.2 Page Layout

**File:** `app/page.tsx`

```
┌─────────────────────────────────────────────────────────────┐
│ Sentinel - Self-Healing Agent Monitor                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │ RSS Memory Usage (MB)                               │    │
│  │                                                      │    │
│  │  800 ┤                                        ╭──── │    │
│  │  700 ┤                                  ╭────╯      │    │
│  │  600 ┤                            ╭────╯            │    │
│  │  500 ┤                      ╭────╯                  │    │
│  │  400 ┤                ╭────╯                        │    │
│  │  300 ┤          ╭────╯    ← Anomaly detected       │    │
│  │  200 ┤    ╭────╯                                    │    │
│  │  100 ┤───╯                                          │    │
│  │      └──────────────────────────────────────────    │    │
│  │         0s    30s   60s   90s   120s               │    │
│  │                                                      │    │
│  │  Current: 756 MB  |  Baseline slope: 2.1 MB/s      │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │ 🔴 ALERT: Memory Leak Detected                     │    │
│  │ Detected at: 14:32:18  |  Severity: HIGH            │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │ 🔍 Diagnosis                                        │    │
│  │                                                      │    │
│  │ Blamed Operation: process_batch                     │    │
│  │ Evidence:                                            │    │
│  │   • 4.1 MB retained per call × 40 calls             │    │
│  │   • 92% of total RSS growth attributed              │    │
│  │                                                      │    │
│  │ Root Cause:                                          │    │
│  │ Global list 'cache' grows unbounded in process_     │    │
│  │ batch(). Each call appends embeddings without        │    │
│  │ clearing, retaining 4.1 MB per iteration.            │    │
│  │                                                      │    │
│  │ Fix Strategy:                                        │    │
│  │ Clear cache at end of each batch or implement LRU    │    │
│  │ eviction. Fixed mode already contains cache.clear() │    │
│  │                                                      │    │
│  │ Confidence: HIGH                                     │    │
│  │                                                      │    │
│  │ Weave Eval: ✅ Diagnosis Accuracy: 100%             │    │
│  │ [View Trace in W&B] [View Eval Results]             │    │
│  │                                                      │    │
│  │          [ Apply Fix ]  (requires confirmation)      │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 6.3 Component Breakdown

**1. MetricsGraph** (`components/MetricsGraph.tsx`):
- Recharts LineChart with RSS over time
- Red vertical line at anomaly detection timestamp
- Auto-scrolling window (last 120s visible)
- Updates every 2s via polling `/api/metrics`

**2. AlertCard** (`components/AlertCard.tsx`):
- Conditionally rendered when `incident.state >= DETECTED`
- Shows detection time, severity badge
- Dismissible (but reappears if new incident)

**3. DiagnosisPanel** (`components/DiagnosisPanel.tsx`):
- Appears when `incident.state === DIAGNOSED` or later
- Shows blamed op, formatted evidence, LLM diagnosis
- Weave eval badge (✅/❌) with click → W&B link
- "Apply Fix" button enabled only in AWAITING_APPROVAL state

**4. ApplyButton** (`components/ApplyButton.tsx`):
- Modal confirmation before POST `/api/apply`
- Shows loading spinner during APPLYING state
- Disabled in other states

**5. RecoveryConfirmation** (`components/RecoveryConfirmation.tsx`):
- Appears when `incident.state === RESOLVED`
- Shows before/after RSS slopes
- "✅ Memory leak fixed! RSS stabilized at 420 MB"

### 6.4 State Management

```typescript
// app/page.tsx
const [metrics, setMetrics] = useState<Metric[]>([]);
const [incident, setIncident] = useState<Incident | null>(null);

// SSE connection
useEffect(() => {
  const eventSource = new EventSource('http://localhost:8000/api/events');

  eventSource.addEventListener('message', (e) => {
    const { new_state, incident: updatedIncident } = JSON.parse(e.data);
    setIncident(updatedIncident);
  });

  return () => eventSource.close();
}, []);

// Polling for metrics
useEffect(() => {
  const interval = setInterval(async () => {
    const res = await fetch('http://localhost:8000/api/metrics');
    const data = await res.json();
    setMetrics(data);
  }, 2000);

  return () => clearInterval(interval);
}, []);
```

---

## 7. File Structure

```
sentinel-mvp/
├── docker-compose.yml
├── .env.example               # API keys template
├── README.md                  # Setup instructions
│
├── victim/
│   ├── Dockerfile
│   ├── requirements.txt       # weave, psutil, redis, tracemalloc
│   ├── main.py                # Core loop with instrumentation
│   ├── ops.py                 # initialize, process_batch, cleanup
│   └── collector.py           # RSS/loop-lag collector thread
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt       # fastapi, redis, openai, weave
│   ├── main.py                # FastAPI app + endpoints
│   ├── agents/
│   │   ├── detector.py
│   │   ├── attributor.py
│   │   ├── diagnostician.py
│   │   └── supervisor.py
│   └── utils/
│       ├── redis_client.py
│       └── weave_client.py
│
└── frontend/
    ├── package.json
    ├── app/
    │   ├── page.tsx           # Main dashboard
    │   └── layout.tsx
    ├── components/
    │   ├── MetricsGraph.tsx
    │   ├── AlertCard.tsx
    │   ├── DiagnosisPanel.tsx
    │   ├── ApplyButton.tsx
    │   └── RecoveryConfirmation.tsx
    └── lib/
        └── api.ts             # Fetch helpers
```

---

## 8. Demo Flow (Step-by-Step)

**Pre-demo setup (5 minutes):**
1. `cp .env.example .env` → fill in WEAVE_API_KEY, OPENAI_API_KEY
2. `docker-compose up -d` → starts Redis, victim (buggy mode), backend
3. `cd frontend && npm run dev` → starts Next.js on localhost:3000
4. Open browser to localhost:3000, confirm graph is live

**Live demo (2 minutes):**

| Time | What's happening | What judges see |
|------|------------------|-----------------|
| 0:00 | Victim runs in buggy mode | Graph shows RSS climbing steadily |
| 0:30 | Baseline established | Graph annotation: "Baseline: 2.1 MB/s" |
| 0:45 | Anomaly detected | 🔴 Alert card appears: "Memory Leak Detected" |
| 0:50 | Attribution completes | Diagnosis panel shows blamed op + evidence |
| 0:55 | Diagnostician returns | LLM diagnosis appears with eval badge |
| 1:00 | Presenter clicks "Apply Fix" | Modal: "Switch to fixed mode?" → Confirm |
| 1:05 | Victim restarts in fixed mode | Graph shows RSS plateauing |
| 1:30 | Verification completes | ✅ "Memory leak fixed! RSS stabilized at 420 MB" |
| 1:35 | Presenter clicks "View Trace" | W&B Weave opens showing full incident trace |

**Backup plan:**
- If live detection timing is off: use manual "Force Detection" button
- If LLM call fails: pre-recorded incident data loaded from Redis

---

## 9. Success Criteria

**Minimum viable demo must:**
1. ✅ Detect memory leak within 60 seconds of startup
2. ✅ Correctly attribute leak to `process_batch` operation
3. ✅ LLM diagnosis mentions unbounded list growth
4. ✅ Apply fix via button click, victim restarts in fixed mode
5. ✅ Verify RSS slope drops by >80% within 30 seconds of fix
6. ✅ Display Weave trace link showing instrumented ops

**Nice-to-have (if time permits):**
- Manual "Force Detection" button for demo control
- Pre-recorded incident replay mode
- ASCII art in terminal showing event flow
- Detailed Weave eval metrics in frontend

---

## 10. Out of Scope (Phase B)

These features are **explicitly excluded** from MVP to hit time constraints:

- ❌ CPU hotspot detection (loop-lag beat)
- ❌ Shadow mode replay (pre-flight verification)
- ❌ Trace recording (op inputs/outputs)
- ❌ Full supervisor state machine (8 states)
- ❌ CopilotKit chat integration
- ❌ Historical incident log
- ❌ Multi-incident handling
- ❌ Automatic fix generation (vs mode flag flip)

MVP focuses on **one happy path:** memory leak detect → diagnose → manual approve → verify.

---

## 11. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| **tracemalloc overhead distorts timing** | Measure baseline with instrumentation enabled; timing normalized |
| **LLM call latency causes demo lag** | Async processing; frontend shows "Diagnosing..." spinner |
| **OpenAI API rate limit during demo** | Pre-warm API with test call; fallback to pre-recorded diagnosis |
| **Docker networking issues** | All services on same network; health checks before victim starts |
| **Frontend SSE connection flaky** | Auto-reconnect with exponential backoff; polling fallback |
| **Victim doesn't restart cleanly** | Docker restart policy + 5s delay before new mode check |
| **Baseline calculation wrong (warmup noise)** | Demo mode skips baseline, uses hardcoded threshold |

---

## Appendix: Key Design Decisions

**Why hybrid architecture over true microservices?**
- 16-hour timeline favors debuggability over purity
- Backend agents don't need separate processes (no independent scaling needs)
- Real isolation only matters for victim (measurement accuracy)

**Why time-based trigger over manual?**
- Demonstrates real detection capability (not smoke & mirrors)
- Timing predictable enough for demo with DEMO_MODE fallback

**Why Redis over in-memory state?**
- Survives backend restarts (critical for debugging during build)
- Pub/sub is cleaner than Python asyncio queues for event flow
- Sponsor tool, shows distributed system thinking

**Why manual approval over auto-apply?**
- Human-in-loop is safer narrative for judges
- Gives presenter control over demo pacing
- Shows trust verification (Weave eval results before clicking)

**Why Next.js over plain React?**
- SSE support out of box, fast dev server
- Recharts integration simpler than D3
- Modern, recognizable stack for judges

**Why skip CopilotKit for MVP?**
- Adds complexity (chat UX, context management)
- Core demo works without it (observability + fix)
- Phase B enhancement if time permits
