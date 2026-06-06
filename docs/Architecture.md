 Design Section 1: System Architecture Overview

  Three-Container Setup:

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

  Deployment model:
  - docker-compose up starts Redis + Victim + Backend
  - Frontend runs via npm run dev (local dev server, connects to backend:8000)
  - All containers on same Docker network, services discover via service names

  Data flow:
  1. Victim writes metrics → Redis streams, attribution → Redis zsets
  2. Backend agents subscribe to Redis pub/sub channels, react to events
  3. Frontend polls /api/metrics for graph data, listens to /api/events SSE for alerts
  4. User clicks "Apply Fix" → backend sets flag → victim restarts in fixed mode