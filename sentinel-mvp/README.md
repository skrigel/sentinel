# Sentinel MVP — Self-Healing Agent Monitor

The watchdog that watches the watchdogs: it watches an agent run, catches a
**memory leak**, traces it to the exact offending op with measured evidence,
asks an LLM to diagnose it, lets a human approve the fix, flips the victim to a
fixed mode, and confirms recovery on a live graph.

This is **Phase A** (memory beat only). See `../docs/superpowers/specs/2026-06-06-sentinel-mvp-design.md`.

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

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/metrics` | last 100 RSS samples |
| GET | `/api/incident` | current incident state |
| GET | `/api/events` | SSE stream of state transitions |
| POST | `/api/apply` | apply fix (flag-flip + verify) |
| POST | `/api/force-detection` | inject anomaly (demo) |
| POST | `/api/reset` | reset to buggy/IDLE |
