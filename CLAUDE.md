# CLAUDE.md — Sentinel

Sentinel is an agent that watches other AI agents while they run unattended, catches **memory leaks** and **CPU/event-loop hot-paths**, traces each to the exact offending step, proposes a fix, and confirms recovery. Built for WeaveHacks (24–36h, team of 2).

**Thesis:** the watchdog that watches the watchdogs — observe → reason → act → verify, applied to other agents.

---

## Critical design invariants (do not break these)

These encode hard-won decisions. Violating them silently breaks the demo.

1. **tracemalloc attributes, RSS alarms.** Use `tracemalloc` per-op diffs to decide *which op* leaked (line-accurate, robust via cumulative ranking). Use `psutil` RSS *slope* to decide *whether* there's a leak. Never try to make a single op's RSS delta precise — it's noise.
2. **Baseline the slope, not absolute RSS.** Python RSS grows during warmup; an absolute baseline is poisoned. Alarm on sustained positive slope + R² > 0.85.
3. **Loop-lag is the primary CPU signal, not CPU%.** Blocking I/O / `time.sleep` starves the event loop without raising CPU%. Alarm on loop-lag (>~50ms); use CPU% only to split blocking vs. compute-bound.
4. **No orchestration LLM.** Agents coordinate via a Redis blackboard + pub/sub + a thin deterministic Supervisor state machine. The only LLM call is the Diagnostician. Keep LLMs off the coordination path.
5. **"Apply" = flag-flip, not hot-reload.** Applying a fix flips the victim from buggy-mode to a *pre-written fixed-mode*. Recovery is real and measured; arbitrary code hot-reload is out of scope.
6. **Shadow mode (Phase B) is additive.** Do not block the MVP on it. MVP path is propose → apply → live-verify. Shadow inserts a pre-flight gate only after the MVP demos cleanly.
7. **Scope is exactly one leak + one hot-path.** Resist generalizing. More breadth = more demo failure surface.

---

## Architecture

Independent workers over a Redis blackboard; a thin Supervisor owns the incident state machine and the gates.

```
VICTIM (instrumented subprocess) ──spans/metrics──> REDIS BLACKBOARD <──> WORKERS
                                                          │
  Detector → Attributor → Diagnostician → [Shadow-Verifier, B] → Supervisor → SSE → Frontend
```

**Incident lifecycle:**
`DETECTED → ATTRIBUTED → DIAGNOSED → [SHADOW_RUN → PASS/FAIL, B] → AWAIT_APPROVAL → APPLYING → LIVE_VERIFY → RESOLVED | REVERTED`
(Phase A skips the SHADOW_* states.)

**Agents:** Detector (slope+lag, no LLM) · Attributor (rank ZSet → blamed op, no LLM) · Diagnostician (OpenAI, 2 prompts, structured output) · Shadow-Verifier (Phase B, replay harness, no LLM) · Supervisor (state machine + gates, no LLM).

---

## Redis schema (the shared contract)

| Key | Type | Purpose |
|---|---|---|
| `metrics:rss` / `metrics:cpu` / `metrics:looplag` | Stream | metric samples (XADD maxlen) |
| `baseline:{metric}` | Hash | slope/lag mean + std |
| `attrib:mem` / `attrib:cpu` | ZSet | cumulative per-op retained bytes / self-time |
| `trace:recent` | Stream | (Phase B) `{op, inputs, outputs}` for replay, bounded |
| `incidents` | Stream + Hash | past diagnoses; grounds the Diagnostician |
| pub/sub `events:anomaly\|enriched\|proposal\|shadow\|verdict` | channel | agent handoffs |

All grounding the Diagnostician's LLM sees comes from Redis reads — keep it that way (reproducible context).

---

## Tech stack

Python victim + Sentinel: `psutil`, `tracemalloc`, `redis`, `weave`, `openai`, FastAPI + SSE.
Frontend: Next.js 14 + CopilotKit + Recharts (degrades to a plain dashboard if CopilotKit stalls).

---

## Proposed repo layout

```
victim/          # instrumented document-QA agent (the target); fault + fix behind flags
sentinel/
  instrument.py  # per-op tracemalloc/self-time wrapper → span attrs + attrib ZSets
  collector.py   # psutil + loop-lag shim → metric streams
  agents/        # detector, attributor, diagnostician, shadow_verifier
  supervisor.py  # state machine + gates
  redis_keys.py  # single source of truth for key names
  api.py         # FastAPI + SSE
frontend/        # Next.js + CopilotKit dashboard
```

---

## Conventions

- **Async throughout**; the victim is an asyncio loop.
- **Dataclasses internally, Pydantic v2 at API/event boundaries.**
- **Every victim step is a `@weave.op()`** and goes through `instrument.py` — no exceptions, or attribution breaks.
- Redis key names come from `redis_keys.py` only; never hardcode key strings.
- Disable tracemalloc during CPU-beat timing runs (it distorts self-time).

---

## The scoped demo (exactly two beats)

- **Memory leak:** `conversation_history` is an unbounded list appended every loop iteration. Fix mode: sliding window K=8.
- **CPU hot-path:** the "retrieve" step does a genuinely CPU-bound `json.dumps` of a large nested dict synchronously in the async loop. Fix mode: `asyncio.run_in_executor`.

Run each beat as a clean start (~2s restart) — a leaked process can't re-baseline mid-run. End on the memory beat (irreversible, dramatic); run the recoverable CPU beat first.

---

## MVP cutline

**Ships no matter what:** memory beat — detect → causally attribute → diagnose → flag-flip apply → confirm recovery, on a live graph.
**Fight to include:** CPU beat, real Supervisor state machine.
**Phase B (additive):** shadow-mode replay + incident-history grounding.
**Cut first if behind:** CopilotKit, CPU beat, polish.

## Out of scope

Distributed/multi-host, real hot-reload, native-memory leaks (tracemalloc is Python-only — the demo leak is pure-Python), generalization beyond the two beats.
