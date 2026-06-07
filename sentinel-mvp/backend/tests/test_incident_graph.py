import pytest

import graph.incident_graph as incident_graph
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
    "cpu_investigate",
    "evidence_collector",
    "classify_cause",
    "retrieve_fix",
    "plan_fix",
    "check_diagnosis",
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
    monkeypatch.setattr(
        graph_nodes,
        "score_hallucination",
        lambda query, context, output: {"passed": True, "metadata": {"score": 0.0}},
    )
    monkeypatch.setattr(graph_nodes.memory, "embed", lambda text: [1.0, 0.0])


@pytest.mark.asyncio
async def test_classify_cause_degrades_to_legacy_when_procstat_absent(monkeypatch):
    async def fake_get_last_n_procstat(_n):
        return []

    monkeypatch.setattr(graph_nodes, "get_last_n_procstat", fake_get_last_n_procstat)

    update = await graph_nodes.n_classify_cause(
        {
            "symptom_type": "memory_leak",
            "blamed_op": "process_batch",
            "pct_explained": 92.0,
            "evidence": [],
            "attempted_routes": [],
            "rejected_routes": [],
        }
    )

    assert update["suspected_subcause"] == "unbounded_collection"
    assert update["confidence"] == 0.9
    assert update["evidence"][0]["matched_rule"] == "legacy_memory"


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
    assert paused["diagnosis_grounded"] is True
    snapshot = await compiled.aget_state(config)
    assert snapshot.next == ("apply",)

    final = await compiled.ainvoke(None, config=config)
    assert final["status"] == "RESOLVED"
    assert final["verification"]["recovered"] is True


@pytest.mark.asyncio
async def test_cpu_hotpath_path_pauses_then_resolves(monkeypatch):
    async def fake_attribute_cpu(anomaly):
        return {
            "type": "cpu_hotpath",
            "blamed_op": "retrieve",
            "confidence": "high",
            "evidence": {
                "cumulative_self_time": 3.0,
                "invocations": 6,
                "per_call_avg_ms": 500.0,
                "pct_of_compute_explained": 75.0,
            },
        }

    async def fake_diagnose(enriched):
        assert enriched["type"] == "cpu_hotpath"
        assert enriched["blamed_op"] == "retrieve"
        return {
            "diagnosis": "retrieve blocks the event loop with synchronous json.dumps",
            "root_cause": "json serialization runs on the event loop",
            "fix_strategy": "offload json.dumps with run_in_executor",
            "confidence": "high",
            "blamed_op": enriched["blamed_op"],
            "evidence": enriched["evidence"],
            "eval": {"accuracy": 1.0},
        }

    async def fake_get_last_n_looplag(n):
        return [{"timestamp": i, "lag": 5.0} for i in range(n)]

    async def fake_sleep(_seconds):
        return None

    # No prior fix in the store: force the path through diagnose (fake_diagnose),
    # not a recalled memory-leak fix. Without this, retrieve_fix can recall an
    # unrelated cached fix from a live Redis and plan_fix skips diagnose.
    async def fake_recall(_state):
        return None

    monkeypatch.setattr(graph_nodes, "attribute_cpu", fake_attribute_cpu)
    monkeypatch.setattr(graph_nodes, "diagnose", fake_diagnose)
    monkeypatch.setattr(graph_nodes, "get_last_n_looplag", fake_get_last_n_looplag)
    monkeypatch.setattr(graph_nodes.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(graph_nodes.memory, "recall", fake_recall)

    compiled = build_incident_graph()
    config = {"configurable": {"thread_id": "cpu-hotpath"}}
    initial = {
        "incident_id": "inc-cpu",
        "anomaly": {
            "type": "cpu_hotpath",
            "lag_mean": 120.0,
            "severity": "HIGH",
        },
        "evidence": [],
        "attempted_routes": [],
        "rejected_routes": [],
    }

    paused = await compiled.ainvoke(initial, config=config)
    assert paused["status"] == "AWAITING_APPROVAL"
    assert paused["symptom_type"] == "cpu_hotpath"
    assert paused["blamed_op"] == "retrieve"
    assert paused["suspected_subcause"] == "sync_io_in_async_loop"
    assert paused["test_result"]["tests_passed"] is True
    assert paused["test_result"]["lag_before"] == 120.0
    assert paused["test_result"]["lag_after"] == pytest.approx(12.0)
    snapshot = await compiled.aget_state(config)
    assert snapshot.next == ("apply",)

    final = await compiled.ainvoke(None, config=config)
    assert final["status"] == "RESOLVED"
    assert final["verification"]["lag_before"] == 120.0
    assert final["verification"]["lag_after"] == pytest.approx(5.0)
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


@pytest.mark.asyncio
async def test_hallucination_gate_replans_then_unresolved(monkeypatch):
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
            "diagnosis": "the moon caused this leak",
            "root_cause": "unsupported external cause",
            "fix_strategy": "do something unrelated",
            "confidence": "high",
            "blamed_op": enriched["blamed_op"],
            "evidence": enriched["evidence"],
            "eval": {"accuracy": 0.0},
        }

    monkeypatch.setattr(graph_nodes, "attribute_anomaly", fake_attribute_anomaly)
    monkeypatch.setattr(graph_nodes, "diagnose", fake_diagnose)
    monkeypatch.setattr(graph_nodes, "DEMO_MODE", False)
    monkeypatch.setattr(
        graph_nodes,
        "score_hallucination",
        lambda query, context, output: {"passed": False, "metadata": {"score": 0.99}},
    )
    apply_called = False

    async def fake_apply(state):
        nonlocal apply_called
        apply_called = True
        return {"status": "APPLIED"}

    monkeypatch.setattr(incident_graph, "n_apply", fake_apply)

    compiled = build_incident_graph()
    config = {"configurable": {"thread_id": "hallucinated-unresolved"}}
    initial = {
        "incident_id": "inc-3",
        "anomaly": {"type": "memory_leak", "slope": 100.0, "severity": "HIGH"},
        "evidence": [],
        "attempted_routes": [],
        "rejected_routes": [],
        "_self_test_should_pass": True,
    }

    final = await compiled.ainvoke(initial, config=config)
    assert final["status"] == "REPORT_UNRESOLVED"
    assert final["fix_attempts"] == MAX_FIX_ATTEMPTS
    assert final["diagnosis_grounded"] is False
    assert final["hallucination"]["passed"] is False
    assert final["next_action"] == "fix attempt budget exhausted"
    assert apply_called is False
