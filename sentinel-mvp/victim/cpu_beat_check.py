"""Pure local check for the victim CPU beat.

Run from sentinel-mvp/victim:
    python cpu_beat_check.py
"""

import asyncio
import json
import os
import time

from ops import (
    WINDOW_K,
    _build_nested_payload,
    _make_op,
    conversation_history,
    get_beat,
    get_mode,
)


class FakeRedis:
    async def zincrby(self, *args, **kwargs):
        return None

    async def hincrby(self, *args, **kwargs):
        return None


def check_payload_speed():
    payload = _build_nested_payload()
    started = time.perf_counter()
    encoded = json.dumps(payload)
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"json.dumps payload: {elapsed_ms:.1f} ms, {len(encoded) / 1024 / 1024:.1f} MB")
    assert elapsed_ms > 100, "CPU beat payload must block for >100 ms"
    return len(encoded)


async def check_gating(expected_payload_len: int):
    _, process_batch, retrieve, _ = _make_op(FakeRedis())

    os.environ["_RESOLVED_BEAT"] = "memory"
    os.environ["_RESOLVED_MODE"] = "buggy"
    conversation_history.clear()
    await process_batch()
    await process_batch()
    assert get_beat() == "memory"
    assert get_mode() == "buggy"
    assert len(conversation_history) == 2
    assert await retrieve() == 0

    os.environ["_RESOLVED_BEAT"] = "cpu"
    os.environ["_RESOLVED_MODE"] = "buggy"
    conversation_history.clear()
    for _ in range(WINDOW_K + 2):
        await process_batch()
    assert get_beat() == "cpu"
    assert get_mode() == "buggy"
    assert len(conversation_history) == WINDOW_K
    assert await retrieve() == expected_payload_len

    os.environ["_RESOLVED_MODE"] = "fixed"
    assert get_mode() == "fixed"
    assert await retrieve() == expected_payload_len


def main():
    expected_payload_len = check_payload_speed()
    asyncio.run(check_gating(expected_payload_len))
    print("cpu beat check passed")


if __name__ == "__main__":
    main()
