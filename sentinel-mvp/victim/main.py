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
from redis_keys import VICTIM_BEAT, VICTIM_MODE

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


def _normalize_beat(beat: str | None) -> str:
    return beat if beat in {"memory", "cpu"} else "memory"


async def resolve_startup_beat(r) -> str:
    """The Redis beat flag wins; fall back to env, then memory."""
    beat = await r.get(VICTIM_BEAT)
    if beat is None:
        beat = _normalize_beat(os.environ.get("VICTIM_BEAT", "memory"))
        await r.set(VICTIM_BEAT, beat)
    else:
        beat = _normalize_beat(beat)
    os.environ["_RESOLVED_BEAT"] = beat
    return beat


async def mode_watcher(r, current_mode: str, current_beat: str):
    """Exit the process if mode or beat changes (Docker restarts us)."""
    while True:
        await asyncio.sleep(2.0)
        mode = await r.get(VICTIM_MODE)
        if mode is not None and mode != current_mode:
            print(f"[victim] mode flip {current_mode} -> {mode}; exiting to restart")
            os._exit(0)
        beat = await r.get(VICTIM_BEAT)
        if beat is not None and _normalize_beat(beat) != current_beat:
            print(f"[victim] beat flip {current_beat} -> {beat}; exiting to restart")
            os._exit(0)


async def main():
    # Weave tracing is best-effort: if the key is missing we still run.
    try:
        weave.init(os.environ.get("WEAVE_PROJECT", "sentinel") + "-victim")
    except Exception as e:
        print(f"[victim] weave.init failed ({e}); continuing without tracing")

    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    mode = await resolve_startup_mode(r)
    beat = await resolve_startup_beat(r)
    if beat != "cpu":
        tracemalloc.start()
    print(f"[victim] starting in {mode!r} mode with {beat!r} beat")

    initialize, process_batch, retrieve, cleanup = _make_op(r)

    asyncio.create_task(collector_task(r))
    asyncio.create_task(mode_watcher(r, mode, beat))

    while True:
        await initialize()
        await process_batch()
        await retrieve()
        await cleanup()
        await asyncio.sleep(LOOP_SLEEP_S)


if __name__ == "__main__":
    asyncio.run(main())
