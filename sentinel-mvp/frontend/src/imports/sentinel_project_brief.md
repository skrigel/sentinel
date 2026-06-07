# Sentinel — Project Brief

## The Idea

Long-running agents fail in two quiet ways while no one is watching: they **leak memory** (unbounded history, retained vector stores, accumulating context) and they **starve the event loop** (blocking calls and CPU-bound work in async paths). Nobody notices until something is on fire.

Sentinel is an agent that watches other agents, detects both failures, traces each to the exact offending step, proposes a fix, applies it, and **confirms the metric recovers**. It closes the loop.

**Thesis:** *Agents that run while you play with the robot dog are the agents that leak and spin. Sentinel is the watchdog that watches the watchdogs — and heals them.*

## Why This Fits the Theme

The event is about self-improving agents and "agents that work together while we're away." A monitoring dashboard misses the point. Sentinel is itself an agent that **observes → reasons → acts → verifies** — a self-healing loop applied to other agents. That reframing is the grand-prize spine: not "we built a profiler," but "we built an agent that keeps your unattended agents alive."

## The Two Failures Are One Pipeline (Mostly)

Both failures flow through the same shape:

```
collect → detect → correlate → reason → propose → apply → verify
```

The *shape* is shared; each stage has a memory variant and a CPU variant. Honestly: collector, detector, and correlator differ by signal; only the reason→propose→verify tail is identical. That's still the right story — one framework, instantiated twice — and it buys two distinct demo beats from one codebase.

| | Memory leak | CPU hotpath |
|---|---|---|
| **Signal** | RSS growth rate (slope) | Event-loop lag (+ CPU% if compute-bound) |
| **Correlate by** | Span *attribute* trajectory (e.g. `history_len`) vs. RSS | Span *self-time* overlapping loop-lag spikes |
| **Fix class** | Bounded buffer / eviction / summarize | `run_in_executor` / async client / batch |
| **Recovery** | RSS slope returns to ~0 | Loop lag returns to sub-ms |

## The Demo (Two Beats)

A graph climbs. The co-pilot fires, names the exact step, explains the cause in plain English, proposes a patch. You approve. The graph **flattens**. The agent confirms recovery. Thirty seconds, zero narration needed — and it runs twice, once per failure class.

## Why It Wins

- **Grand prize / on-theme:** A self-healing agent, not a dashboard. Every infra judge (W&B, OpenAI, Cursor) has lived this pain.
- **Best Use of Weave:** Span data is load-bearing — diagnosis works by correlating span attributes/self-time against the metric, then verifying recovery in the trace. Tracing as causal reasoning, not logging.
- **Best Use of Redis:** Holds the metric ring buffer and baseline state; survives restarts; and is a natural home for the eviction patterns the agent proposes.
- **Social demo:** The climb-intervene-flatten arc is inherently visceral and self-explaining.

## One-Line Pitch

> *Sentinel watches your agents while you're away — catching memory leaks and event-loop stalls, tracing each to the exact step, fixing it, and confirming the fix held.*
