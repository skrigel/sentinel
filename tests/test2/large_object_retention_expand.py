"""Scenario: large-object retention via a "last results" debug handle.

A document-processing service decompresses each incoming document into a large
in-memory expansion, processes it, and is supposed to drop it. The expanded blob
is correctly cleared from the active job map in a ``finally`` -- but a second
reference is stashed on a module-level ``_LAST_RESULTS`` ring that the author
sized wrong (off-by-one comparison), so it keeps every expansion instead of the
last few. Unlike an unbounded *collection* of many small items, here a small
number of *very large* objects are retained longer than they should be.
tracemalloc blames ``expand_and_retain_document``; the fix corrects the bound.
"""

import asyncio
import time

SCENARIO = {
    "name": "document_expansion_retention",
    "tier": "resolvable",
    "expected_symptom": "memory_leak",
    "expected_subcause": "large_object_retention",
    "expected_blamed_op": "expand_and_retain_document",
    "expected_outcome": "resolved",
    "expected_min_rss_growth_mb": 45,
    "expected_min_cpu_pct": 0,
    "decline_reason_keywords": [],
    "description": "Large decompressed documents are retained on a mis-sized 'last results' handle instead of being released.",
}

_RETAIN_LAST_N = 4
_LAST_RESULTS: list = []      # intended to hold only the last N expansions
_ACTIVE_JOBS: dict = {}       # correctly cleaned up; the bug is _LAST_RESULTS


async def expand_and_retain_document(job_id: int, raw_size_kb: int) -> int:
    """Expand a compact doc into a ~5 MB structure and (buggily) retain it."""
    # Simulate decompression: a compact descriptor expands ~50x into big rows.
    expanded = {
        "job_id": job_id,
        "pages": [bytes(5120) for _ in range(1024)],  # ~5 MB expansion
        "index": {i: (i * raw_size_kb) % 8191 for i in range(4096)},
    }
    _ACTIVE_JOBS[job_id] = expanded
    try:
        # ... real processing would read from `expanded` here ...
        _LAST_RESULTS.append(expanded)
        # BUG: off-by-one -- trims only when STRICTLY greater, and uses > not >=,
        # combined with appending before trimming, so it never actually bounds.
        if len(_LAST_RESULTS) > _RETAIN_LAST_N + len(_LAST_RESULTS):
            del _LAST_RESULTS[0]
        return len(_LAST_RESULTS)
    finally:
        # The active-job handle is released correctly; the leak is the retain ring.
        _ACTIVE_JOBS.pop(job_id, None)


async def _process_stream(duration_seconds: int) -> None:
    deadline = time.time() + duration_seconds
    job_id = 0
    while time.time() < deadline:
        await expand_and_retain_document(job_id, raw_size_kb=64 + (job_id % 16))
        job_id += 1
        await asyncio.sleep(0.5)


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_process_stream(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
