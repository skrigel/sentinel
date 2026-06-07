"""FastAPI app: hosts the 4 agents as asyncio tasks, exposes metrics/incident
REST + an SSE stream, and the human-in-the-loop apply endpoint.

Event flow (spec §3.2): detector -> events:anomaly -> attributor ->
events:enriched -> diagnostician -> events:proposal. The Supervisor subscribes
to all three to drive the state machine; the SSE endpoint relays events:state.
"""

import asyncio
import contextlib
import io
import json
import os
import time
import zipfile

from fastapi import File, FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents import attributor, detector, diagnostician
from agents.supervisor import Supervisor
from utils.activity_db import fetch_activity, fetch_incidents, init_activity_db
from utils.agent_store import (
    DEFAULT_AGENT_ID,
    create_agent,
    delete_agent,
    get_agent_source,
    get_primary_monitored_agent,
    init_agent_store,
    list_agents,
    update_agent,
)
from utils.redis_client import (
    get_last_n_rss,
    get_last_n_rss_by_agent,
    iter_pubsub_messages,
    redis,
)
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
    VICTIM_AGENT_ID,
    VICTIM_AGENT_VERSION,
    VICTIM_MODE,
)
from utils.weave_client import init_weave

# init_weave()
ORCHESTRATOR = os.environ.get("ORCHESTRATOR", "legacy")
ACTIVE_AGENT_PATH = os.environ.get("ACTIVE_AGENT_PATH", "/data/active_agent.py")

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


class AgentUpdate(BaseModel):
    display_name: str | None = None
    monitored: bool | None = None
    entry_point: str | None = None


SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".txt",
    ".md",
}


def _source_text_from_upload(filename: str, raw: bytes) -> str:
    if filename.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                parts = []
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename
                    if "__pycache__" in name or "node_modules/" in name:
                        continue
                    if os.path.splitext(name)[1].lower() not in SOURCE_EXTENSIONS:
                        continue
                    try:
                        text = zf.read(info).decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                    parts.append(f"# file: {name}\n{text.rstrip()}\n")
        except zipfile.BadZipFile as e:
            raise HTTPException(status_code=400, detail=f"{filename} is not a valid zip") from e
        if not parts:
            raise HTTPException(
                status_code=400,
                detail=f"{filename} did not contain any UTF-8 source files",
            )
        return "\n".join(parts)

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"{filename or 'agent'} is not valid UTF-8 source",
        ) from e


def _is_runnable_victim_agent(source_text: str | None) -> bool:
    return bool(source_text and "def _make_op" in source_text)


def _with_runtime_status(agent: dict, runnable: bool, active: bool) -> dict:
    if active:
        return {
            **agent,
            "runtime_status": "running",
            "runtime_message": "Running in the victim loop.",
        }
    if runnable:
        return {
            **agent,
            "runtime_status": "ready",
            "runtime_message": "Ready to run when selected.",
        }
    return {
        **agent,
        "runtime_status": "source_only",
        "runtime_message": (
            "Uploaded for source diagnosis only. To run in the victim loop, "
            "the file must expose _make_op(redis_client)."
        ),
    }


async def _activate_agent_runtime(agent_id: str) -> None:
    agent, source_text = await get_agent_source(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    os.makedirs(os.path.dirname(ACTIVE_AGENT_PATH), exist_ok=True)
    if agent["id"] == DEFAULT_AGENT_ID:
        try:
            os.remove(ACTIVE_AGENT_PATH)
        except OSError:
            pass
    else:
        if not _is_runnable_victim_agent(source_text):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Selected agent cannot run as the victim loop. Upload a Python "
                    "source file exposing _make_op(redis_client), like the original victim."
                ),
            )
        tmp_path = f"{ACTIVE_AGENT_PATH}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(source_text)
        os.replace(tmp_path, ACTIVE_AGENT_PATH)

    await redis.set(VICTIM_AGENT_ID, agent["id"])
    await redis.set(VICTIM_AGENT_VERSION, f"{agent['id']}:{time.time()}")
    await redis.set(VICTIM_MODE, "buggy")
    await redis.delete(ATTRIB_MEM, ATTRIB_INVOCATIONS)


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
    await init_agent_store()
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


@app.get("/api/agents")
async def get_agents():
    """All uploaded/default agents and whether Sentinel should monitor them."""
    return await list_agents()


@app.post("/api/agents")
async def upload_agents(
    files: list[UploadFile] = File(...),
    entry_point: str = Form(...),
    display_name: str | None = Form(None),
):
    """Upload one or more agent source files/bundles and mark them monitored."""
    agents = []
    for file in files:
        raw = await file.read()
        filename = file.filename or "agent.py"
        source_text = _source_text_from_upload(filename, raw)
        runnable = _is_runnable_victim_agent(source_text)
        agent = await create_agent(
            filename,
            source_text,
            file.content_type,
            entry_point,
            display_name,
            monitored=runnable,
        )
        if runnable:
            await _activate_agent_runtime(agent["id"])
        else:
            primary = await get_primary_monitored_agent()
            if not primary or primary["id"] == agent["id"]:
                await update_agent(DEFAULT_AGENT_ID, monitored=True)
                primary = await get_primary_monitored_agent()
            if primary:
                await _activate_agent_runtime(primary["id"])
        agents.append(_with_runtime_status(agent, runnable, runnable))
    return agents


@app.patch("/api/agents/{agent_id}")
async def patch_agent(agent_id: str, body: AgentUpdate):
    agent = await update_agent(
        agent_id,
        display_name=body.display_name,
        monitored=body.monitored,
        entry_point=body.entry_point,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.get("monitored"):
        await _activate_agent_runtime(agent["id"])
    return agent


@app.delete("/api/agents/{agent_id}")
async def remove_agent(agent_id: str):
    if not await delete_agent(agent_id):
        raise HTTPException(
            status_code=404, detail="Agent not found or cannot be deleted"
        )
    primary = await get_primary_monitored_agent()
    if primary:
        await _activate_agent_runtime(primary["id"])
    return {"status": "deleted"}


@app.get("/api/agents/metrics")
async def get_agent_metrics(n: int = 100):
    """Last RSS samples grouped by monitored agent id."""
    agents = await list_agents()
    monitored_agents = [agent for agent in agents if agent.get("monitored")]
    primary_agent = await get_primary_monitored_agent()
    agent_ids = [agent["id"] for agent in monitored_agents]
    grouped = await get_last_n_rss_by_agent(
        n, agent_ids, legacy_agent_id=primary_agent["id"]
    )
    return [
        {
            "agent": agent,
            "samples": grouped.get(agent["id"], []),
        }
        for agent in monitored_agents
    ]

@app.get("/api/activity")
async def get_activity(limit: int = 300, offset: int = 0):
    """Durable, cross-incident agent activity (SQLite), oldest-first per page."""
    return await fetch_activity(limit=limit, offset=offset)


@app.get("/api/interventions")
async def get_interventions(limit: int = 50, agent_id: str | None = None):
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
