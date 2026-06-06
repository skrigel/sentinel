"""Shared async Redis client + small stream-reading helpers."""

import os

import redis.asyncio as aioredis

from .redis_keys import METRICS_RSS

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# decode_responses=True: everything is str, which is what the agents expect.
redis = aioredis.from_url(REDIS_URL, decode_responses=True)


async def get_last_n_rss(n: int):
    """Return up to the last n RSS samples, oldest-first.

    Each sample: {"timestamp": float, "rss": int}.
    """
    # XREVRANGE gives newest-first; reverse to oldest-first.
    entries = await redis.xrevrange(METRICS_RSS, count=n)
    samples = []
    for _id, fields in reversed(entries):
        try:
            samples.append(
                {"timestamp": float(fields["timestamp"]), "rss": int(float(fields["rss"]))}
            )
        except (KeyError, ValueError):
            continue
    return samples
