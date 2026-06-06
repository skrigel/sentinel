"""Scenario: a video pipeline retaining full-resolution decoded frames.

A frame-processing pipeline decodes each frame, runs a cheap analysis stage, and
emits a small summary. For "debugging", every decoded full-resolution frame is
appended to a ``_FRAME_HISTORY`` that was meant to be a short rolling preview but
is never trimmed. The retained objects are a handful of *large* decoded buffers
that should have been freed once summarized -- large-object retention, distinct
from the document-expansion variant: the payload is pixel-row buffers, the flow
is a multi-stage pipeline, and the retention is an always-on debug capture.
tracemalloc blames ``process_frame``; the fix bounds the history ring.
"""

import asyncio
import time

SCENARIO = {
    "name": "frame_history_retention",
    "tier": "resolvable",
    "expected_symptom": "memory_leak",
    "expected_subcause": "large_object_retention",
    "expected_blamed_op": "process_frame",
    "expected_outcome": "resolved",
    "expected_min_rss_growth_mb": 50,
    "expected_min_cpu_pct": 0,
    "decline_reason_keywords": [],
    "description": "Full-resolution decoded frames are kept in an unbounded debug history instead of being freed after summarizing.",
}

# Meant to be a short rolling preview; never trimmed. Holds big decoded frames.
_FRAME_HISTORY: list = []


def _decode_frame(frame_no: int) -> dict:
    # ~6 MB decoded frame: 720 rows of ~8 KB each.
    return {
        "frame_no": frame_no,
        "rows": [bytes(8192) for _ in range(720)],
    }


def _summarize(frame: dict) -> dict:
    # The only thing we actually needed downstream: a tiny summary.
    return {"frame_no": frame["frame_no"], "row_count": len(frame["rows"])}


async def process_frame(frame_no: int) -> int:
    """Decode, summarize, and (buggily) retain the full decoded frame."""
    frame = _decode_frame(frame_no)
    summary = _summarize(frame)
    # BUG: the full decoded frame is retained for "debugging", never trimmed,
    # even though only `summary` is needed past this point.
    _FRAME_HISTORY.append(frame)
    _ = summary
    return len(_FRAME_HISTORY)


async def _run_pipeline(duration_seconds: int) -> None:
    deadline = time.time() + duration_seconds
    frame_no = 0
    while time.time() < deadline:
        await process_frame(frame_no)
        frame_no += 1
        await asyncio.sleep(0.4)


def run(duration_seconds: int = 60) -> None:
    asyncio.run(_run_pipeline(duration_seconds))


if __name__ == "__main__":
    import sys

    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
