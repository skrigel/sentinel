"""Scenario: synchronous zlib compression blocking the event loop.

An export endpoint gzips a large batch inline with a synchronous
``zlib.compress`` at a high compression level, directly in the async path. Each
call burns CPU for tens of ms with no ``await``; a co-resident heartbeat task
starves, so loop-lag and CPU% both climb. This is the second event_loop_blocking
variant and is deliberately different from the json.dumps one: the blocking work
is CPU-bound *compression* (not serialization), the payload is a flat byte buffer
(not a nested dict), and the level/size are tuned for a heavier per-call cost.
tracemalloc/self-time blames ``compress_export_batch``; the fix offloads to an
executor.
"""

import asyncio
import os
import time
import zlib

SCENARIO = {
    "name": "blocking_zlib_compress",
    "tier": "resolvable",
    "expected_symptom": "cpu_hotpath",
    "expected_subcause": "event_loop_blocking",
    "expected_blamed_op": "compress_export_batch",
    "expected_outcome": "resolved",
    "expected_min_rss_growth_mb": 0,
    "expected_min_cpu_pct": 50,
    "decline_reason_keywords": [],
    "description": "A synchronous high-level zlib.compress of a large batch blocks the async loop every export.",
}

# A ~6 MB semi-compressible payload built once and reused (so RSS stays flat).
# Mixing random-ish and repeated bytes keeps compression genuinely CPU-bound.
_PAYLOAD = bytes((i * 2654435761) & 0xFF for i in range(6 * 1024 * 1024))


async def compress_export_batch(payload: bytes) -> int:
    """Compress the export synchronously in the loop at a heavy level (the bug)."""
    # BUG: CPU-bound zlib.compress with no await -> blocks every other coroutine.
    compressed = zlib.compress(payload, level=9)
    return len(compressed)


async def _heartbeat(stop: asyncio.Event) -> None:
    while not stop.is_set():
        await asyncio.sleep(0.05)


async def _serve_exports(duration_seconds: int) -> None:
    stop = asyncio.Event()
    beat = asyncio.create_task(_heartbeat(stop))
    deadline = time.time() + duration_seconds
    try:
        while time.time() < deadline:
            await compress_export_batch(_PAYLOAD)
            await asyncio.sleep(0)
    finally:
        stop.set()
        await beat


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_serve_exports(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
