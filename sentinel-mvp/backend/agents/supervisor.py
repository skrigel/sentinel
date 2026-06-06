"""Supervisor: the thin deterministic state machine + gates (no LLM).

Owns the incident lifecycle, persists it to Redis (survives backend restarts),
and pushes every transition to the frontend by publishing to ``events:state``
(the SSE endpoint relays that channel). Applying a fix is a flag-flip
(CLAUDE.md #5): set victim:mode=fixed, wait for the clean restart, then measure
real recovery.
"""

import asyncio
import json
import time

import weave

from utils.redis_client import get_last_n_rss, redis
from utils.redis_keys import (
    EVENTS_STATE,
    INCIDENT_CURRENT,
    VICTIM_MODE,
)
from utils.stats import linregress

# Phase A lifecycle (shadow states skipped per CLAUDE.md #6).
STATES = ["IDLE", "DETECTED", "DIAGNOSED", "AWAITING_APPROVAL", "APPLYING", "RESOLVED", "FAILED"]

VERIFY_WAIT_S = 30
RECOVERY_REDUCTION_TARGET = 0.8  # slope must drop by >=80%
WINDOW_SAMPLES = 30


def _current_slope_from(samples):
    if len(samples) < 5:
        return 0.0
    slope, _ = linregress([s["timestamp"] for s in samples], [s["rss"] for s in samples])
    return slope


class Supervisor:
    def __init__(self):
        self.state = "IDLE"
        self.incident = {}
        self._detection_ts = None

    async def _persist_and_broadcast(self):
        await redis.hset(
            INCIDENT_CURRENT,
            mapping={"state": self.state, "data": json.dumps(self.incident)},
        )
        await redis.publish(
            EVENTS_STATE,
            json.dumps({"new_state": self.state, "incident": self.incident}),
        )

    async def on_anomaly(self, data: dict):
        self.state = "DETECTED"
        self.incident = {"anomaly": data}
        self._detection_ts = time.time()
        await self._persist_and_broadcast()

    async def on_enriched(self, data: dict):
        self.incident["enriched"] = data
        await self._persist_and_broadcast()

    async def on_proposal(self, data: dict):
        self.incident["proposal"] = data
        self.state = "DIAGNOSED"
        await self._persist_and_broadcast()
        await asyncio.sleep(1)
        self.state = "AWAITING_APPROVAL"
        await self._persist_and_broadcast()

    @weave.op()
    async def apply_fix(self):
        if self.state != "AWAITING_APPROVAL":
            raise ValueError(f"Cannot apply fix from state {self.state}")

        self.state = "APPLYING"
        await self._persist_and_broadcast()

        slope_before = self.incident.get("anomaly", {}).get("slope", 0.0) or 1.0

        # Flag-flip. Victim's mode_watcher sees this and self-exits; Docker
        # restarts it clean in fixed mode.
        await redis.set(VICTIM_MODE, "fixed")
        # Reset attribution so the fixed run re-baselines cleanly.
        await redis.delete("attrib:mem", "attrib:invocations")

        await asyncio.sleep(VERIFY_WAIT_S)

        samples = await get_last_n_rss(WINDOW_SAMPLES)
        slope_after = _current_slope_from(samples)
        reduction = 1 - (slope_after / slope_before) if slope_before else 0.0

        verification = {
            "slope_before": slope_before,
            "slope_after": slope_after,
            "reduction_pct": reduction * 100,
            "duration_seconds": (
                time.time() - self._detection_ts if self._detection_ts else None
            ),
        }
        self.incident["verification"] = verification

        if reduction >= RECOVERY_REDUCTION_TARGET:
            self.state = "RESOLVED"
        else:
            self.state = "FAILED"
        await self._persist_and_broadcast()
        return verification

    async def reset(self):
        self.state = "IDLE"
        self.incident = {}
        self._detection_ts = None
        await redis.set(VICTIM_MODE, "buggy")
        await redis.delete("attrib:mem", "attrib:invocations")
        await self._persist_and_broadcast()
