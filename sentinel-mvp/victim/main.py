"""Victim entrypoint: an instrumented document-QA agent loop.

Lifecycle: read the desired mode from Redis (set by Sentinel's Supervisor at
"apply" time), run the instrumented loop, and self-exit when the mode flips so
Docker restarts us cleanly in the new mode (CLAUDE.md #5: apply == flag-flip,
not hot-reload; a leaked process can't re-baseline mid-run).
"""

import asyncio
import os
import tracemalloc

import redis.asyncio as aioredis
import weave

from collector import collector_task
from ops import _make_op
from redis_keys import VICTIM_MODE

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
LOOP_SLEEP_S = 1.0


async def resolve_startup_mode(r) -> str:
    """The Redis flag wins; fall back to the env default on first boot."""
    mode = await r.get(VICTIM_MODE)
    if mode is None:
        mode = os.environ.get("VICTIM_MODE", "buggy")
        await r.set(VICTIM_MODE, mode)
    os.environ["_RESOLVED_MODE"] = mode
    return mode


async def mode_watcher(r, current_mode: str):
    """Exit the process if the mode flag changes (Docker restarts us)."""
    while True:
        await asyncio.sleep(2.0)
        mode = await r.get(VICTIM_MODE)
        if mode is not None and mode != current_mode:
            print(f"[victim] mode flip {current_mode} -> {mode}; exiting to restart")
            os._exit(0)


async def main():
    tracemalloc.start()

    # Weave tracing is best-effort: if the key is missing we still run.
    try:
        weave.init(os.environ.get("WEAVE_PROJECT", "sentinel") + "-victim")
    except Exception as e:
        print(f"[victim] weave.init failed ({e}); continuing without tracing")

    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    mode = await resolve_startup_mode(r)
    print(f"[victim] starting in {mode!r} mode")

    initialize, process_batch, cleanup = _make_op(r)

    asyncio.create_task(collector_task(r))
    asyncio.create_task(mode_watcher(r, mode))

    while True:
        await initialize()
        await process_batch()
        await cleanup()
        await asyncio.sleep(LOOP_SLEEP_S)


if __name__ == "__main__":
    asyncio.run(main())
