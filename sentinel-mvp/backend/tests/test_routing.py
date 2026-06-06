from graph.routing import (
    route_after_diagnosis_check,
    route_after_classify,
    route_after_investigation,
    route_after_self_test,
    route_after_triage,
    route_after_verify,
)


def test_route_after_triage():
    assert route_after_triage({"symptom_type": "memory_leak"}) == "investigate"
    assert route_after_triage({"symptom_type": "cpu_hotpath"}) == "unresolved"
    assert route_after_triage({}) == "unresolved"


def test_route_after_investigation():
    assert route_after_investigation({"pct_explained": 92}) == "classify"
    assert (
        route_after_investigation({"pct_explained": 10, "triage_rounds": 0})
        == "retriage"
    )
    assert (
        route_after_investigation({"pct_explained": 10, "triage_rounds": 3})
        == "unresolved"
    )
    assert (
        route_after_investigation({"pct_explained": 40, "investigation_rounds": 2})
        == "collect_more"
    )
    assert (
        route_after_investigation({"pct_explained": 40, "investigation_rounds": 4})
        == "unresolved"
    )


def test_route_after_classify():
    assert route_after_classify({"suspected_subcause": "unbounded_collection"}) == "retrieve"
    assert (
        route_after_classify(
            {"suspected_subcause": "unknown", "investigation_rounds": 0}
        )
        == "collect_more"
    )
    assert (
        route_after_classify(
            {"suspected_subcause": None, "investigation_rounds": 4}
        )
        == "unresolved"
    )


def test_route_after_self_test():
    assert route_after_self_test({"test_result": {"tests_passed": True}}) == "approve"
    assert (
        route_after_self_test({"test_result": {"tests_passed": False}, "fix_attempts": 1})
        == "replan"
    )
    assert (
        route_after_self_test({"test_result": {"tests_passed": False}, "fix_attempts": 2})
        == "unresolved"
    )
    assert route_after_self_test({}) == "replan"


def test_route_after_diagnosis_check():
    assert route_after_diagnosis_check({"diagnosis_grounded": True}) == "selftest"
    assert (
        route_after_diagnosis_check({"diagnosis_grounded": False, "fix_attempts": 1})
        == "replan"
    )
    assert (
        route_after_diagnosis_check({"diagnosis_grounded": False, "fix_attempts": 2})
        == "unresolved"
    )
    assert route_after_diagnosis_check({}) == "replan"


def test_route_after_verify():
    assert route_after_verify({"verification": {"recovered": True}}) == "resolved"
    assert route_after_verify({"verification": {"recovered": False}}) == "rollback"
    assert route_after_verify({}) == "rollback"
