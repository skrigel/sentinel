"""Shared state contract for Sentinel's deterministic incident graph."""

import operator
from typing import Annotated, Optional, TypedDict

MAX_TRIAGE_ROUNDS = 3
MAX_INVESTIGATION_ROUNDS = 4
MAX_FIX_ATTEMPTS = 2
RECOVERY_REDUCTION_TARGET = 0.8


class IncidentState(TypedDict, total=False):
    incident_id: str
    status: str
    anomaly: dict
    symptom_type: str
    blamed_op: Optional[str]
    suspected_subcause: Optional[str]
    confidence: float
    pct_explained: float
    evidence: Annotated[list, operator.add]
    attempted_routes: Annotated[list, operator.add]
    rejected_routes: Annotated[list, operator.add]
    proposed_fix: Optional[dict]
    test_result: Optional[dict]
    verification: Optional[dict]
    next_action: Optional[str]
    triage_rounds: int
    investigation_rounds: int
    fix_attempts: int
    _self_test_should_pass: bool
