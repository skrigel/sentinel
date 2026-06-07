"""Guarded Redis broadcast helpers for graph nodes."""

import json
import time
from typing import Any

from utils.activity_db import record_activity, record_incident
from utils.redis_client import redis
from utils.redis_keys import (
    EVENTS_NARRATION,
    EVENTS_STATE,
    INCIDENT_CURRENT,
    TIMELINE_EVENTS,
    TIMELINE_MAXLEN,
)


def _serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _serializable(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_serializable(item) for item in value]
    if isinstance(value, tuple):
        return [_serializable(item) for item in value]
    return value


async def broadcast(state: dict) -> None:
    try:
        payload = _serializable(state)
        status = payload.get("status", "UNKNOWN")
        encoded = json.dumps(payload, default=str)
        await redis.hset(INCIDENT_CURRENT, mapping={"state": status, "data": encoded})
        await redis.publish(
            EVENTS_STATE,
            json.dumps({"new_state": status, "incident": payload}, default=str),
        )
        # Persist the incident snapshot so resolved interventions stay in the feed.
        await record_incident(payload)
    except Exception:
        pass


async def narrate(
    node: str,
    decision: str,
    reason: str,
    confidence: float | None = None,
    status: str | None = None,
    incident_id: str | None = None,
) -> None:
    """Publish a per-node activity event and persist it to the timeline stream so
    the frontend can render the real agent activity log (not a synthesized one)."""
    try:
        ts = time.time()
        payload = {
            "node": node,
            "decision": decision,
            "reason": reason,
            "confidence": confidence,
            "status": status,
            "incident_id": incident_id,
            "timestamp": ts,
        }
        await redis.publish(EVENTS_NARRATION, json.dumps(payload, default=str))
        # Stream fields must be strings; None -> "".
        await redis.xadd(
            TIMELINE_EVENTS,
            {
                "node": node,
                "decision": decision,
                "reason": reason,
                "confidence": "" if confidence is None else str(confidence),
                "status": status or "",
                "incident_id": incident_id or "",
                "timestamp": str(ts),
            },
            maxlen=TIMELINE_MAXLEN,
            approximate=True,
        )
        # Durable cross-incident history (SQLite).
        await record_activity(
            {
                "node": node,
                "decision": decision,
                "reason": reason,
                "confidence": None if confidence is None else str(confidence),
                "status": status,
                "incident_id": incident_id,
                "timestamp": ts,
            }
        )
    except Exception:
        pass
