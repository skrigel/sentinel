import pytest

from utils import redis_client
from utils.redis_keys import METRICS_LOOPLAG


@pytest.mark.asyncio
async def test_get_last_n_rss_segments_by_newest_pid(monkeypatch):
    async def fake_xrevrange(key, count):
        return [
            ("5-0", {"timestamp": "5", "rss": "130", "pid": "new"}),
            ("4-0", {"timestamp": "4", "rss": "120", "pid": "new"}),
            ("3-0", {"timestamp": "3", "rss": "110", "pid": "new"}),
            ("2-0", {"timestamp": "2", "rss": "1800000000", "pid": "old"}),
            ("1-0", {"timestamp": "1", "rss": "1700000000", "pid": "old"}),
        ]

    monkeypatch.setattr(redis_client.redis, "xrevrange", fake_xrevrange)

    samples = await redis_client.get_last_n_rss(30)

    assert samples == [
        {"timestamp": 3.0, "rss": 110},
        {"timestamp": 4.0, "rss": 120},
        {"timestamp": 5.0, "rss": 130},
    ]


@pytest.mark.asyncio
async def test_get_last_n_rss_honors_limit_within_current_pid(monkeypatch):
    async def fake_xrevrange(key, count):
        return [
            ("5-0", {"timestamp": "5", "rss": "150", "pid": "new"}),
            ("4-0", {"timestamp": "4", "rss": "140", "pid": "new"}),
            ("3-0", {"timestamp": "3", "rss": "130", "pid": "new"}),
            ("2-0", {"timestamp": "2", "rss": "120", "pid": "new"}),
        ]

    monkeypatch.setattr(redis_client.redis, "xrevrange", fake_xrevrange)

    samples = await redis_client.get_last_n_rss(2)

    assert samples == [
        {"timestamp": 4.0, "rss": 140},
        {"timestamp": 5.0, "rss": 150},
    ]


@pytest.mark.asyncio
async def test_get_last_n_looplag_segments_by_newest_pid(monkeypatch):
    async def fake_xrevrange(key, count):
        assert key == METRICS_LOOPLAG
        return [
            ("5-0", {"timestamp": "5", "lag": "80.5", "pid": "new"}),
            ("4-0", {"timestamp": "4", "lag": "70.0", "pid": "new"}),
            ("3-0", {"timestamp": "3", "lag": "60.25", "pid": "new"}),
            ("2-0", {"timestamp": "2", "lag": "2.0", "pid": "old"}),
            ("1-0", {"timestamp": "1", "lag": "1.0", "pid": "old"}),
        ]

    monkeypatch.setattr(redis_client.redis, "xrevrange", fake_xrevrange)

    samples = await redis_client.get_last_n_looplag(10)

    assert samples == [
        {"timestamp": 3.0, "lag": 60.25},
        {"timestamp": 4.0, "lag": 70.0},
        {"timestamp": 5.0, "lag": 80.5},
    ]
