"""Scenario: an HTTP request-audit trail that is never trimmed.

A web service records a per-request context snapshot into a process-global audit
log "for compliance". Nothing ever evicts it, so the list grows for the lifetime
of the process: a classic unbounded-collection leak. tracemalloc attributes the
retained bytes to ``record_request_context`` line-by-line, so Sentinel can blame
the op and the flag-flip fix (cap the log to a ring buffer) verifies cleanly.
"""

import asyncio
import time

SCENARIO = {
    "name": "audit_log_unbounded",
    "tier": "resolvable",
    "expected_symptom": "memory_leak",
    "expected_subcause": "unbounded_collection",
    "expected_blamed_op": "record_request_context",
    "expected_outcome": "resolved",
    "expected_min_rss_growth_mb": 40,
    "expected_min_cpu_pct": 0,
    "decline_reason_keywords": [],
    "description": "A per-request audit-trail list grows forever because nothing evicts it.",
}

# Process-global audit trail. BUG: appended to on every request, never trimmed.
_REQUEST_AUDIT_LOG: list = []


async def record_request_context(request_id: int, route: str) -> int:
    """Append a ~3 MB context snapshot for one request and retain it forever."""
    # A realistic audit record: headers, a body snapshot, and a numeric trace.
    snapshot = {
        "request_id": request_id,
        "route": route,
        "headers": {f"x-header-{i}": "v" * 48 for i in range(200)},
        # ~3 MB body snapshot held as raw bytes (tracemalloc-tracked).
        "body": bytes(3 * 1024 * 1024),
        "latency_trace_ms": [float(i) * 0.5 for i in range(2048)],
    }
    _REQUEST_AUDIT_LOG.append(snapshot)  # BUG: unbounded retention
    return len(_REQUEST_AUDIT_LOG)


async def _serve_requests(duration_seconds: int) -> None:
    routes = ["/search", "/ingest", "/profile", "/report"]
    deadline = time.time() + duration_seconds
    rid = 0
    while time.time() < deadline:
        # Simulate ~3 requests/sec across a few routes.
        for route in routes[: 1 + (rid % len(routes))]:
            await record_request_context(rid, route)
            rid += 1
        await asyncio.sleep(0.33)


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_serve_requests(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
