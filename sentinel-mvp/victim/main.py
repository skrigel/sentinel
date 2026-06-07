"""Victim entrypoint: an instrumented document-QA agent loop.

Lifecycle: read the desired mode from Redis (set by Sentinel's Supervisor at
"apply" time), run the instrumented loop, and self-exit when the mode flips so
Docker restarts us cleanly in the new mode (CLAUDE.md #5: apply == flag-flip,
not hot-reload; a leaked process can't re-baseline mid-run).
"""

import asyncio
import importlib.util
import os
import tracemalloc

import redis.asyncio as aioredis
import weave

from collector import collector_task
from redis_keys import VICTIM_AGENT_ID, VICTIM_AGENT_VERSION, VICTIM_MODE

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
LOOP_SLEEP_S = 1.0
ACTIVE_AGENT_PATH = os.environ.get("ACTIVE_AGENT_PATH", "/data/active_agent.py")


async def resolve_startup_mode(r) -> str:
    """The Redis flag wins; fall back to the env default on first boot."""
    mode = await r.get(VICTIM_MODE)
    if mode is None:
        mode = os.environ.get("VICTIM_MODE", "buggy")
        await r.set(VICTIM_MODE, mode)
    os.environ["_RESOLVED_MODE"] = mode
    return mode


async def resolve_agent_version(r) -> str:
    version = await r.get(VICTIM_AGENT_VERSION)
    if version is None:
        version = "victim:built-in"
        await r.set(VICTIM_AGENT_VERSION, version)
    if await r.get(VICTIM_AGENT_ID) is None:
        await r.set(VICTIM_AGENT_ID, "victim")
    return version


def load_make_op():
    """Load the selected victim ops module, preserving the original _make_op API."""
    if os.path.exists(ACTIVE_AGENT_PATH):
        spec = importlib.util.spec_from_file_location(
            "active_agent_ops", ACTIVE_AGENT_PATH
        )
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            make_op = getattr(module, "_make_op", None)
            if make_op:
                print(f"[victim] loaded active agent from {ACTIVE_AGENT_PATH}")
                return make_op
        print(f"[victim] active agent at {ACTIVE_AGENT_PATH} is invalid; using built-in ops")

    from ops import _make_op

    print("[victim] loaded built-in ops")
    return _make_op


async def runtime_watcher(r, current_mode: str, current_agent_version: str):
    """Exit if mode or selected agent changes; Docker restarts a clean process."""
    while True:
        await asyncio.sleep(2.0)
        mode = await r.get(VICTIM_MODE)
        if mode is not None and mode != current_mode:
            print(f"[victim] mode flip {current_mode} -> {mode}; exiting to restart")
            os._exit(0)
        agent_version = await r.get(VICTIM_AGENT_VERSION)
        if agent_version is not None and agent_version != current_agent_version:
            print("[victim] selected agent changed; exiting to restart")
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
    agent_version = await resolve_agent_version(r)
    print(f"[victim] starting in {mode!r} mode (agent_version={agent_version})")

    _make_op = load_make_op()
    initialize, process_batch, cleanup = _make_op(r)

    asyncio.create_task(collector_task(r))
    asyncio.create_task(runtime_watcher(r, mode, agent_version))

    while True:
        await initialize()
        await process_batch()
        await cleanup()
        await asyncio.sleep(LOOP_SLEEP_S)


if __name__ == "__main__":
    asyncio.run(main())
