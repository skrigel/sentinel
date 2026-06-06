"""Scenario (GRACEFUL DECLINE): native memory growth via numpy buffers.

An ML serving loop accumulates per-batch feature matrices into an in-memory
"feature store" as numpy arrays. RSS climbs steadily and *looks* exactly like a
Python leak from the outside (psutil sees it). But the bytes live in numpy's C
buffers, which ``tracemalloc`` (Python-allocator-only) does not trace -- so the
attributor finds that the top Python op explains only a tiny fraction of the RSS
growth. The honest move is REPORT_UNRESOLVED: "tracemalloc under-attributes;
suspect native/C-extension allocation", not a confident pure-Python fix.

This is why the decline tier exists: it defeats Sentinel's tracemalloc assumption.
"""

import asyncio
import time

SCENARIO = {
    "name": "numpy_feature_store_native",
    "tier": "graceful_decline",
    "expected_symptom": "memory_leak",
    "expected_subcause": "native_memory_growth",
    "expected_blamed_op": None,
    "expected_outcome": "report_unresolved",
    "expected_min_rss_growth_mb": 50,
    "expected_min_cpu_pct": 0,
    "decline_reason_keywords": ["native", "tracemalloc", "numpy", "under-attribut", "C buffer"],
    "description": "Accumulated numpy feature matrices grow RSS, but tracemalloc cannot attribute the native bytes.",
}

# Retained native buffers: list of numpy arrays. RSS grows; tracemalloc can't see it.
_FEATURE_STORE: list = []


def accumulate_feature_matrix(np_module, batch_id: int):
    """Append a ~4 MB float64 matrix held in a numpy (native) buffer."""
    # 256 * 2048 * 8 bytes ~= 4 MB, allocated by numpy via malloc (untraced).
    matrix = np_module.random.random((256, 2048))
    _FEATURE_STORE.append(matrix)  # retained "feature store" -> native RSS growth
    return len(_FEATURE_STORE)


async def _serve_inference(duration_seconds: int) -> None:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "native_memory_growth scenario requires numpy (the leak must be native)"
        ) from exc

    deadline = time.time() + duration_seconds
    batch_id = 0
    while time.time() < deadline:
        accumulate_feature_matrix(np, batch_id)
        batch_id += 1
        await asyncio.sleep(0.4)


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_serve_inference(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
