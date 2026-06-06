"""Pure deterministic routing functions for the incident graph."""

from .state import MAX_FIX_ATTEMPTS, MAX_INVESTIGATION_ROUNDS, MAX_TRIAGE_ROUNDS


def route_after_triage(state) -> str:
    if state.get("symptom_type") == "memory_leak":
        return "investigate"
    return "unresolved"


def route_after_investigation(state) -> str:
    pct = state.get("pct_explained", 0.0)
    if pct > 60:
        return "classify"
    if pct < 20:
        if state.get("triage_rounds", 0) < MAX_TRIAGE_ROUNDS:
            return "retriage"
        return "unresolved"
    if state.get("investigation_rounds", 0) < MAX_INVESTIGATION_ROUNDS:
        return "collect_more"
    return "unresolved"


def route_after_classify(state) -> str:
    subcause = state.get("suspected_subcause")
    if subcause and subcause != "unknown":
        return "retrieve"
    if state.get("investigation_rounds", 0) < MAX_INVESTIGATION_ROUNDS:
        return "collect_more"
    return "unresolved"


def route_after_self_test(state) -> str:
    test_result = state.get("test_result") or {}
    if test_result.get("tests_passed"):
        return "approve"
    if state.get("fix_attempts", 0) < MAX_FIX_ATTEMPTS:
        return "replan"
    return "unresolved"


def route_after_verify(state) -> str:
    verification = state.get("verification") or {}
    if verification.get("recovered"):
        return "resolved"
    return "rollback"
