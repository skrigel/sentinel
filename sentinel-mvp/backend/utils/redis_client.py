"""Shared async Redis client + small stream-reading helpers."""

import asyncio
import contextlib
import os

import redis.asyncio as aioredis
import redis.exceptions as redis_exc

from .redis_keys import METRICS_RSS

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# decode_responses=True: everything is str, which is what the agents expect.
# health_check_interval keeps the socket warm so long-idle pub/sub subscriptions
# don't get reaped between incident transitions.
redis = aioredis.from_url(REDIS_URL, decode_responses=True, health_check_interval=30)


async def iter_pubsub_messages(channel: str, poll_timeout: float = 1.0):
    """Yield messages from `channel`, resilient to idle read timeouts and
    transient disconnects.

    Yields ``None`` on each idle tick (no message within ``poll_timeout``) so
    callers can emit heartbeats; yields the raw message dict when a real message
    arrives. On a connection/timeout error it resubscribes instead of dying —
    important because a dead listener silently stalls the Supervisor.

    Uses ``get_message(timeout=...)`` rather than ``listen()`` on purpose: a
    user-supplied timeout makes an idle read return ``None`` instead of raising
    ``TimeoutError`` (see redis ``Connection.read_response``).
    """
    while True:
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(channel)
            while True:
                try:
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=poll_timeout
                    )
                except (redis_exc.TimeoutError, redis_exc.ConnectionError):
                    break  # fall through to resubscribe
                yield msg  # None on idle, dict on a real message
        finally:
            with contextlib.suppress(Exception):
                await pubsub.reset()
        await asyncio.sleep(poll_timeout)  # backoff before resubscribing


async def get_last_n_rss(n: int):
    """Return up to n RSS samples for the current victim PID, oldest-first.

    Segmenting by PID stops a victim restart discontinuity from poisoning
    RSS slope/R² calculations.
    """
    # XREVRANGE gives newest-first. Read extra entries so a short current run
    # after restart can be found without letting older-pid samples leak in.
    entries = await redis.xrevrange(METRICS_RSS, count=max(n * 4, 200))
    unset = object()
    current_pid = unset
    samples = []  # newest-first while building
    for _id, fields in entries:
        try:
            ts = float(fields["timestamp"])
            rss = int(float(fields["rss"]))
        except (KeyError, ValueError):
            continue
        pid = fields.get("pid")
        if current_pid is unset:
            current_pid = pid
        if pid != current_pid:
            break
        samples.append({"timestamp": ts, "rss": rss})
        if len(samples) >= n:
            break
    samples.reverse()
    return samples
