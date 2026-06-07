# Sentinel — the watchdog that watches the watchdogs

A self-healing observability agent for **other agents**. Point it at a long-running agent and it watches the live runtime; the moment the agent starts to rot — a **memory leak** or CPU-bound work **blocking its async event loop** — Sentinel detects it, blames the exact offending operation, has GPT-4o diagnose it and write a fix, gets one click of human approval, applies it, and **measures** that the agent recovered before going back to watching.

**Observe → reason → act → verify, pointed at other agents.** The whole loop is deterministic except a single LLM call.

> Built at WeaveHacks (W&B).

## Why

Agents run for hours unsupervised. The failure nobody watches for isn't a bad answer — it's an agent that silently degrades (RAM climbing until it's OOM-killed; a blocked event loop stalling every task). These are invisible to evals: CPU% looks fine while the loop is jammed, and absolute memory looks fine during warmup. Sentinel catches it by alarming on **RSS slope** and **event-loop lag**, then attributes the fault to the exact line with `tracemalloc`.

## Architecture

```
victim agent ──signals──▶  Redis blackboard  ◀──▶  backend (FastAPI + LangGraph)
(instrumented)             streams · pub/sub        Detector → Attributor
                           ZSets · vector mem       → Diagnostician (GPT-4o)
                                                     → Supervisor (state machine)
                                                            │ SSE
                                                            ▼
                                                     React + Monaco dashboard
```

The LLM is called once (diagnosis); coordination is a deterministic LangGraph + Redis blackboard, so it's safe to act unattended.

## Run it

```bash
cd sentinel-mvp
# create .env with: OPENAI_API_KEY, WANDB_API_KEY, WEAVE_PROJECT=<entity>/<project>
docker compose up --build   # redis + instrumented victim + backend (graph orchestrator)
cd frontend && npm install && npm run dev   # dashboard (Vite)
```

Backend on `:8000`, dashboard on the Vite dev port. See [`sentinel-mvp/README.md`](sentinel-mvp/README.md) for details and [`sentinel-mvp/docs/agent-upload-format.md`](sentinel-mvp/docs/agent-upload-format.md) to monitor your own agent.

## Built with

**W&B Weave** (tracing + hallucination-scorer guardrail + evals) · **OpenAI** GPT-4o + embeddings · **Redis** (blackboard, streams, pub/sub, attribution ZSets, vector recall) · **LangGraph** · **Monaco** · **Cursor**.
