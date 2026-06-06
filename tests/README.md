# Sentinel scenario suite

Authoritative spec for the runtime-bug scenarios under `test1/`, `test2/`, `test3/`.
If code and this file disagree, **this file wins** — fix the scenario.

---

## 1. Purpose

A scenario suite for exercising Sentinel against a variety of *runtime* bugs. Sentinel
is an incident-response agent that watches a live Python process and reasons only from
**telemetry**: RSS (`psutil`), CPU%, event-loop lag, and Redis health. Attribution of a
memory leak to a specific operation is done with `tracemalloc` per-op deltas
(`attrib:mem` ZSet, keyed by the offending function's name). Detection is
telemetry-based, **not** static code analysis.

These scenarios test two things at once:

- the **resolvable** path: can Sentinel detect → attribute → diagnose → flag-flip a fix →
  verify recovery on a live metric, and
- the **graceful-decline** path: when a symptom is real but *outside what Sentinel can
  honestly fix* (native allocations it can't attribute, pressure that lives in an external
  system, or no leak at all), does it route to `REPORT_UNRESOLVED` with honest reasoning
  instead of confidently proposing a wrong fix.

## 2. Paradigm

**Every scenario is a runnable Python module that produces a measurable runtime symptom.**
A scenario is not a snippet of buggy source for someone to read — it is a workload. Its
`run(duration_seconds)` function, when invoked inside (or as) the victim process, must
drive enough activity that one of these symptoms shows up in the telemetry within the
window:

- a sustained positive **RSS slope** (memory leak),
- a **CPU** spike with event-loop lag (compute-bound hot path),
- **event-loop lag** with low CPU (blocking I/O in the async loop), or
- **Redis growth** while process RSS stays flat (external backlog).

Static buggy code with no observable runtime effect is explicitly **not** a scenario.

## 3. Two tiers

| Tier | What Sentinel should do | `expected_outcome` |
|---|---|---|
| `resolvable` | Fully diagnose, flag-flip a fix, and verify recovery. | `resolved` |
| `graceful_decline` | Recognize the symptom is real but un-fixable-by-Sentinel; route to `REPORT_UNRESOLVED` with honest reasoning, propose **no** fix. (Or, for a benign plateau, not fire at all.) | `report_unresolved` or `no_detection` |

The decline tier is the point of the suite as much as the resolvable tier: it proves
Sentinel knows its own limits.

## 4. Subcause taxonomy

Stays consistent with the `CAUSE_CLASSIFIER` taxonomy in `sentinelv2plan.md`:

```
unbounded_collection · cache_without_ttl · large_object_retention ·
native_memory_growth · event_loop_blocking · sync_io_in_async_loop ·
redis_queue_backlog · unknown
```

**RESOLVABLE** — pure-Python only, so `tracemalloc` can attribute them to a named op:

| symptom | subcause |
|---|---|
| `memory_leak` | `unbounded_collection` |
| `memory_leak` | `cache_without_ttl` |
| `memory_leak` | `large_object_retention` |
| `cpu_hotpath` | `event_loop_blocking` |
| `cpu_hotpath` | `sync_io_in_async_loop` |

**GRACEFUL_DECLINE** — designed to defeat one of Sentinel's assumptions:

| symptom | subcause | why it must decline |
|---|---|---|
| `memory_leak` | `native_memory_growth` | Allocations live in numpy / `ctypes` C buffers. `tracemalloc` (Python-only) under-attributes, so no op honestly explains the RSS growth. |
| `redis_pressure` | `redis_queue_backlog` | Items are pushed to a Redis list faster than they are consumed. The **process** RSS stays flat; the growth is in Redis, an external system. |
| `none` | `benign_plateau` | RSS rises during warmup then plateaus. There is no sustained slope — the detector must not false-fire and no fix may be proposed. |

## 5. Scenario file contract

Every file defines **exactly** these two things at module scope:

```python
SCENARIO = {
    "name": "<unique_snake_case>",
    "tier": "resolvable" | "graceful_decline",
    "expected_symptom": "memory_leak" | "cpu_hotpath" | "redis_pressure" | "none",
    "expected_subcause": "<taxonomy value>",
    "expected_blamed_op": "<exact function name>" | None,   # None for decline tier
    "expected_outcome": "resolved" | "report_unresolved" | "no_detection",
    "expected_min_rss_growth_mb": <int>,    # 0 if N/A
    "expected_min_cpu_pct": <int>,          # 0 if N/A
    "decline_reason_keywords": [<str>, ...],  # decline tier only: substrings the
                                              # honest reasoning should mention,
                                              # e.g. ["native", "tracemalloc"]
    "description": "<one sentence>",
}

def run(duration_seconds: int = 60) -> None:
    """Drives the workload; must produce the expected symptom within the window."""
```

For **resolvable** scenarios the buggy function(s) are **module-level** and **named to
match `expected_blamed_op` exactly**, so attribution scoring (`attrib:mem` top op ==
`expected_blamed_op`) is unambiguous. The dominant retained allocation (memory) or the
dominant self-time (CPU) lives *inside* that function.

For **decline** scenarios `expected_blamed_op` is `None`: there is intentionally no op a
`tracemalloc`-based attributor can honestly blame.

`SCENARIO` is importable without importing `numpy` / `redis` — those heavier deps are
imported lazily inside `run()` so a harness can read every `SCENARIO` dict cheaply.

## 6. Per-folder rule

Each `testN/` contains **exactly 4 files**: 3 `resolvable` (spanning ≥2 different
subcauses) + 1 `graceful_decline`.

- `test1/` — `unbounded_collection`, `cache_without_ttl`, `event_loop_blocking` + `native_memory_growth`
- `test2/` — `large_object_retention`, `sync_io_in_async_loop`, `unbounded_collection` (different variant) + `redis_queue_backlog`
- `test3/` — free resolvable mix (≥1 `memory_leak`, ≥1 `cpu_hotpath`) + `benign_plateau`

**Coverage across all folders** (see matrix in §10): all three decline scenarios appear,
and each resolvable subcause is covered with meaningfully different variants.

> **Known spec tension (read this).** The rule "every resolvable subcause appears ≥2
> times" needs `5 subcauses × 2 = 10` resolvable slots, but the fixed 3-folder layout
> only provides `3 folders × 3 = 9` resolvable slots (the 4th file in each folder is
> reserved for a decline scenario). 9 < 10, so full satisfaction is impossible without
> adding a folder or a 5th file. This suite resolves the tension by **fully covering all
> three memory-leak subcauses (the ship-no-matter-what beat) and `event_loop_blocking` at
> ≥2 each, leaving `sync_io_in_async_loop` at exactly 1**. If you add a `test4/` (or a 4th
> resolvable to one folder), add a second `sync_io_in_async_loop` variant to close it.

## 7. Variant rule

Two scenarios with the same subcause differ in **all** of: blamed-op name, growth/spike
rate, payload shape, and surrounding control flow. No copy-paste between variants.

## 8. Realism rule

Workloads read like plausible application code — request handling, cache lookups, batch
processing, event consumers, media pipelines — not `leak1.py` toy demos.

## 9. Safety

`run()` honors `duration_seconds` and exits cleanly via a wall-clock deadline. No infinite
loops, no `os._exit`, no `os.fork`, no subprocesses. Decline scenarios that touch Redis
namespace their keys and clean up in a `finally`. Each file is independently runnable
(`python <file>.py [duration]`) for manual smoke-testing.

## 10. Coverage matrix

resolvable subcauses (target ≥2; `sync_io_in_async_loop` at 1 — see §6 tension):

| subcause | count | files |
|---|---|---|
| `unbounded_collection`   | 2 | `test1/unbounded_collection_audit_log.py`, `test2/unbounded_collection_consumer.py` |
| `cache_without_ttl`      | 2 | `test1/cache_without_ttl_search.py`, `test3/cache_without_ttl_templates.py` |
| `large_object_retention` | 2 | `test2/large_object_retention_expand.py`, `test3/large_object_retention_frames.py` |
| `event_loop_blocking`    | 2 | `test1/event_loop_blocking_serialize.py`, `test3/event_loop_blocking_compress.py` |
| `sync_io_in_async_loop`  | 1 | `test2/sync_io_in_async_loop_profile.py` |

decline subcauses (each ≥1):

| subcause | count | files |
|---|---|---|
| `native_memory_growth` | 1 | `test1/native_memory_growth_numpy.py` |
| `redis_queue_backlog`  | 1 | `test2/redis_queue_backlog_jobs.py` |
| `benign_plateau`       | 1 | `test3/benign_plateau_warmup.py` |
