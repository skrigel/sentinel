"""Scenario: a blocking (synchronous) I/O call inside the async request path.

An async handler enriches each request by calling a third-party profile service
through a *synchronous* SDK. The blocking call is modeled with ``time.sleep``,
which is the key distinction from a compute-bound hot path: the loop is starved
(event-loop lag spikes) but CPU% stays near zero because the thread is parked,
not computing. Per CLAUDE.md #3, loop-lag is the primary signal here and CPU% is
what tells Sentinel this is blocking-I/O, not compute. The fix moves the call to
a thread via ``run_in_executor`` (or an async client).
"""

import asyncio
import time

SCENARIO = {
    "name": "blocking_profile_fetch",
    "tier": "resolvable",
    "expected_symptom": "cpu_hotpath",
    "expected_subcause": "sync_io_in_async_loop",
    "expected_blamed_op": "fetch_user_profile_blocking",
    "expected_outcome": "resolved",
    "expected_min_rss_growth_mb": 0,
    "expected_min_cpu_pct": 0,  # blocking I/O starves the loop WITHOUT raising CPU%
    "decline_reason_keywords": [],
    "description": "A synchronous profile-service SDK call (time.sleep) blocks the async loop with low CPU.",
}


async def fetch_user_profile_blocking(user_id: int) -> dict:
    """Call a synchronous profile SDK from the async path (the bug)."""
    # BUG: blocking network call modeled as time.sleep -> parks the whole loop.
    time.sleep(0.18)  # ~180 ms synchronous round trip per request
    return {"user_id": user_id, "tier": "gold" if user_id % 3 == 0 else "std"}


async def _heartbeat(stop: asyncio.Event) -> None:
    while not stop.is_set():
        await asyncio.sleep(0.05)


async def _serve(duration_seconds: int) -> None:
    stop = asyncio.Event()
    beat = asyncio.create_task(_heartbeat(stop))
    deadline = time.time() + duration_seconds
    user_id = 0
    try:
        while time.time() < deadline:
            await fetch_user_profile_blocking(user_id)
            user_id += 1
            await asyncio.sleep(0.02)
    finally:
        stop.set()
        await beat


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_serve(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
