import pytest

import graph.nodes as graph_nodes
from graph.incident_graph import build_incident_graph
from graph.state import MAX_FIX_ATTEMPTS

pytestmark = [
    pytest.mark.filterwarnings("ignore::PendingDeprecationWarning"),
    pytest.mark.filterwarnings("ignore:The default value of `allowed_objects`.*"),
    pytest.mark.filterwarnings("ignore:.*asyncio.iscoroutinefunction.*:DeprecationWarning"),
]

EXPECTED_NODES = {
    "triage",
    "memory_investigate",
    "evidence_collector",
    "classify_cause",
    "retrieve_fix",
    "plan_fix",
    "self_test",
    "await_approval",
    "apply",
    "verify",
    "store_learning",
    "rollback",
    "report_unresolved",
}


def _runtime_nodes(compiled):
    return {name for name in compiled.nodes if not name.startswith("__")}


def test_compiles():
    compiled = build_incident_graph()
    assert _runtime_nodes(compiled) == EXPECTED_NODES


@pytest.fixture(autouse=True)
def no_redis_broadcast(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(graph_nodes, "broadcast", noop)
    monkeypatch.setattr(graph_nodes, "narrate", noop)


@pytest.mark.asyncio
async def test_happy_path(monkeypatch):
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

    compiled = build_incident_graph()
    config = {"configurable": {"thread_id": "happy-path"}}
    initial = {
        "incident_id": "inc-1",
        "anomaly": {"type": "memory_leak", "slope": 100.0, "severity": "HIGH"},
        "evidence": [],
        "attempted_routes": [],
        "rejected_routes": [],
        "_self_test_should_pass": True,
    }

    paused = await compiled.ainvoke(initial, config=config)
    assert paused["status"] == "AWAITING_APPROVAL"
    snapshot = await compiled.aget_state(config)
    assert snapshot.next == ("apply",)

    final = await compiled.ainvoke(None, config=config)
    assert final["status"] == "RESOLVED"
    assert final["verification"]["recovered"] is True


@pytest.mark.asyncio
async def test_retry_then_unresolved(monkeypatch):
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

    monkeypatch.setattr(graph_nodes, "attribute_anomaly", fake_attribute_anomaly)
    monkeypatch.setattr(graph_nodes, "diagnose", fake_diagnose)

    compiled = build_incident_graph()
    config = {"configurable": {"thread_id": "retry-unresolved"}}
    initial = {
        "incident_id": "inc-2",
        "anomaly": {"type": "memory_leak", "slope": 100.0, "severity": "HIGH"},
        "evidence": [],
        "attempted_routes": [],
        "rejected_routes": [],
        "_self_test_should_pass": False,
    }

    final = await compiled.ainvoke(initial, config=config)
    assert final["status"] == "REPORT_UNRESOLVED"
    assert final["fix_attempts"] == MAX_FIX_ATTEMPTS
    assert final["next_action"] == "fix attempt budget exhausted"
