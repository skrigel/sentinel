"""Attributor agent: which op leaked, with measured evidence.

No LLM (CLAUDE.md #4). Reads the cumulative ``attrib:mem`` ZSet the victim's
instrumentation built, ranks it, and cross-checks the top suspect's retained
bytes against the actual RSS growth so the claim is causal, not correlational.
"""

import json

import weave

from utils.agent_store import (
    DEFAULT_AGENT_ID,
    DEFAULT_ENTRY_POINT,
    get_primary_monitored_agent,
)
from utils.redis_client import get_last_n_rss, redis
from utils.redis_keys import ATTRIB_CPU, ATTRIB_INVOCATIONS, ATTRIB_MEM, EVENTS_ENRICHED

LOW_CONFIDENCE_PCT = 30.0  # below this share of growth, flag as uncertain
CPU_HIGH_CONFIDENCE_PCT = 50.0
WINDOW_SAMPLES = 30


async def _selected_target(anomaly: dict) -> tuple[dict | None, str]:
    """Resolve the user-selected source bundle and configured op to monitor."""
    try:
        agent = await get_primary_monitored_agent()
    except Exception:
        agent = None
    entry_point = (
        anomaly.get("entry_point")
        or (agent or {}).get("entry_point")
        or DEFAULT_ENTRY_POINT
    )
    return agent, entry_point


async def _recent_rss_growth() -> tuple[list[dict], float]:
    samples = await get_last_n_rss(WINDOW_SAMPLES)
    total_rss_growth = (
        (samples[-1]["rss"] - samples[0]["rss"]) if len(samples) >= 2 else 0
    )
    return samples, total_rss_growth


def _decode_member(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


async def _publish_enriched(enriched: dict):
    try:
        await redis.publish(EVENTS_ENRICHED, json.dumps(enriched))
    except Exception:
        pass


@weave.op()
async def attribute_anomaly(anomaly: dict) -> dict:
    target_agent, configured_op = await _selected_target(anomaly)
    target_agent_id = anomaly.get("agent_id") or (target_agent or {}).get("id")
    results = await redis.zrevrange(ATTRIB_MEM, 0, 0, withscores=True)
    if not results:
        _, total_rss_growth = await _recent_rss_growth()
        enriched = {
            "agent_id": target_agent_id,
            "blamed_op": configured_op,
            "confidence": "medium",
            "evidence": {
                "configured_target": True,
                "type": "configured_entry_point",
                "value": configured_op,
                "total_rss_growth": total_rss_growth,
                "pct_of_growth_explained": 100.0,
                "note": "No measured op attribution was available; using the selected entry point.",
            },
        }
        await redis.publish(EVENTS_ENRICHED, json.dumps(enriched))
        return enriched

    observed_op, cumulative_bytes = results[0][0], int(results[0][1])
    blamed_op = observed_op
    configured_target = False
    if (
        target_agent_id
        and target_agent_id != DEFAULT_AGENT_ID
        and configured_op
        and observed_op == DEFAULT_ENTRY_POINT
    ):
        blamed_op = configured_op
        configured_target = True

    inv_raw = await redis.hget(ATTRIB_INVOCATIONS, observed_op)
    invocations = int(inv_raw) if inv_raw else 1
    per_call_avg = cumulative_bytes / max(invocations, 1)

    # Cross-check against measured RSS growth over the recent window.
    _, total_rss_growth = await _recent_rss_growth()
    pct_explained = (
        (cumulative_bytes / total_rss_growth * 100.0) if total_rss_growth > 0 else 0.0
    )

    confidence = "low" if pct_explained < LOW_CONFIDENCE_PCT else "high"

    enriched = {
        "agent_id": target_agent_id,
        "blamed_op": blamed_op,
        "confidence": confidence,
        "evidence": {
            "cumulative_bytes": cumulative_bytes,
            "invocations": invocations,
            "per_call_avg": per_call_avg,
            "total_rss_growth": total_rss_growth,
            "pct_of_growth_explained": pct_explained,
            "configured_target": configured_target,
            "configured_entry_point": configured_op,
            "observed_op": observed_op,
        },
    }
    await redis.publish(EVENTS_ENRICHED, json.dumps(enriched))
    mb = per_call_avg / 1024 / 1024
    print(
        f"[attributor] {blamed_op}: {mb:.1f} MB/call x {invocations} "
        f"= {pct_explained:.0f}% of growth ({confidence})"
    )
    return enriched


@weave.op()
async def attribute_cpu(anomaly: dict) -> dict:
    try:
        results = await redis.zrevrange(ATTRIB_CPU, 0, 0, withscores=True)
    except Exception:
        results = []
    if not results:
        enriched = {"blamed_op": None, "evidence": {}, "confidence": "none"}
        await _publish_enriched(enriched)
        return enriched

    blamed_op = _decode_member(results[0][0])
    cumulative_self_time = float(results[0][1])

    try:
        inv_raw = await redis.hget(ATTRIB_INVOCATIONS, blamed_op)
    except Exception:
        inv_raw = None
    invocations = int(inv_raw) if inv_raw else 1
    per_call_avg_ms = cumulative_self_time / max(invocations, 1) * 1000.0

    try:
        all_cpu = await redis.zrange(ATTRIB_CPU, 0, -1, withscores=True)
    except Exception:
        all_cpu = results
    total_self_time = sum(float(score) for _, score in all_cpu)
    pct_explained = (
        (cumulative_self_time / total_self_time * 100.0)
        if total_self_time > 0
        else 0.0
    )
    confidence = (
        "high" if pct_explained >= CPU_HIGH_CONFIDENCE_PCT else "low"
    )

    enriched = {
        "type": anomaly.get("type", "cpu_hotpath"),
        "blamed_op": blamed_op,
        "confidence": confidence,
        "evidence": {
            "cumulative_self_time": cumulative_self_time,
            "invocations": invocations,
            "per_call_avg_ms": per_call_avg_ms,
            "pct_of_compute_explained": pct_explained,
        },
    }
    await _publish_enriched(enriched)
    print(
        f"[attributor] {blamed_op}: {per_call_avg_ms:.1f} ms/call x "
        f"{invocations} = {pct_explained:.0f}% of compute ({confidence})"
    )
    return enriched
