"""FastAPI app: hosts the 4 agents as asyncio tasks, exposes metrics/incident
REST + an SSE stream, and the human-in-the-loop apply endpoint.

Event flow (spec §3.2): detector -> events:anomaly -> attributor ->
events:enriched -> diagnostician -> events:proposal. The Supervisor subscribes
to all three to drive the state machine; the SSE endpoint relays events:state.
"""

import asyncio
import contextlib
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agents import attributor, detector, diagnostician
from agents.supervisor import Supervisor
from utils.redis_client import get_last_n_rss, redis
from utils.redis_keys import (
    EVENTS_ANOMALY,
    EVENTS_ENRICHED,
    EVENTS_PROPOSAL,
    EVENTS_STATE,
    INCIDENT_CURRENT,
)
from utils.weave_client import init_weave

supervisor = Supervisor()
_tasks: list[asyncio.Task] = []


async def _anomaly_listener():
    """events:anomaly -> Supervisor + kick off attribution chain."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(EVENTS_ANOMALY)
    async for msg in pubsub.listen():
        if msg["type"] != "message":
            continue
        data = json.loads(msg["data"])
        await supervisor.on_anomaly(data)
        # Deterministic handoff: attribute, then diagnose.
        enriched = await attributor.attribute_anomaly(data)
        await diagnostician.diagnose(enriched)


async def _enriched_listener():
    pubsub = redis.pubsub()
    await pubsub.subscribe(EVENTS_ENRICHED)
    async for msg in pubsub.listen():
        if msg["type"] != "message":
            continue
        await supervisor.on_enriched(json.loads(msg["data"]))


async def _proposal_listener():
    pubsub = redis.pubsub()
    await pubsub.subscribe(EVENTS_PROPOSAL)
    async for msg in pubsub.listen():
        if msg["type"] != "message":
            continue
        await supervisor.on_proposal(json.loads(msg["data"]))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    init_weave()
    await supervisor.reset()
    _tasks.append(asyncio.create_task(detector.detect_anomaly()))
    _tasks.append(asyncio.create_task(_anomaly_listener()))
    _tasks.append(asyncio.create_task(_enriched_listener()))
    _tasks.append(asyncio.create_task(_proposal_listener()))
    print("[backend] agents started")
    yield
    for t in _tasks:
        t.cancel()


app = FastAPI(title="Sentinel", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    try:
        await redis.ping()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/metrics")
async def get_metrics():
    """Last 100 RSS samples (oldest-first) for the live graph."""
    return await get_last_n_rss(100)


@app.get("/api/incident")
async def get_incident():
    state = await redis.hget(INCIDENT_CURRENT, "state")
    data = await redis.hget(INCIDENT_CURRENT, "data")
    return {
        "state": state or "IDLE",
        "incident": json.loads(data) if data else None,
    }


@app.get("/api/events")
async def sse_events():
    async def event_stream():
        pubsub = redis.pubsub()
        await pubsub.subscribe(EVENTS_STATE)
        # Send current state immediately so a fresh client is in sync.
        state = await redis.hget(INCIDENT_CURRENT, "state")
        data = await redis.hget(INCIDENT_CURRENT, "data")
        yield (
            "data: "
            + json.dumps(
                {
                    "new_state": state or "IDLE",
                    "incident": json.loads(data) if data else None,
                }
            )
            + "\n\n"
        )
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    yield f"data: {msg['data']}\n\n"
        finally:
            await pubsub.unsubscribe(EVENTS_STATE)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/apply")
async def apply_fix():
    try:
        result = await supervisor.apply_fix()
        return {"status": "done", "verification": result}
    except ValueError as e:
        return {"status": "error", "error": str(e)}


@app.post("/api/force-detection")
async def force_detection():
    """Demo-safety override (spec §5.4)."""
    return {"status": "ok", "anomaly": await detector.force_anomaly()}


@app.post("/api/reset")
async def reset():
    await supervisor.reset()
    return {"status": "reset"}
