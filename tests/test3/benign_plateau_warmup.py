"""Scenario (GRACEFUL DECLINE / no detection): a benign warmup plateau.

A service loads a fixed-size lookup model and warms a bounded LRU cache during the
first several seconds, so RSS rises noticeably at startup -- then it reaches
steady state and stays flat: the cache is capped and per-request work allocates
only short-lived objects that are promptly freed. There is no leak. The correct
behavior is that the detector does NOT fire (the RSS *slope* decays to ~0 with no
sustained positive trend), so no incident, no attribution, no fix. This tests
that Sentinel does not false-positive on normal warmup transients (CLAUDE.md #2:
alarm on sustained slope, not absolute RSS).
"""

import asyncio
import time
from collections import OrderedDict

SCENARIO = {
    "name": "warmup_plateau_benign",
    "tier": "graceful_decline",
    "expected_symptom": "none",
    "expected_subcause": "benign_plateau",
    "expected_blamed_op": None,
    "expected_outcome": "no_detection",
    "expected_min_rss_growth_mb": 0,   # transient warmup bump only; no sustained slope
    "expected_min_cpu_pct": 0,
    "decline_reason_keywords": ["warmup", "plateau", "no leak", "bounded", "false positive"],
    "description": "RSS rises during a one-time warmup then plateaus; there is no real leak and the detector must not fire.",
}

_MODEL: dict = {}                       # loaded once at warmup, fixed size
_LRU: "OrderedDict" = OrderedDict()     # bounded cache, evicts oldest
_LRU_MAX = 128


def _warmup_model() -> None:
    # One-time ~30 MB lookup table loaded at startup, then never grows.
    for shard in range(30):
        _MODEL[shard] = bytes(1024 * 1024)


def handle_request(request_id: int) -> int:
    # Steady-state work: build a short-lived response (freed on return) and touch
    # a bounded LRU cache that evicts, so retained memory plateaus.
    transient = [bytes(4096) for _ in range(64)]  # ~256 KB, dropped after this call
    key = request_id % 512
    if key not in _LRU:
        _LRU[key] = bytes(8192)
        if len(_LRU) > _LRU_MAX:
            _LRU.popitem(last=False)  # bounded: oldest evicted
    _ = sum(len(t) for t in transient)
    return len(_LRU)


async def _serve(duration_seconds: int) -> None:
    _warmup_model()  # the one-time RSS bump happens here
    deadline = time.time() + duration_seconds
    request_id = 0
    while time.time() < deadline:
        handle_request(request_id)
        request_id += 1
        await asyncio.sleep(0.1)


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_serve(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
