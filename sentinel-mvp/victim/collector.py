"""RSS + event-loop-lag collector.

Runs as an asyncio task alongside the victim loop. RSS slope is the leak alarm
(CLAUDE.md #2); loop-lag is captured for the CPU beat (Phase B) but emitted now
so the stream exists.
"""

import asyncio
import os
import time

import psutil

from redis_keys import METRICS_LOOPLAG, METRICS_MAXLEN, METRICS_RSS

SAMPLE_INTERVAL_S = 2.0


async def measure_loop_lag() -> float:
    """ms the event loop was delayed beyond a requested 50ms sleep."""
    requested = 0.05
    t0 = time.perf_counter()
    await asyncio.sleep(requested)
    actual = time.perf_counter() - t0
    return max(0.0, (actual - requested) * 1000.0)


async def collector_task(redis_client):
    proc = psutil.Process(os.getpid())
    while True:
        rss = proc.memory_info().rss
        lag = await measure_loop_lag()
        ts = time.time()

        try:
            await redis_client.xadd(
                METRICS_RSS,
                {"timestamp": ts, "rss": rss, "pid": proc.pid},
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

        await asyncio.sleep(SAMPLE_INTERVAL_S)
