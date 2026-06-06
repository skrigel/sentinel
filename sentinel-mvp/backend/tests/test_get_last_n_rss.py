import pytest

from utils import redis_client


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
