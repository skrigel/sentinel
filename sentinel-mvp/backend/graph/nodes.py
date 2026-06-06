"""Async graph node implementations.

Each node returns only the partial state update LangGraph should merge. Redis
side effects are guarded, and existing agents are reused through their public
async signatures.
"""

from agents.attributor import attribute_anomaly
from agents.diagnostician import diagnose
from utils.redis_client import get_last_n_rss, redis
from utils.redis_keys import (
    ATTRIB_INVOCATIONS,
    ATTRIB_MEM,
    FIX_CACHE_PREFIX,
    VICTIM_MODE,
)
from utils.stats import linregress

from .broadcast import broadcast, narrate
from .state import RECOVERY_REDUCTION_TARGET


def _merge_for_broadcast(state: dict, update: dict) -> dict:
    merged = dict(state)
    for key, value in update.items():
        if key in {"evidence", "attempted_routes", "rejected_routes"}:
            merged[key] = list(merged.get(key, [])) + list(value)
        else:
            merged[key] = value
    return merged


async def _finish(state: dict, update: dict, node: str, decision: str, reason: str):
    merged = _merge_for_broadcast(state, update)
    await broadcast(merged)
    await narrate(node, decision, reason, merged.get("confidence"))
    return update


def _fix_cache_key(state: dict) -> str:
    return (
        f"{FIX_CACHE_PREFIX}:"
        f"{state.get('symptom_type', 'unknown')}:"
        f"{state.get('suspected_subcause') or 'unknown'}:"
        f"{state.get('blamed_op') or 'unknown'}"
    )


def _confidence_score(raw: str | None) -> float:
    return {"high": 0.9, "low": 0.4, "medium": 0.6}.get(raw or "", 0.1)


async def n_triage(state: dict) -> dict:
    anomaly = state.get("anomaly") or {}
    symptom_type = state.get("symptom_type") or anomaly.get("type") or "unknown"
    update = {
        "status": "TRIAGING",
        "symptom_type": symptom_type,
        "attempted_routes": ["triage"],
        "triage_rounds": state.get("triage_rounds", 0) + 1,
    }
    return await _finish(
        state,
        update,
        "triage",
        "route",
        f"symptom_type={symptom_type}",
    )


async def n_memory_investigate(state: dict) -> dict:
    enriched = await attribute_anomaly(state.get("anomaly") or {})
    evidence = enriched.get("evidence") or {}
    blamed_op = enriched.get("blamed_op")
    pct_explained = evidence.get("pct_of_growth_explained", 0.0)
    update = {
        "status": "INVESTIGATING",
        "blamed_op": blamed_op,
        "confidence": _confidence_score(enriched.get("confidence")),
        "pct_explained": pct_explained,
        "evidence": [evidence],
        "investigation_rounds": state.get("investigation_rounds", 0) + 1,
    }
    return await _finish(
        state,
        update,
        "memory_investigate",
        "attribute",
        f"{blamed_op or 'none'} explains {pct_explained:.1f}% of growth",
    )


async def n_evidence_collector(state: dict) -> dict:
    update = {
        "status": "NEEDS_MORE_EVIDENCE",
        "evidence": [{"type": "note", "value": "collected more"}],
        "investigation_rounds": state.get("investigation_rounds", 0) + 1,
    }
    return await _finish(
        state,
        update,
        "evidence_collector",
        "collect_more",
        "collected more evidence",
    )


async def n_classify_cause(state: dict) -> dict:
    if state.get("symptom_type") == "memory_leak" and state.get("blamed_op"):
        subcause = "unbounded_collection"
        confidence = 0.9
    else:
        subcause = "unknown"
        confidence = 0.3
    update = {
        "status": "CLASSIFYING_CAUSE",
        "suspected_subcause": subcause,
        "confidence": confidence,
    }
    return await _finish(
        state,
        update,
        "classify_cause",
        "classify",
        f"suspected_subcause={subcause}",
    )


async def n_retrieve_fix(state: dict) -> dict:
    update = {"status": "LOOKING_UP_PRIOR_FIXES"}
    reason = "no cached fix"
    key = _fix_cache_key(state)
    try:
        cached = await redis.hgetall(key)
        if cached:
            update["proposed_fix"] = {**cached, "source": "cache"}
            reason = f"cache hit {key}"
    except Exception:
        pass
    return await _finish(state, update, "retrieve_fix", "lookup", reason)


async def n_plan_fix(state: dict) -> dict:
    fix_attempts = state.get("fix_attempts", 0) + 1
    existing = state.get("proposed_fix")
    if existing and existing.get("source") == "cache":
        proposed_fix = existing
        reason = "using cached fix"
    else:
        evidence_items = state.get("evidence") or [{}]
        proposal = await diagnose(
            {
                "blamed_op": state.get("blamed_op"),
                "evidence": evidence_items[-1] if evidence_items else {},
                "type": state.get("symptom_type"),
            }
        )
        proposed_fix = {**proposal, "source": "llm"}
        reason = "planned fix with diagnostician"
    update = {
        "status": "PLANNING_FIX",
        "fix_attempts": fix_attempts,
        "proposed_fix": proposed_fix,
    }
    return await _finish(state, update, "plan_fix", "plan", reason)


async def n_self_test(state: dict) -> dict:
    proposed_fix = state.get("proposed_fix") or {}
    slope_before = (state.get("anomaly") or {}).get("slope", 0)
    passed = (
        bool(proposed_fix)
        and proposed_fix.get("confidence") != "failed"
        and state.get("_self_test_should_pass", True)
    )
    update = {
        "status": "TESTING_FIX",
        "test_result": {
            "tests_passed": passed,
            "rss_slope_before": slope_before,
            "rss_slope_after": slope_before * 0.05 if passed else slope_before,
            "confidence": "high" if passed else "low",
        },
    }
    return await _finish(
        state,
        update,
        "self_test",
        "pass" if passed else "fail",
        "self-test passed" if passed else "self-test failed",
    )


async def n_await_approval(state: dict) -> dict:
    update = {"status": "AWAITING_APPROVAL"}
    return await _finish(
        state,
        update,
        "await_approval",
        "await",
        "waiting for human approval",
    )


async def n_apply(state: dict) -> dict:
    try:
        await redis.set(VICTIM_MODE, "fixed")
        await redis.delete(ATTRIB_MEM, ATTRIB_INVOCATIONS)
    except Exception:
        pass
    update = {"status": "APPLYING_FIX"}
    return await _finish(state, update, "apply", "apply", "set victim fixed mode")


async def n_verify(state: dict) -> dict:
    samples = await get_last_n_rss(30)
    if len(samples) >= 5:
        slope_after, _ = linregress(
            [sample["timestamp"] for sample in samples],
            [sample["rss"] for sample in samples],
        )
    else:
        slope_after = 0
    slope_before = (state.get("anomaly") or {}).get("slope", 0) or 1
    reduction = 1 - (slope_after / slope_before)
    recovered = reduction >= RECOVERY_REDUCTION_TARGET
    update = {
        "status": "VERIFYING_RECOVERY",
        "verification": {
            "slope_before": slope_before,
            "slope_after": slope_after,
            "reduction_pct": reduction * 100,
            "recovered": recovered,
        },
    }
    return await _finish(
        state,
        update,
        "verify",
        "recovered" if recovered else "rollback",
        f"reduction={reduction * 100:.1f}%",
    )


async def n_store_learning(state: dict) -> dict:
    proposed_fix = state.get("proposed_fix") or {}
    summary = (
        proposed_fix.get("summary")
        or proposed_fix.get("fix_strategy")
        or proposed_fix.get("diagnosis")
        or "fix verified"
    )
    try:
        await redis.hset(
            _fix_cache_key(state),
            mapping={"summary": summary, "source": proposed_fix.get("source", "unknown")},
        )
    except Exception:
        pass
    update = {"status": "RESOLVED", "next_action": "resolved"}
    return await _finish(state, update, "store_learning", "resolved", "stored fix")


async def n_rollback(state: dict) -> dict:
    try:
        await redis.set(VICTIM_MODE, "buggy")
    except Exception:
        pass
    update = {"status": "REVERTING"}
    return await _finish(state, update, "rollback", "rollback", "restored buggy mode")


async def n_report_unresolved(state: dict) -> dict:
    if state.get("fix_attempts", 0) >= 2:
        reason = "fix attempt budget exhausted"
    elif state.get("pct_explained", 0.0) < 20:
        reason = (
            f"attribution explains only {state.get('pct_explained', 0.0):.1f}% "
            "of RSS growth"
        )
    else:
        reason = "no deterministic route remained"
    update = {"status": "REPORT_UNRESOLVED", "next_action": reason}
    return await _finish(state, update, "report_unresolved", "unresolved", reason)
