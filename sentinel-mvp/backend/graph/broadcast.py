"""Guarded Redis broadcast helpers for graph nodes."""

import json
import time
from typing import Any

from utils.redis_client import redis
from utils.redis_keys import EVENTS_NARRATION, EVENTS_STATE, INCIDENT_CURRENT


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
    except Exception:
        pass


async def narrate(
    node: str,
    decision: str,
    reason: str,
    confidence: float | None = None,
) -> None:
    try:
        payload = {
            "node": node,
            "decision": decision,
            "reason": reason,
            "confidence": confidence,
            "timestamp": time.time(),
        }
        await redis.publish(EVENTS_NARRATION, json.dumps(payload, default=str))
    except Exception:
        pass
