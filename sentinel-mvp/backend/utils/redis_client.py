"""Shared async Redis client + small stream-reading helpers."""

import asyncio
import contextlib
import os

import redis.asyncio as aioredis
import redis.exceptions as redis_exc

from .redis_keys import METRICS_LOOPLAG, METRICS_PROCSTAT, METRICS_RSS

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


async def get_last_n_rss_by_agent(
    n: int, agent_ids: list[str], legacy_agent_id: str
) -> dict[str, list[dict]]:
    """Return RSS samples grouped by agent id, oldest-first per agent.

    New collectors can tag stream rows with ``agent_id``. Existing demo rows are
    untagged, so they are attributed to the current primary monitored agent.
    """
    wanted = set(agent_ids)
    grouped: dict[str, list[dict]] = {agent_id: [] for agent_id in agent_ids}
    if not wanted:
        return grouped
    current_pid_by_agent: dict[str, str | None] = {}
    entries = await redis.xrevrange(
        METRICS_RSS, count=max(n * 4 * max(len(wanted), 1), 200)
    )

    for _id, fields in entries:
        agent_id = fields.get("agent_id") or fields.get("agentId") or legacy_agent_id
        if agent_id not in wanted:
            continue
        if len(grouped[agent_id]) >= n:
            continue
        try:
            ts = float(fields["timestamp"])
            rss = int(float(fields["rss"]))
        except (KeyError, ValueError):
            continue

        pid = fields.get("pid")
        if agent_id not in current_pid_by_agent:
            current_pid_by_agent[agent_id] = pid
        if pid != current_pid_by_agent[agent_id]:
            continue
        grouped[agent_id].append({"timestamp": ts, "rss": rss})

    for samples in grouped.values():
        samples.reverse()
    return grouped


async def get_last_n_looplag(n: int):
    """Return up to n loop-lag samples for the current victim PID, oldest-first."""
    try:
        entries = await redis.xrevrange(METRICS_LOOPLAG, count=max(n * 4, 200))
    except Exception:
        return []
    unset = object()
    current_pid = unset
    samples = []  # newest-first while building
    for _id, fields in entries:
        try:
            ts = float(fields["timestamp"])
            lag = float(fields["lag"])
        except (KeyError, ValueError):
            continue
        pid = fields.get("pid")
        if current_pid is unset:
            current_pid = pid
        if pid != current_pid:
            break
        samples.append({"timestamp": ts, "lag": lag})
        if len(samples) >= n:
            break
    samples.reverse()
    return samples


def _optional_float(fields: dict, key: str):
    value = fields.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def get_last_n_procstat(n: int):
    """Return up to n process-stat samples for the current victim PID, oldest-first."""
    try:
        entries = await redis.xrevrange(METRICS_PROCSTAT, count=max(n * 4, 200))
    except Exception:
        return []
    unset = object()
    current_pid = unset
    samples = []  # newest-first while building
    for _id, fields in entries:
        try:
            ts = float(fields["timestamp"])
        except (KeyError, ValueError):
            continue
        pid = fields.get("pid")
        if current_pid is unset:
            current_pid = pid
        if pid != current_pid:
            break
        samples.append(
            {
                "timestamp": ts,
                "uss": _optional_float(fields, "uss"),
                "cpu_pct": _optional_float(fields, "cpu_pct"),
                "num_fds": _optional_float(fields, "num_fds"),
                "num_threads": _optional_float(fields, "num_threads"),
            }
        )
        if len(samples) >= n:
            break
    samples.reverse()
    return samples
