"""Scenario: an event consumer that never clears its pending-ack map.

A Kafka-style consumer drains batches of messages off a topic. For each message
it records an entry in a ``_PENDING_ACKS`` dict so it can ack later -- but the ack
path was never wired up, so the dict accumulates one entry (carrying the message
payload) per message forever. This is a second unbounded-collection variant: the
growth is *bursty* (batch-shaped), the container is a *dict* keyed by offset (not
a list), the payload is message bytes, and the control flow is a drain loop.
tracemalloc blames ``consume_event``; the fix pops acked offsets.
"""

import asyncio
import time

SCENARIO = {
    "name": "event_consumer_unbounded",
    "tier": "resolvable",
    "expected_symptom": "memory_leak",
    "expected_subcause": "unbounded_collection",
    "expected_blamed_op": "consume_event",
    "expected_outcome": "resolved",
    "expected_min_rss_growth_mb": 40,
    "expected_min_cpu_pct": 0,
    "decline_reason_keywords": [],
    "description": "A consumer's pending-ack dict accumulates every message's payload because acks never fire.",
}

# Offset -> in-flight message payload. BUG: entries are never popped after acking.
_PENDING_ACKS: dict = {}


async def consume_event(offset: int, payload: bytes) -> int:
    """Track an in-flight message for later acking; never released (the bug)."""
    _PENDING_ACKS[offset] = {
        "payload": payload,            # ~1 MB message body retained
        "received_at": time.time(),
        "attempts": 0,
    }
    # BUG: the matching `_PENDING_ACKS.pop(offset)` on successful ack is missing.
    return len(_PENDING_ACKS)


async def _drain_topic(duration_seconds: int) -> None:
    deadline = time.time() + duration_seconds
    offset = 0
    while time.time() < deadline:
        # Poll returns a burst of messages, then we idle briefly (batchy growth).
        batch_size = 6 + (offset % 5)
        for _ in range(batch_size):
            await consume_event(offset, payload=bytes(1024 * 1024))
            offset += 1
        await asyncio.sleep(0.75)


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_drain_topic(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
