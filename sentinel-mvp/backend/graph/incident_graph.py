"""LangGraph construction for Sentinel's deterministic incident workflow."""

import contextlib
import io

from .nodes import (
    n_apply,
    n_await_approval,
    n_check_diagnosis,
    n_classify_cause,
    n_evidence_collector,
    n_memory_investigate,
    n_plan_fix,
    n_report_unresolved,
    n_retrieve_fix,
    n_rollback,
    n_self_test,
    n_store_learning,
    n_triage,
    n_verify,
)
from .routing import (
    route_after_classify,
    route_after_diagnosis_check,
    route_after_investigation,
    route_after_self_test,
    route_after_triage,
    route_after_verify,
)
from .state import IncidentState


def build_incident_graph():
    # LangGraph 0.3.34 imports trigger a LangChain warning on stderr through its
    # checkpoint serde path. The import is localized so the standalone build
    # check remains quiet while graph execution behavior stays unchanged.
    from langchain_core._api.deprecation import suppress_langchain_deprecation_warning

    with (
        contextlib.redirect_stderr(io.StringIO()),
        suppress_langchain_deprecation_warning(),
    ):
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, START, StateGraph

    graph = StateGraph(IncidentState)

    graph.add_node("triage", n_triage)
    graph.add_node("memory_investigate", n_memory_investigate)
    graph.add_node("evidence_collector", n_evidence_collector)
    graph.add_node("classify_cause", n_classify_cause)
    graph.add_node("retrieve_fix", n_retrieve_fix)
    graph.add_node("plan_fix", n_plan_fix)
    graph.add_node("check_diagnosis", n_check_diagnosis)
    graph.add_node("self_test", n_self_test)
    graph.add_node("await_approval", n_await_approval)
    graph.add_node("apply", n_apply)
    graph.add_node("verify", n_verify)
    graph.add_node("store_learning", n_store_learning)
    graph.add_node("rollback", n_rollback)
    graph.add_node("report_unresolved", n_report_unresolved)

    graph.add_edge(START, "triage")
    graph.add_conditional_edges(
        "triage",
        route_after_triage,
        {"investigate": "memory_investigate", "unresolved": "report_unresolved"},
    )
    graph.add_conditional_edges(
        "memory_investigate",
        route_after_investigation,
        {
            "classify": "classify_cause",
            "retriage": "triage",
            "collect_more": "evidence_collector",
            "unresolved": "report_unresolved",
        },
    )
    graph.add_edge("evidence_collector", "memory_investigate")
    graph.add_conditional_edges(
        "classify_cause",
        route_after_classify,
        {
            "retrieve": "retrieve_fix",
            "collect_more": "evidence_collector",
            "unresolved": "report_unresolved",
        },
    )
    graph.add_edge("retrieve_fix", "plan_fix")
    graph.add_edge("plan_fix", "check_diagnosis")
    graph.add_conditional_edges(
        "check_diagnosis",
        route_after_diagnosis_check,
        {
            "selftest": "self_test",
            "replan": "plan_fix",
            "unresolved": "report_unresolved",
        },
    )
    graph.add_conditional_edges(
        "self_test",
        route_after_self_test,
        {
            "approve": "await_approval",
            "replan": "plan_fix",
            "unresolved": "report_unresolved",
        },
    )
    graph.add_edge("await_approval", "apply")
    graph.add_edge("apply", "verify")
    graph.add_conditional_edges(
        "verify",
        route_after_verify,
        {"resolved": "store_learning", "rollback": "rollback"},
    )
    graph.add_edge("store_learning", END)
    graph.add_edge("rollback", "report_unresolved")
    graph.add_edge("report_unresolved", END)

    return graph.compile(checkpointer=MemorySaver(), interrupt_before=["apply"])
