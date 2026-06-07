import pytest

from utils import redis_client
from utils.redis_keys import METRICS_LOOPLAG, METRICS_PROCSTAT


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


@pytest.mark.asyncio
async def test_get_last_n_procstat_segments_and_tolerates_missing_uss(monkeypatch):
    async def fake_xrevrange(key, count):
        assert key == METRICS_PROCSTAT
        return [
            (
                "6-0",
                {
                    "timestamp": "6",
                    "pid": "new",
                    "cpu_pct": "12.5",
                    "num_fds": "9",
                    "num_threads": "4",
                },
            ),
            (
                "5-0",
                {
                    "timestamp": "5",
                    "pid": "new",
                    "uss": "1000",
                    "cpu_pct": "10.0",
                    "num_fds": "",
                    "num_threads": "3",
                },
            ),
            (
                "4-0",
                {
                    "timestamp": "4",
                    "pid": "new",
                    "uss": "900",
                    "cpu_pct": "",
                    "num_fds": "7",
                    "num_threads": "2",
                },
            ),
            (
                "3-0",
                {
                    "timestamp": "3",
                    "pid": "old",
                    "uss": "5000",
                    "cpu_pct": "1",
                    "num_fds": "30",
                    "num_threads": "10",
                },
            ),
        ]

    monkeypatch.setattr(redis_client.redis, "xrevrange", fake_xrevrange)

    samples = await redis_client.get_last_n_procstat(10)

    assert samples == [
        {
            "timestamp": 4.0,
            "uss": 900.0,
            "cpu_pct": None,
            "num_fds": 7.0,
            "num_threads": 2.0,
        },
        {
            "timestamp": 5.0,
            "uss": 1000.0,
            "cpu_pct": 10.0,
            "num_fds": None,
            "num_threads": 3.0,
        },
        {
            "timestamp": 6.0,
            "uss": None,
            "cpu_pct": 12.5,
            "num_fds": 9.0,
            "num_threads": 4.0,
        },
    ]
