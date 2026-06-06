"""Scenario: a search-result memoization cache with no TTL and no max size.

Each distinct query string memoizes its (large) result dict. Queries are nearly
always unique (they carry a cursor / timestamp), so the cache key space is
effectively unbounded and entries are never evicted. RSS climbs as a memory leak
even though the code "looks like" a sensible cache. tracemalloc blames
``lookup_with_cache``; the fix flips it to an LRU with maxsize.
"""

import asyncio
import time

SCENARIO = {
    "name": "search_cache_no_ttl",
    "tier": "resolvable",
    "expected_symptom": "memory_leak",
    "expected_subcause": "cache_without_ttl",
    "expected_blamed_op": "lookup_with_cache",
    "expected_outcome": "resolved",
    "expected_min_rss_growth_mb": 35,
    "expected_min_cpu_pct": 0,
    "decline_reason_keywords": [],
    "description": "A memoization cache keyed by ~unique queries never evicts, so it grows unbounded.",
}

# Unbounded memo cache: no TTL, no maxsize. BUG: every distinct key sticks forever.
_RESULT_CACHE: dict = {}


def _expensive_search(query: str) -> dict:
    # Pretend to hit a vector index and build a ~2.5 MB ranked result set.
    return {
        "query": query,
        "hits": [{"doc_id": i, "vec": bytes(2400)} for i in range(1024)],
    }


async def lookup_with_cache(query: str) -> int:
    """Return a memoized result, caching misses forever (the bug)."""
    cached = _RESULT_CACHE.get(query)
    if cached is None:
        cached = _expensive_search(query)
        _RESULT_CACHE[query] = cached  # BUG: no eviction, no TTL
    return len(_RESULT_CACHE)


async def _drive_queries(duration_seconds: int) -> None:
    deadline = time.time() + duration_seconds
    seq = 0
    terms = ["invoice", "contract", "policy", "ticket", "email"]
    while time.time() < deadline:
        # Each query carries a monotonic cursor -> effectively always a cache miss.
        term = terms[seq % len(terms)]
        query = f"{term}?cursor={seq}&ts={time.time():.3f}"
        await lookup_with_cache(query)
        seq += 1
        await asyncio.sleep(0.4)


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_drive_queries(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
