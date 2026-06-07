"""FastAPI app: hosts the 4 agents as asyncio tasks, exposes metrics/incident
REST + an SSE stream, and the human-in-the-loop apply endpoint.

Event flow (spec §3.2): detector -> events:anomaly -> attributor ->
events:enriched -> diagnostician -> events:proposal. The Supervisor subscribes
to all three to drive the state machine; the SSE endpoint relays events:state.
"""

import asyncio
import contextlib
import json
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents import attributor, detector, diagnostician
from agents.supervisor import Supervisor
from utils.activity_db import fetch_activity, fetch_incidents, init_activity_db
from utils.redis_client import get_last_n_rss, iter_pubsub_messages, redis
from utils.redis_keys import (
    ATTRIB_INVOCATIONS,
    ATTRIB_MEM,
    EVENTS_ANOMALY,
    EVENTS_ENRICHED,
    EVENTS_PROPOSAL,
    EVENTS_STATE,
    INCIDENT_CURRENT,
    SETTINGS_AUTO_APPROVE,
    TIMELINE_EVENTS,
    VICTIM_MODE,
)
from utils.weave_client import init_weave

# init_weave()
ORCHESTRATOR = os.environ.get("ORCHESTRATOR", "legacy")

supervisor = Supervisor()
_tasks: list[asyncio.Task] = []
_graph_runner = None


def _get_graph_runner():
    global _graph_runner
    if _graph_runner is None:
        from graph.runner import GraphRunner

        _graph_runner = GraphRunner()
    return _graph_runner


async def _auto_approve_enabled() -> bool:
    """Settings override (CLAUDE.md HITL gate): when on, fixes apply without a human."""
    try:
        return (await redis.get(SETTINGS_AUTO_APPROVE)) == "1"
    except Exception:
        return False


# After a successful fix, hold RESOLVED briefly so the UI can show recovery, then
# return the state machine to its IDLE start state (durable history lives in SQLite).
RESOLVED_LINGER_S = 6.0


def _was_recovered(result: dict) -> bool:
    verification = (result or {}).get("verification") or {}
    return bool(verification.get("recovered"))


async def _return_to_idle_after(delay: float = RESOLVED_LINGER_S) -> None:
    await asyncio.sleep(delay)
    await redis.hset(
        INCIDENT_CURRENT, mapping={"state": "IDLE", "data": json.dumps({})}
    )
    await redis.publish(
        EVENTS_STATE, json.dumps({"new_state": "IDLE", "incident": {}})
    )
    if ORCHESTRATOR == "graph":
        await _get_graph_runner().reset()


async def _anomaly_listener():
    """events:anomaly -> Supervisor + kick off attribution chain."""
    async for msg in iter_pubsub_messages(EVENTS_ANOMALY):
        if msg is None:
            continue
        data = json.loads(msg["data"])
        await supervisor.on_anomaly(data)
        # Deterministic handoff: attribute, then diagnose.
        enriched = await attributor.attribute_anomaly(data)
        await diagnostician.diagnose(enriched)


async def _enriched_listener():
    async for msg in iter_pubsub_messages(EVENTS_ENRICHED):
        if msg is None:
            continue
        await supervisor.on_enriched(json.loads(msg["data"]))


async def _proposal_listener():
    async for msg in iter_pubsub_messages(EVENTS_PROPOSAL):
        if msg is None:
            continue
        await supervisor.on_proposal(json.loads(msg["data"]))
        if await _auto_approve_enabled():
            try:
                await supervisor.apply_fix()
            except ValueError:
                pass  # not in an applyable state; ignore


async def _graph_anomaly_listener():
    async for msg in iter_pubsub_messages(EVENTS_ANOMALY):
        if msg is None:
            continue
        runner = _get_graph_runner()
        # Fresh incident -> fresh timeline so stale node events don't bleed across.
        await redis.delete(TIMELINE_EVENTS)
        result = await runner.start_from_anomaly(json.loads(msg["data"]))
        # The graph interrupts before apply for human approval; auto-approve
        # resumes it deterministically (no LLM on the coordination path).
        if result.get("status") == "AWAITING_APPROVAL" and await _auto_approve_enabled():
            try:
                applied = await runner.approve_and_apply()
                if _was_recovered(applied):
                    asyncio.create_task(_return_to_idle_after())
            except Exception:
                pass


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    init_weave()
    await init_activity_db()
    _tasks.append(asyncio.create_task(detector.detect_anomaly()))
    if ORCHESTRATOR == "graph":
        _tasks.append(asyncio.create_task(_graph_anomaly_listener()))
    else:
        await supervisor.reset()
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


@app.get("/api/timeline")
async def get_timeline(n: int = 100):
    """Per-node agent activity for the current incident, oldest-first.

    Each event is one graph node's decision (node, decision, reason, confidence,
    status), so the frontend timeline reflects real backend agent state.
    """
    entries = await redis.xrevrange(TIMELINE_EVENTS, count=n)
    events = []
    for _id, fields in entries:
        events.append(
            {
                "node": fields.get("node"),
                "decision": fields.get("decision"),
                "reason": fields.get("reason"),
                "confidence": fields.get("confidence") or None,
                "status": fields.get("status") or None,
                "incident_id": fields.get("incident_id") or None,
                "timestamp": float(fields.get("timestamp") or 0.0),
            }
        )
    events.reverse()
    return events


@app.get("/api/activity")
async def get_activity(limit: int = 300, offset: int = 0):
    """Durable, cross-incident agent activity (SQLite), oldest-first per page."""
    return await fetch_activity(limit=limit, offset=offset)


@app.get("/api/interventions")
async def get_interventions(limit: int = 50):
    """Durable per-incident snapshots (newest-first) for the Agent Activity feed."""
    return await fetch_incidents(limit=limit)


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
        # iter_pubsub_messages yields None on idle ticks; emit an SSE comment
        # heartbeat so the connection stays warm and never dies on a quiet channel.
        async for msg in iter_pubsub_messages(EVENTS_STATE):
            if msg is None:
                yield ": keepalive\n\n"
                continue
            yield f"data: {msg['data']}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/apply")
async def apply_fix():
    try:
        if ORCHESTRATOR == "graph":
            result = await _get_graph_runner().approve_and_apply()
            if _was_recovered(result):
                asyncio.create_task(_return_to_idle_after())
            return {"status": "done", "verification": result.get("verification")}
        result = await supervisor.apply_fix()
        if supervisor.state == "RESOLVED":
            asyncio.create_task(_return_to_idle_after())
        return {"status": "done", "verification": result}
    except ValueError as e:
        return {"status": "error", "error": str(e)}


class SettingsUpdate(BaseModel):
    auto_approve: bool


@app.get("/api/settings")
async def get_settings():
    return {"auto_approve": await _auto_approve_enabled()}


@app.post("/api/settings")
async def update_settings(body: SettingsUpdate):
    await redis.set(SETTINGS_AUTO_APPROVE, "1" if body.auto_approve else "0")
    return {"auto_approve": body.auto_approve}


@app.post("/api/force-detection")
async def force_detection():
    """Demo-safety override (spec §5.4)."""
    return {"status": "ok", "anomaly": await detector.force_anomaly()}


@app.post("/api/reset")
async def reset():
    if ORCHESTRATOR == "graph":
        await _get_graph_runner().reset()
        await redis.set(VICTIM_MODE, "buggy")
        await redis.delete(ATTRIB_MEM, ATTRIB_INVOCATIONS, TIMELINE_EVENTS)
        await redis.hset(
            INCIDENT_CURRENT,
            mapping={"state": "IDLE", "data": json.dumps({})},
        )
        await redis.publish(
            EVENTS_STATE,
            json.dumps({"new_state": "IDLE", "incident": {}}),
        )
        return {"status": "reset"}
    await supervisor.reset()
    await redis.delete(TIMELINE_EVENTS)
    return {"status": "reset"}
