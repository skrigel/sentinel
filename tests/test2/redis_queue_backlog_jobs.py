"""Scenario (GRACEFUL DECLINE): a Redis work queue that backs up.

A producer enqueues jobs onto a Redis list far faster than a single slow worker
drains them. The symptom is real -- memory pressure builds -- but it builds *in
Redis*, not in the victim process: the producer's own RSS stays flat. Sentinel's
attributor (which ranks per-op tracemalloc inside the process) finds nothing to
blame, and the honest verdict is REPORT_UNRESOLVED pointing at the external queue
(scale consumers / add backpressure), not a code fix in the watched process.

Requires a reachable Redis (``REDIS_URL``, default redis://localhost:6379/0). The
scenario namespaces its key and deletes it on exit so it leaves no residue.
"""

import asyncio
import json
import os
import time

SCENARIO = {
    "name": "redis_jobs_backlog",
    "tier": "graceful_decline",
    "expected_symptom": "redis_pressure",
    "expected_subcause": "redis_queue_backlog",
    "expected_blamed_op": None,
    "expected_outcome": "report_unresolved",
    "expected_min_rss_growth_mb": 0,   # process RSS stays flat; growth is in Redis
    "expected_min_cpu_pct": 0,
    "decline_reason_keywords": ["redis", "backlog", "queue", "external", "process rss"],
    "description": "Jobs are pushed to a Redis list faster than consumed; Redis grows while process RSS stays flat.",
}

_QUEUE_KEY = "scenario:redis_jobs_backlog:queue"


def _make_job(seq: int) -> str:
    # ~64 KB job document pushed into Redis (lives in Redis memory, not ours).
    return json.dumps({"seq": seq, "blob": "x" * (64 * 1024), "ts": time.time()})


async def _run_backlog(duration_seconds: int) -> None:
    try:
        import redis.asyncio as aioredis
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("redis_queue_backlog scenario requires the redis package") from exc

    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client = aioredis.from_url(url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:  # pragma: no cover - environment guard
        await client.aclose()
        raise RuntimeError(f"redis_queue_backlog scenario needs a reachable Redis at {url}") from exc

    deadline = time.time() + duration_seconds
    seq = 0
    try:
        while time.time() < deadline:
            # Producer: push a burst of jobs every tick (fast).
            async with client.pipeline(transaction=False) as pipe:
                for _ in range(40):
                    pipe.rpush(_QUEUE_KEY, _make_job(seq))
                    seq += 1
                await pipe.execute()
            # Consumer: drain only a handful (slow) -> net backlog grows in Redis.
            for _ in range(5):
                await client.lpop(_QUEUE_KEY)
            await asyncio.sleep(0.2)
    finally:
        await client.delete(_QUEUE_KEY)
        await client.aclose()


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_run_backlog(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
