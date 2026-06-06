Component Responsibilities

  Victim Process (victim/main.py):
  - Runs synthetic agent loop: initialize() → process_batch() → cleanup() repeated
  - Each op wrapped with @weave.op + tracemalloc instrumentation
  - Leak injection: process_batch() appends to global list in buggy mode, clears in fixed mode
  - Collector thread: Every 2 seconds, samples psutil.Process().memory_info().rss and loop lag, writes to Redis streams (metrics:rss, metrics:looplag)
  - Attribution: Each instrumented op does ZINCRBY attrib:mem <delta> <op_name>
  - Mode control: Reads victim:mode flag from Redis (buggy/fixed), exits when changed (Docker restarts it)

  Backend Agents (backend/agents/):

  1. Detector (detector.py):
    - Subscribes to new metrics:rss stream entries
    - Maintains sliding window (last 30 samples = 60 seconds)
    - Calculates linear regression slope + R²
    - Trigger: slope > baseline * 3σ AND R² > 0.85 AND sustained >= 30s
    - Emits: PUBLISH events:anomaly {type: "memory_leak", start_ts, severity}
  2. Attributor (attributor.py):
    - Subscribes to events:anomaly
    - Reads ZREVRANGE attrib:mem 0 0 WITHSCORES → top suspect op
    - Calculates: cumulative bytes, invocations (from separate counter), per-call avg, % of total RSS growth
    - Emits: PUBLISH events:enriched {blamed_op, evidence: {...}}
  3. Diagnostician (diagnostician.py):
    - Subscribes to events:enriched
    - Reads blamed op source code from victim codebase (mounted volume or hardcoded)
    - Calls OpenAI gpt-4o with structured output:
    response_format={
    "type": "json_schema",
    "json_schema": {
      "name": "diagnosis",
      "schema": {
        "diagnosis": str,      # what's happening
        "root_cause": str,     # why it's happening
        "fix_strategy": str,   # how to fix it
        "confidence": str      # high/medium/low
      }
    }
  }
    - Emits: PUBLISH events:proposal {diagnosis, root_cause, fix_strategy, confidence}
  4. Supervisor (supervisor.py):
    - Subscribes to all events:* channels
    - State machine: IDLE → DETECTED → DIAGNOSED → AWAITING_APPROVAL → RESOLVED
    - Stores incident in Redis hash: incident:current {state, anomaly, enriched, proposal, timestamps}
    - SSE endpoint: /api/events streams state transitions to frontend
    - Apply endpoint: POST /api/apply validates state is AWAITING_APPROVAL, sets victim:mode = fixed, transitions to RESOLVED, waits 30s, confirms RSS slope flattened

  Backend API (backend/main.py):
  - /api/metrics - Returns last 100 RSS samples from Redis stream (for graph)
  - /api/incident - Returns current incident state (for alert card + diagnosis panel)
  - /api/events - SSE stream of supervisor state transitions
  - /api/apply - Triggers fix application (calls supervisor.apply())

  Does this breakdown make sense for the MVP scope?

> Make sure to include weave tracing and evals 

⏺ Good catch! Let me revise Section 2 to include explicit Weave integration.

  Design Section 2 (Revised): Component Responsibilities

  Victim Process (victim/main.py):
  - Weave initialization: weave.init("sentinel-victim") on startup
  - Runs synthetic agent loop: initialize() → process_batch() → cleanup() repeated
  - Each op decorated: @weave.op() wraps every function (initialize, process_batch, cleanup)
  - Instrumentation wrapper: Custom decorator stack:
  @weave.op()
  @instrument_memory()  # tracemalloc snapshot → span attributes
  def process_batch():
      # ... buggy/fixed logic
  - Span attributes written:
    - mem_delta_py: Python bytes retained (from tracemalloc diff)
    - self_time: Operation duration
    - top_alloc: Top allocating line (file:line)
    - mode: "buggy" or "fixed"
  - Attribution: Each instrumented op does ZINCRBY attrib:mem <delta> <op_name>
  - Collector thread: Every 2 seconds, samples RSS/loop-lag → Redis streams
  - Mode control: Reads victim:mode flag from Redis, exits when changed

  Backend Agents (backend/agents/):

  1. Detector (detector.py):
    - Same as before (subscribes to metrics, calculates slope, emits anomaly)
    - Weave integration: Wraps detection logic in @weave.op() so each detection event is traced
  2. Attributor (attributor.py):
    - Same attribution logic (ZREVRANGE → top suspect)
    - Weave integration: @weave.op() wraps attribution, logs blamed_op + evidence as span attributes
  3. Diagnostician (diagnostician.py):
    - Weave integration: LLM call wrapped in @weave.op() to capture:
        - Input: blamed_op source + evidence
      - Output: diagnosis + root_cause + fix_strategy
      - Model: gpt-4o
      - Latency, token count (via Weave's automatic LLM tracing)
    - Weave Evals: After diagnosis, run evaluation:
    @weave.op()
  def evaluate_diagnosis(diagnosis, ground_truth):
      # For demo: ground_truth is hardcoded (we know it's list.append leak)
      # Checks: Did diagnosis mention the correct op? Correct root cause?
      return {"accuracy": 1.0, "mentioned_correct_op": True}
    - Store eval results in Weave, display in frontend
  4. Supervisor (supervisor.py):
    - Same state machine + SSE
    - Weave integration: Each state transition is a @weave.op(), entire incident lifecycle becomes a single trace
    - Apply logic enhanced:
        - Before apply: Create Weave eval comparing predicted fix vs actual outcome
      - After apply: Log verification metrics (RSS slope before/after) as span attributes
      - Eval: "Did RSS slope flatten?" (boolean), "Recovery time" (seconds)

  Weave Dashboard Integration:
  - Victim trace shows the leak accumulating (mem_delta growing per call)
  - Backend trace shows the diagnosis pipeline (detect → attribute → diagnose → apply)
  - Evals tracked over time: diagnosis accuracy, fix effectiveness
  - Frontend can embed Weave trace links (click "View Trace" button → opens W&B)

  Weave Evals Strategy:
  1. Diagnosis Quality Eval: Compare LLM's blamed_op against ground truth (we know it's process_batch)
  2. Fix Effectiveness Eval: Measure RSS slope reduction after fix (target: >80% reduction)
  3. End-to-End Eval: Time from detection → resolved (target: <90 seconds)