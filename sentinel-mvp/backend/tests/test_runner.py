import pytest

import graph.nodes as graph_nodes
from graph.runner import GraphRunner

pytestmark = [
    pytest.mark.filterwarnings("ignore:.*asyncio.iscoroutinefunction.*:DeprecationWarning"),
]


@pytest.fixture(autouse=True)
def no_redis_broadcast(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(graph_nodes, "broadcast", noop)
    monkeypatch.setattr(graph_nodes, "narrate", noop)
    monkeypatch.setattr(
        graph_nodes,
        "score_hallucination",
        lambda query, context, output: {"passed": True, "metadata": {"score": 0.0}},
    )
    monkeypatch.setattr(graph_nodes.memory, "embed", lambda text: [1.0, 0.0])


@pytest.mark.asyncio
async def test_runner_starts_paused_then_resumes_to_resolved(monkeypatch):
    async def fake_attribute_anomaly(anomaly):
        return {
            "blamed_op": "process_batch",
            "confidence": "high",
            "evidence": {
                "cumulative_bytes": 100,
                "invocations": 10,
                "per_call_avg": 10.0,
                "total_rss_growth": 108,
                "pct_of_growth_explained": 92,
            },
        }

    async def fake_diagnose(enriched):
        return {
            "diagnosis": "process_batch grows an unbounded list",
            "root_cause": "unbounded list",
            "fix_strategy": "bound the list",
            "confidence": "high",
            "blamed_op": enriched["blamed_op"],
            "evidence": enriched["evidence"],
            "eval": {"accuracy": 1.0},
        }

    async def fake_get_last_n_rss(n):
        return [{"timestamp": i, "rss": 1000} for i in range(30)]

    monkeypatch.setattr(graph_nodes, "attribute_anomaly", fake_attribute_anomaly)
    monkeypatch.setattr(graph_nodes, "diagnose", fake_diagnose)
    monkeypatch.setattr(graph_nodes, "get_last_n_rss", fake_get_last_n_rss)

    runner = GraphRunner()
    paused = await runner.start_from_anomaly(
        {"type": "memory_leak", "slope": 100.0, "start_ts": 1}
    )
    assert paused["status"] == "AWAITING_APPROVAL"

    final = await runner.approve_and_apply()
    assert final["status"] == "RESOLVED"
    assert final["verification"]["recovered"] is True


@pytest.mark.asyncio
async def test_runner_rejects_apply_without_incident():
    runner = GraphRunner()

    with pytest.raises(ValueError, match="No incident awaiting approval"):
        await runner.approve_and_apply()
