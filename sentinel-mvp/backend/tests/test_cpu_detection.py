import asyncio
import json

import pytest

from agents import attributor, detector
from utils.redis_keys import ATTRIB_CPU, ATTRIB_INVOCATIONS, EVENTS_ANOMALY


def _lag_samples(value, n=10):
    return [{"timestamp": float(i), "lag": float(value)} for i in range(n)]


@pytest.mark.asyncio
async def test_detect_cpu_anomaly_emits_on_sustained_high_lag(monkeypatch):
    published = []
    calls = 0

    async def fake_sleep(_seconds):
        return None

    async def fake_get_last_n_looplag(_n):
        nonlocal calls
        calls += 1
        if calls > 2:
            raise asyncio.CancelledError
        return _lag_samples(80.0)

    async def fake_publish(channel, payload):
        published.append((channel, json.loads(payload)))

    # Derive the clock from the sample-fetch count so it is robust to any extra
    # time.time() calls (e.g. the @weave.op wrapper consumes one before the loop):
    # iteration 1 -> t=0, iteration 2 -> t=11 (>= CPU_SUSTAINED_S) so it fires once.
    def fake_time():
        return 0.0 if calls <= 1 else 11.0

    monkeypatch.setattr(detector, "DEMO_MODE", True)
    monkeypatch.setattr(detector.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(detector, "get_last_n_looplag", fake_get_last_n_looplag)
    monkeypatch.setattr(detector.redis, "publish", fake_publish)
    monkeypatch.setattr(detector.time, "time", fake_time)

    with pytest.raises(asyncio.CancelledError):
        await detector.detect_cpu_anomaly()

    assert len(published) == 1
    channel, anomaly = published[0]
    assert channel == EVENTS_ANOMALY
    assert anomaly["type"] == "cpu_hotpath"
    assert anomaly["severity"] == "MEDIUM"
    assert anomaly["lag_mean"] == pytest.approx(80.0)


@pytest.mark.asyncio
async def test_detect_cpu_anomaly_does_not_emit_on_low_lag(monkeypatch):
    published = []
    calls = 0

    async def fake_sleep(_seconds):
        return None

    async def fake_get_last_n_looplag(_n):
        nonlocal calls
        calls += 1
        if calls > 3:
            raise asyncio.CancelledError
        return _lag_samples(10.0)

    async def fake_publish(channel, payload):
        published.append((channel, json.loads(payload)))

    monkeypatch.setattr(detector, "DEMO_MODE", True)
    monkeypatch.setattr(detector.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(detector, "get_last_n_looplag", fake_get_last_n_looplag)
    monkeypatch.setattr(detector.redis, "publish", fake_publish)

    with pytest.raises(asyncio.CancelledError):
        await detector.detect_cpu_anomaly()

    assert published == []


class FakeCpuRedis:
    def __init__(self):
        self.published = []

    async def zrevrange(self, key, start, end, withscores=False):
        assert key == ATTRIB_CPU
        assert (start, end, withscores) == (0, 0, True)
        return [("retrieve", 3.0)]

    async def zrange(self, key, start, end, withscores=False):
        assert key == ATTRIB_CPU
        assert (start, end, withscores) == (0, -1, True)
        return [("initialize", 0.5), ("retrieve", 3.0), ("cleanup", 0.5)]

    async def hget(self, key, field):
        assert key == ATTRIB_INVOCATIONS
        assert field == "retrieve"
        return "6"

    async def publish(self, channel, payload):
        self.published.append((channel, json.loads(payload)))


@pytest.mark.asyncio
async def test_attribute_cpu_ranks_and_computes_compute_share(monkeypatch):
    fake_redis = FakeCpuRedis()
    monkeypatch.setattr(attributor, "redis", fake_redis)

    enriched = await attributor.attribute_cpu({"type": "cpu_hotpath"})

    assert enriched["blamed_op"] == "retrieve"
    assert enriched["type"] == "cpu_hotpath"
    assert enriched["confidence"] == "high"
    assert enriched["evidence"] == {
        "cumulative_self_time": 3.0,
        "invocations": 6,
        "per_call_avg_ms": 500.0,
        "pct_of_compute_explained": 75.0,
    }
    assert fake_redis.published == [("events:enriched", enriched)]
