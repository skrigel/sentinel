"""Scenario: synchronous JSON serialization blocking the event loop.

An API handler serializes a large, deeply nested response with a synchronous
``json.dumps`` directly in the async request path. The CPU-bound encode runs for
tens of ms per request with no ``await``, so a concurrent heartbeat task starves:
event-loop lag spikes and CPU% climbs. This is a compute-bound hot path, not a
leak (RSS stays flat). Sentinel blames ``serialize_response_payload``; the fix
offloads the encode to ``run_in_executor``.
"""

import asyncio
import json
import time

SCENARIO = {
    "name": "blocking_json_serialize",
    "tier": "resolvable",
    "expected_symptom": "cpu_hotpath",
    "expected_subcause": "event_loop_blocking",
    "expected_blamed_op": "serialize_response_payload",
    "expected_outcome": "resolved",
    "expected_min_rss_growth_mb": 0,
    "expected_min_cpu_pct": 50,
    "decline_reason_keywords": [],
    "description": "A synchronous json.dumps of a large nested dict blocks the async loop every request.",
}


def _build_large_document() -> dict:
    # A deeply nested ~realistic API response: 600 records, each with nested rows.
    return {
        "page": {
            "records": [
                {
                    "id": r,
                    "attrs": {f"f{c}": (r * c) % 997 for c in range(60)},
                    "rows": [[r, c, r * c, float(r) / (c + 1)] for c in range(40)],
                }
                for r in range(600)
            ]
        }
    }


async def serialize_response_payload(document: dict) -> int:
    """Encode the response synchronously in the loop (the bug)."""
    # BUG: CPU-bound json.dumps with no await -> blocks every other coroutine.
    encoded = json.dumps(document)
    return len(encoded)


async def _heartbeat(stop: asyncio.Event) -> None:
    # A co-resident task whose timing reveals loop lag when the encode blocks.
    while not stop.is_set():
        await asyncio.sleep(0.05)


async def _serve(duration_seconds: int) -> None:
    stop = asyncio.Event()
    beat = asyncio.create_task(_heartbeat(stop))
    document = _build_large_document()
    deadline = time.time() + duration_seconds
    try:
        while time.time() < deadline:
            await serialize_response_payload(document)
            await asyncio.sleep(0)  # yield, but the encode itself already blocked
    finally:
        stop.set()
        await beat


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_serve(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
