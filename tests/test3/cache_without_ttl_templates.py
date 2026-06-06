"""Scenario: a rendered-template cache whose eviction guard never triggers.

A page service caches rendered HTML keyed by ``(template, user_id)``. The author
*tried* to bound it ("don't let it exceed max_entries") but compares the cache
size against ``self._max_entries`` while the limit was actually stored in a
differently named attribute that stays ``None`` -- so the guard is always false
and nothing is ever evicted. The key space is combinatorial (every user x every
template), so it grows unbounded. This differs from the search-cache variant: the
keys are *tuples*, values are large HTML strings, and the bug is a broken
size-guard (not a missing one). tracemalloc blames ``render_cached_template``.
"""

import asyncio
import time

SCENARIO = {
    "name": "template_cache_no_eviction",
    "tier": "resolvable",
    "expected_symptom": "memory_leak",
    "expected_subcause": "cache_without_ttl",
    "expected_blamed_op": "render_cached_template",
    "expected_outcome": "resolved",
    "expected_min_rss_growth_mb": 35,
    "expected_min_cpu_pct": 0,
    "decline_reason_keywords": [],
    "description": "A (template,user) HTML cache never evicts because its size-guard checks an attribute that stays None.",
}


class _TemplateCache:
    def __init__(self):
        self._store: dict = {}
        # BUG: the real limit was meant to be `max_entries`, but the guard below
        # reads `_capacity`, which is never set to a number -> guard never fires.
        self.max_entries = 256
        self._capacity = None

    def put(self, key, value) -> int:
        self._store[key] = value
        if self._capacity is not None and len(self._store) > self._capacity:
            self._store.pop(next(iter(self._store)))  # dead code: _capacity is None
        return len(self._store)


_CACHE = _TemplateCache()


def _render(template: str, user_id: int) -> str:
    # A ~2 MB rendered HTML page (lots of repeated markup rows).
    row = f"<tr><td>{user_id}</td><td>{template}</td><td>{'.' * 200}</td></tr>"
    return "<table>" + (row * 8192) + "</table>"


async def render_cached_template(template: str, user_id: int) -> int:
    """Render + cache a page, with an eviction guard that never triggers (bug)."""
    key = (template, user_id)
    html = _CACHE._store.get(key)
    if html is None:
        html = _render(template, user_id)
        return _CACHE.put(key, html)
    return len(_CACHE._store)


async def _serve_pages(duration_seconds: int) -> None:
    templates = ["dashboard", "billing", "settings"]
    deadline = time.time() + duration_seconds
    user_id = 0
    while time.time() < deadline:
        # Combinatorial keys: a fresh user against each template every tick.
        for template in templates:
            await render_cached_template(template, user_id)
        user_id += 1
        await asyncio.sleep(0.45)


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_serve_pages(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
