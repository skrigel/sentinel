# Sentinel — Implementation Plan

> **Assumptions (inline):** Python victim runs as a subprocess Sentinel controls. Sponsor tools: W&B Weave (tracing), Redis (state + memory + pub/sub), CopilotKit (frontend), OpenAI (Diagnostician). Single machine. Team of 2, ~16 active hours. The plan ships an **MVP (Phase A)** first; **shadow-mode replay (Phase B)** is layered on only after Phase A demos cleanly. No code yet — pseudocode and signatures only.

---

## 0. What Changed From the Planning Doc

Two upgrades reshape the middle of the pipeline:

- **Correlation → causal attribution.** We no longer infer the culprit from co-movement (history_len tracks RSS). We *measure* it: every op carries a memory delta and self-time as span attributes, and we rank ops by cumulative attributed cost. Output is "`embed_documents()` retained 4.1 MB/call × 40 calls = 92% of RSS growth," not "RSS is high."
- **A pre-flight gate.** Between *propose* and *apply* we insert **shadow replay**: run the patch against recorded recent steps, confirm the metric improves *there* first, then promote to live. Two verification gates now exist — shadow (pre-flight, on a replay) and live (post-apply, on the real process).

---

## 1. Architectural Approach + Data Flow

Sentinel is a small team of independent workers over a **Redis blackboard**, coordinated by a thin **Supervisor** state machine. Each worker reads/writes shared Redis state and hands off via pub/sub events. The flow is mostly a pipeline; the blackboard makes each stage independently testable — which is what you want under time pressure.

```
┌────────────────────────────────────────────────────────────────┐
│ VICTIM AGENT (subprocess, instrumented)                         │
│  every op wrapped: snapshot mem+time → run → delta → span attrs  │
│  fault behind flag; fix behind a second flag                     │
│  RECORDER (Phase B): writes {op, inputs, outputs} → trace stream │
└───────┬───────────────────────────────────┬─────────────────────┘
        │ Weave spans                        │ psutil (RSS, CPU)
        │ (mem_delta, self_time, top_alloc)  │ + loop-lag shim
        ▼                                    ▼
┌───────────────┐                  ┌──────────────────────────────┐
│ WEAVE TRACE   │                  │  COLLECTOR → REDIS STREAMS    │
└───────┬───────┘                  │  metrics:rss / cpu / looplag  │
        │ per-op attribution        └──────────────┬───────────────┘
        │ ZINCRBY attrib:mem/cpu                    │
        ▼                                           ▼
┌──────────────────────────  REDIS BLACKBOARD  ──────────────────────────┐
│ metrics:* (streams)   baseline:* (hash)   attrib:mem|cpu (zset)         │
│ trace:recent (stream, Phase B)   incidents (stream+hash)                │
│ pub/sub: events:anomaly → enriched → proposal → shadow → verdict        │
└──────────┬──────────┬───────────┬─────────────┬────────────┬───────────┘
           ▼          ▼           ▼             ▼            ▼
      ┌─────────┐┌──────────┐┌──────────────┐┌────────────┐┌───────────┐
      │DETECTOR ││ATTRIBUTOR││DIAGNOSTICIAN ││SHADOW-VERIF││SUPERVISOR │
      │slope+lag││rank zset ││ LLM, 2 prompts││ (Phase B)  ││state mach.│
      │(no LLM) ││(no LLM)  ││ structured out││ replay     ││+ gates    │
      └─────────┘└──────────┘└──────────────┘└────────────┘└─────┬─────┘
                                                                 │ SSE
                                                                 ▼
                                              ┌──────────────────────────┐
                                              │ FRONTEND (Next + Copilot) │
                                              │ graph · alert · diagnosis │
                                              │ · shadow result · recovery│
                                              └──────────────────────────┘
```

**Incident lifecycle (Supervisor state machine):**
```
DETECTED → ATTRIBUTED → DIAGNOSED → [Phase B: SHADOW_RUN → SHADOW_PASS/FAIL]
        → AWAIT_APPROVAL → APPLYING → LIVE_VERIFY → RESOLVED | REVERTED
```
Phase A skips the SHADOW_* states (DIAGNOSED → AWAIT_APPROVAL). Phase B inserts them; the live-apply gate requires SHADOW_PASS.

---

## 2. Tech Stack

| Component | Choice | Why / simpler-beats-correct |
|---|---|---|
| Per-op mem attribution | `tracemalloc` snapshot diff | Python-level, line-accurate attribution; robust via cumulative ranking. Demo leak is pure-Python so it's fully visible |
| Process alarm signal | `psutil` RSS + custom loop-lag shim | OS-truth for the alarm; shim is the only honest event-loop signal. `time.sleep` ≠ CPU, so lag is primary |
| Blackboard / memory | Redis (Streams, Hash, ZSet, Pub/Sub) | One store for metrics, baselines, attribution, traces, incidents, *and* handoffs. Survives restart; sponsor tool |
| Tracing | W&B Weave | Spans carry the deltas; the diagnosis and (B) recovery live in the trace. Sponsor |
| Diagnostician LLM | OpenAI `gpt-4o`, `response_format` | Strong structured output; only heavy-LLM step |
| Orchestration | Redis pub/sub + thin Supervisor | Deterministic, debuggable. **No orchestration-LLM** — that's flakiness on the critical path |
| Shadow replay (B) | subprocess + recorded-output stubs | Deterministic, API-free replay; isolated process is measurable from outside like the live victim |
| Backend | FastAPI + SSE | Async; SSE is one decorator |
| Frontend | Next.js 14 + CopilotKit + Recharts | Sponsor; chat panel shows agents reasoning; degrades to plain dashboard |

---

## 3. Core Agent Workflows

**Orchestration pattern: blackboard + thin supervisor.** Workers are stateless event handlers; all durable state is in Redis; the Supervisor owns only the incident state machine and the gates. Rationale for a 16-hour build: each agent is built and tested in isolation, one agent failing can't corrupt another, and there's no LLM in the coordination path. It reads as "multi-agent" (independent roles over shared state) without negotiation-protocol overhead.

| Agent | Trigger | Reads | Writes / emits | LLM? |
|---|---|---|---|---|
| **Detector** | new metric sample | `metrics:*`, `baseline:*` | `events:anomaly {type, start_ts, severity}` | no |
| **Attributor** | `events:anomaly` | `attrib:{mem\|cpu}` zset, recent spans | `events:enriched {blamed_op, evidence}` | no |
| **Diagnostician** | `events:enriched` | blamed-op source, `incidents` history | `events:proposal {diagnosis, root_cause, patch, confidence}` | **yes** |
| **Shadow-Verifier** (B) | `events:proposal` | `trace:recent` | `events:shadow {pass, metric_before, metric_after, delta}` | no |
| **Supervisor** | every event | incident state | state transitions, `incidents` record, SSE to frontend | no |

**Handoff** is purely event-driven over Redis pub/sub; **shared state** is the blackboard. Every input the Diagnostician's LLM sees comes from Redis reads (evidence, source, prior incidents) — so its grounding is dependable and reproducible, not improvised.

---

## 4. Implementing the Hard Parts (conceptual + signatures)

### 4a. Per-step memory-delta instrumentation
Wrap each op. Use **tracemalloc for attribution** (which op/line holds memory) and **RSS for the alarm** (does the OS see growth). Don't trust a single op's RSS delta — it's noisy; rely on cumulative-across-invocations ranking, which averages the noise out.

```python
def instrument(op_name):
    # decorator around each @weave.op()
    def wrap(fn):
        async def inner(*a, **k):
            snap0 = tracemalloc.take_snapshot()
            t0 = perf_counter()
            result = await fn(*a, **k)              # run the op body
            self_time = perf_counter() - t0
            snap1 = tracemalloc.take_snapshot()
            diff = snap1.compare_to(snap0, "lineno")
            py_delta = sum(s.size_diff for s in diff)   # retained Python bytes
            top = diff[0]                                # top allocating line
            weave.attributes({                           # → span
                "mem_delta_py": py_delta,
                "self_time": self_time,
                "top_alloc": str(top),
            })
            redis.zincrby("attrib:mem", py_delta, op_name)   # cumulative
            redis.zincrby("attrib:cpu", self_time, op_name)
            return result
        return inner
    return wrap
```
Note: tracemalloc adds overhead — disable it during CPU-beat timing runs so it doesn't distort self-time.

### 4b. Causal attribution (replaces the correlator)
Deterministic ranking, plus a sanity cross-check against total RSS growth.
```python
def attribute(anomaly) -> Enriched:
    key = "attrib:mem" if anomaly.type == "memory_leak" else "attrib:cpu"
    op, score = redis.zrevrange(key, 0, 0, withscores=True)[0]   # top suspect
    total_rss_growth = rss_window_delta()                        # from metrics
    explained = score / total_rss_growth if memory else None     # % attributed
    return Enriched(blamed_op=op, evidence={
        "cumulative": score,
        "invocations": op_invocation_count(op),
        "per_call_avg": score / invocations,
        "pct_of_growth_explained": explained,
    })
```
This is *measured* causation: "this op allocated and retained X across N calls, = Y% of observed growth." Evidence travels to the Diagnostician.

### 4c. Detector (unchanged in spirit, tightened)
```python
# memory: baseline the SLOPE, not absolute RSS (warmup poisons absolute)
slope, r2 = linregress(rss_window)
if slope > slope_baseline_3sigma and r2 > 0.85 and sustained(>= W secs):
    emit("memory_leak")
# cpu: loop-lag is primary; CPU% only splits blocking vs compute-bound
if loop_lag_mean(10) > 50ms:
    emit("cpu_hotpath", compute_bound = cpu_pct_3sigma())
```

### 4d. Diagnostician
```python
def diagnose(enriched) -> Proposal:
    sys = MEM_PROMPT if enriched.type == "memory_leak" else CPU_PROMPT
    ctx = {
      "evidence": enriched.evidence,            # the measured numbers
      "source": source_of(enriched.blamed_op),  # the actual function
      "history": redis_recent_incidents(enriched.blamed_op),  # grounding
    }
    return openai.structured(sys, ctx,
        schema=Proposal)  # {diagnosis, root_cause, patch, confidence}
```
The LLM must ground its diagnosis in `evidence` + `source`, not vibes — confidence is "high" only when source confirms the mechanism.

### 4e. (Phase B) Trace recording + shadow replay + promote gate
**Record** while the victim runs (bounded to "recent"):
```python
# inside each op, after running:
seq = redis.xadd("trace:recent", {"op": op_name, "inputs": j(inputs),
                                  "outputs": j(outputs)}, maxlen=200)
```
**Replay** in an isolated subprocess, serving recorded outputs so it's deterministic and API-free; measure the same metric from outside via psutil:
```python
def shadow_run(code_mode) -> MetricTraj:   # code_mode = "buggy" | "candidate"
    steps = redis.xrange("trace:recent")
    proc = spawn_replay(code_mode, steps)  # LLM/tool calls served from `steps`
    return sample_metric(proc.pid)         # same collector, isolated PID
```
**Promote gate** (Shadow-Verifier → Supervisor):
```python
before = shadow_run("buggy")               # or reuse recorded buggy trajectory
after  = shadow_run("candidate")           # candidate = pre-written fixed-mode
passed = improvement(after, before) >= THRESHOLD and no_errors(after)
emit("events:shadow", pass=passed, ...)
# Supervisor: only SHADOW_PASS + human approval → APPLYING (flag flip)
```
**"Improvement"** is measured against the metric that alarmed: memory → replayed slope < 20% of buggy slope; CPU → blamed-op self-time reduced > 50%. Scope shadow to the **memory beat first** (slope deltas replay cleanly; CPU self-time is timing-sensitive and flakier).

---

## 5. Implementation Sequence

### Phase A — MVP (causal trace → diagnose → apply → live-verify)

| # | Task | Owner | Gate |
|---|---|---|---|
| A0 | Repo, Redis up, Weave init, victim base loop with `@weave.op()` | both | spans visible, Redis reachable |
| A1 | Per-op instrumentation: tracemalloc delta + self_time → span + `attrib:*` zsets | you | top_alloc shows the right line on a hand-test |
| A2 | Collector (psutil RSS/CPU + loop-lag shim) → Redis streams; Detector (slope+R², lag) | you | injected leak fires anomaly <60s, reliably |
| A3 | Attributor: rank zset → blamed_op + evidence | you | blames the correct op with sane numbers |
| A4 | Diagnostician: MEM + CPU prompts, structured output, grounded in evidence+source | you | memory case → readable diagnosis + patch |
| A5 | Apply (flag-flip buggy→fixed) + Live-Verify (confirm metric recovers) | you | graph flattens, verifier confirms |
| A6 | Frontend: live graph, alert card, diagnosis panel, recovery state (SSE) | mate | beat renders end-to-end on screen |
| A7 | Supervisor state machine + pub/sub wiring (can degrade to linear async chain) | both | both beats run via events |
| A8 | CPU beat end-to-end; rehearse both beats; record backup video | both | two clean beats, timed ~2 min each |

**MVP cutline — ships no matter what:** A0–A6 for the **memory beat** (detect → causally attribute → diagnose → flag-flip apply → confirm recovery), on a live graph.
**Fight to include:** CPU beat (A8), real Supervisor (A7).
**Cut first if behind:** CopilotKit (→ plain dashboard), CPU beat, polish.

### Phase B — Shadow Mode (only after Phase A demos cleanly)

| # | Task | Gate |
|---|---|---|
| B1 | Recorder: per-op `{op, inputs, outputs}` → `trace:recent` (bounded) | recent steps visible in Redis |
| B2 | Replay harness: subprocess re-executes loop from recorded outputs (deterministic) | candidate-mode replay runs, measurable PID |
| B3 | Shadow-Verifier + improvement criterion; emit verdict | memory patch shows clear improvement on replay |
| B4 | Insert SHADOW_RUN/PASS/FAIL into Supervisor; gate live-apply on PASS | live-apply blocked until shadow passes |
| B5 | Frontend: show shadow before/after *before* the approve button | judge sees "proven safe on replay, then applied" |
| B6 | Feed `incidents` history into Diagnostician context (grounding across runs) | second occurrence cites the first |

**Phase B is the headline differentiator** ("we prove the fix helps on a replay before touching live"), but it is strictly additive — if B is incomplete, the Phase A flag-flip + live-verify still gives a complete, honest demo.

---

## 6. Top Risks (this design)

**R1 — Per-op memory delta is noisy; tracemalloc distorts timing.** *Mitigation:* tracemalloc for *attribution ranking only* (robust via cumulative sums); RSS slope for the *alarm*; disable tracemalloc during CPU self-time measurement. Don't chase precise single-call RSS deltas.

**R2 — Shadow replay determinism.** Faithfully re-executing steps is the hardest new piece. *Mitigation:* serve recorded LLM/tool outputs (no fresh calls); keep victim steps pure given inputs; scope shadow to the memory beat first. If replay is unreliable, fall back to Phase A's flag-flip live-verify — shadow is explicitly the *addition*, so the demo survives without it.

**R3 — Orchestration / state-machine complexity under demo pressure.** Two gates and ~8 states is a lot to get right live. *Mitigation:* blackboard + thin Supervisor, no orchestration LLM; model the state machine explicitly and small; build the happy path first; Supervisor can degrade to a linear async function for the MVP.

**R4 — tracemalloc misses native allocations** (C-extension vector libs allocate outside Python). *Mitigation:* the chosen demo leak is pure-Python (`list.append`), fully visible to tracemalloc; state the limitation honestly in Q&A rather than engineering around it. RSS slope still catches native growth at the alarm layer.

**R5 — Weave span retrieval is awkward programmatically.** *Mitigation:* attribution already flows through Redis zsets (not Weave queries), so the critical path doesn't depend on querying Weave; Weave stays the human-facing trace + recovery view. Timebox any Weave-API needs to 45 min.
