# Sentinel MVP — Self-Healing Agent Monitor

The watchdog that watches the watchdogs: it watches an agent run, catches a
**memory leak**, traces it to the exact offending op with measured evidence,
asks an LLM to diagnose it, lets a human approve the fix, flips the victim to a
fixed mode, and confirms recovery on a live graph.

It ships **two demo beats** (a memory leak and a CPU hot path) and can monitor
either the built-in victim or **your own uploaded agent**, blaming the **entry
point** you choose. See `../docs/superpowers/specs/2026-06-06-sentinel-mvp-design.md`.

## Architecture

```
victim  ──metrics/attribution──▶  Redis  ◀──▶  backend (FastAPI)
(leaky agent, instrumented)      blackboard     Detector → Attributor
                                                → Diagnostician (GPT-4o)
                                                → Supervisor (state machine)
                                                        │ SSE
                                                        ▼
                                                  frontend (Next.js)
```

Design invariants (see `../CLAUDE.md`): tracemalloc *attributes*, RSS slope
*alarms*; the only LLM is the Diagnostician; "apply" is a flag-flip to a
pre-written fixed mode; agents coordinate over a Redis blackboard.

## Run it

1. **Env**
   ```bash
   cp .env.example .env
   # fill in OPENAI_API_KEY (and optionally WANDB_API_KEY for Weave tracing)
   ```

2. **Backend + victim + Redis** (3 containers)
   ```bash
   docker compose up --build
   ```
   Backend on http://localhost:8000 (`/api/health` to check).

3. **Frontend** (local dev server)
   ```bash
   cd frontend
   cp .env.local.example .env.local
   npm install
   npm run dev
   ```
   Open http://localhost:3000.

## Demo flow

1. Victim starts in `buggy` mode → RSS climbs on the graph.
2. After ~45s the Detector fires → 🔴 alert card.
3. Attributor blames `process_batch` with measured evidence.
4. Diagnostician (GPT-4o) explains the leak; a Weave eval badge scores it.
5. Click **Apply Fix** → victim restarts in `fixed` mode (sliding window K=8).
6. Supervisor waits 30s, verifies slope dropped ≥80% → ✅ recovery card.

`DEMO_MODE=true` (default) skips baseline calc and uses a fixed slope threshold
for predictable timing. The header **Force Detection** button is a demo-safety
override. `POST /api/reset` returns everything to `buggy`/IDLE for another run.

## Monitoring your own agent (add agent + entry point)

Sentinel isn't hardcoded to the built-in victim. Upload a Python file (or a
`.zip` bundle) on the dashboard and pick the **entry point** — the op you want
Sentinel to attribute and diagnose. The registry (`utils/agent_store.py`) tracks
every agent, its entry point, and which one is monitored (exactly one primary at
a time); the Diagnostician reads *that* entry point's source from *that* agent.

An uploaded file falls into one of two runtime states:

- **Runnable** — it defines `_make_op(redis_client)` returning the 4-tuple
  `(initialize, <work>, <retrieve>, cleanup)` of async ops. Selecting it makes
  the victim loop restart and run *your* agent (apply == flag-flip, CLAUDE.md #5).
- **Source-only** — no `_make_op`, so it's used for source diagnosis only. The
  built-in victim keeps running the loop.

Ready-to-upload examples live in `examples/` (each documents its entry point):

| File | Entry point | Beat | What it shows |
|------|-------------|------|----------------|
| `original_victim_agent.py` | `process_batch` | memory | faithful copy of the built-in victim |
| `test1_agent.py` | `embed_documents` | memory | leak on a **custom** entry point |
| `test2_agent.py` | `rerank_results` | cpu | event-loop-blocking `json.dumps` hot path |

### Adding your own runnable agent

Copy `examples/test1_agent.py`, rename the ops to your agent's steps, and:

1. Keep `_make_op(redis_client)` returning the **4-tuple**
   `(initialize, <work>, <retrieve>, cleanup)` of `@weave.op()`/`@instr`-wrapped
   async ops (positional — the names are yours; the loop runs all four each tick).
2. Put your bug in one op (unbounded growth for the memory beat, or a synchronous
   CPU-bound call for the CPU beat), gated on `get_mode()`/`get_beat()` so the
   apply-time flag-flip can switch it to the fixed branch.
3. Declare module-level **`ENTRY_POINT`** (the op name to watch) and **`BEAT`**
   (`"memory"` or `"cpu"`).

That's the whole contract. Name the file `*_agent.py` and the test suite
**auto-discovers and validates it** — no test edits needed (see below). At upload
time you still pick the entry point in the form; `ENTRY_POINT` is its default and
what the examples/tests key off.

## Tests

```bash
cd backend
# point the SQLite registry + uploads at throwaway paths (defaults are /data/*)
ACTIVITY_DB_PATH=$(pwd)/.testdata/activity.db \
AGENT_UPLOAD_DIR=$(pwd)/.testdata/agents \
VICTIM_SRC_DIR=$(pwd)/../victim \
python -m pytest -q
```

`tests/test_agent_store.py` covers the add-agent/entry-point registry;
`tests/test_example_agents.py` **auto-discovers** every `examples/*_agent.py`,
loads each the way `victim/main.py` does, runs one loop iteration to prove it's
actually runnable through its declared `ENTRY_POINT` (not just hardcoded), and
checks the Diagnostician can read that op's source. Drop a new `*_agent.py` into
`examples/` following the contract above and the suite validates it with **no
edits** to the tests. Per-test isolation comes from `tests/conftest.py`
(throwaway DB + upload dir), so the env vars above are only a safety net for the
default-path tests.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/metrics` | last 100 RSS samples |
| GET | `/api/procstat` | recent USS / CPU% / fd / thread samples |
| GET | `/api/agents` | list agents (built-in + uploaded) and runtime status |
| POST | `/api/agents` | upload agent file(s)/bundle + set entry point |
| PATCH | `/api/agents/{id}` | rename / re-monitor / change entry point |
| DELETE | `/api/agents/{id}` | delete an uploaded agent |
| GET | `/api/agents/metrics` | RSS samples grouped by monitored agent |
| GET | `/api/incident` | current incident state |
| GET | `/api/timeline` | per-node activity for the current incident |
| GET | `/api/activity` | durable cross-incident activity log |
| GET | `/api/events` | SSE stream of state transitions |
| POST | `/api/apply` | apply fix (flag-flip + verify) |
| POST | `/api/force-detection` | inject anomaly (demo) |
| POST | `/api/reset` | reset to buggy/IDLE |
