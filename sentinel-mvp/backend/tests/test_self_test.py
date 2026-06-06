import pytest

import graph.nodes as graph_nodes


@pytest.fixture(autouse=True)
def no_broadcast(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(graph_nodes, "broadcast", noop)
    monkeypatch.setattr(graph_nodes, "narrate", noop)


@pytest.mark.asyncio
async def test_unbounded_collection_self_test_uses_offline_simulation():
    result = await graph_nodes.n_self_test(
        {
            "anomaly": {"slope": 100.0},
            "suspected_subcause": "unbounded_collection",
            "proposed_fix": {"confidence": "high", "fix_strategy": "bound the list"},
        }
    )

    test_result = result["test_result"]
    assert test_result["tests_passed"] is True
    assert test_result["confidence"] == "high"
    assert test_result["rss_slope_before"] == pytest.approx(100.0)
    assert test_result["rss_slope_after"] <= 0.2 * test_result["rss_slope_before"]


@pytest.mark.asyncio
async def test_unsupported_subcause_self_test_fails_low_confidence():
    result = await graph_nodes.n_self_test(
        {
            "anomaly": {"slope": 100.0},
            "suspected_subcause": "cpu_hotpath",
            "proposed_fix": {"confidence": "high", "fix_strategy": "optimize loop"},
        }
    )

    assert result["test_result"] == {
        "tests_passed": False,
        "rss_slope_before": 100.0,
        "rss_slope_after": 100.0,
        "confidence": "low",
    }


@pytest.mark.asyncio
async def test_self_test_override_forces_result_before_simulation():
    result = await graph_nodes.n_self_test(
        {
            "anomaly": {"slope": 100.0},
            "suspected_subcause": "unbounded_collection",
            "proposed_fix": {"confidence": "high", "fix_strategy": "bound the list"},
            "_self_test_should_pass": False,
        }
    )

    assert result["test_result"] == {
        "tests_passed": False,
        "rss_slope_before": 100.0,
        "rss_slope_after": 100.0,
        "confidence": "low",
    }
