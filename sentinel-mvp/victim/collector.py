"""RSS + event-loop-lag collector.

Runs as an asyncio task alongside the victim loop. RSS slope is the leak alarm
(CLAUDE.md #2); loop-lag is captured for the CPU beat (Phase B) but emitted now
so the stream exists.
"""

import asyncio
import os
import time

import psutil

from redis_keys import (
    METRICS_LOOPLAG,
    METRICS_MAXLEN,
    METRICS_PROCSTAT,
    METRICS_RSS,
    VICTIM_AGENT_ID,
)

SAMPLE_INTERVAL_S = 2.0
USS_EVERY_N = 5


async def measure_loop_lag() -> float:
    """ms the event loop was delayed beyond a requested 50ms sleep."""
    requested = 0.05
    t0 = time.perf_counter()
    await asyncio.sleep(requested)
    actual = time.perf_counter() - t0
    return max(0.0, (actual - requested) * 1000.0)


def _safe_cpu_percent(proc):
    try:
        return proc.cpu_percent()
    except Exception:
        return None


def _safe_num_threads(proc):
    try:
        return proc.num_threads()
    except Exception:
        return None


def _safe_num_fds(proc):
    try:
        return proc.num_fds()
    except AttributeError:
        try:
            return proc.num_handles()
        except Exception:
            return None
    except Exception:
        return None


def _safe_uss(proc):
    try:
        return proc.memory_full_info().uss
    except Exception:
        return None


def _stream_value(value):
    return "" if value is None else value


async def collector_task(redis_client):
    proc = psutil.Process(os.getpid())
    cycle = 0
    last_uss = None
    while True:
        rss = proc.memory_info().rss
        lag = await measure_loop_lag()
        ts = time.time()
        if cycle % USS_EVERY_N == 0:
            last_uss = _safe_uss(proc)
        procstat = {
            "timestamp": ts,
            "pid": proc.pid,
            "uss": _stream_value(last_uss),
            "cpu_pct": _stream_value(_safe_cpu_percent(proc)),
            "num_fds": _stream_value(_safe_num_fds(proc)),
            "num_threads": _stream_value(_safe_num_threads(proc)),
        }

        try:
            agent_id = await redis_client.get(VICTIM_AGENT_ID) or "victim"
            await redis_client.xadd(
                METRICS_RSS,
                {"timestamp": ts, "rss": rss, "pid": proc.pid, "agent_id": agent_id},
                maxlen=METRICS_MAXLEN,
                approximate=True,
            )
            await redis_client.xadd(
                METRICS_LOOPLAG,
                {"timestamp": ts, "lag": lag, "pid": proc.pid},
                maxlen=METRICS_MAXLEN,
                approximate=True,
            )
        except Exception:
            # Losing Redis means we can't do our job; let the loop crash so
            # Docker restarts us (restart: always).
            raise

        try:
            await redis_client.xadd(
                METRICS_PROCSTAT,
                procstat,
                maxlen=METRICS_MAXLEN,
                approximate=True,
            )
        except Exception:
            pass

        cycle += 1
        await asyncio.sleep(SAMPLE_INTERVAL_S)
