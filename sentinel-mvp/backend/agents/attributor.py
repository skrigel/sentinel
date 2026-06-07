"""Attributor agent: which op leaked, with measured evidence.

No LLM (CLAUDE.md #4). Reads the cumulative ``attrib:mem`` ZSet the victim's
instrumentation built, ranks it, and cross-checks the top suspect's retained
bytes against the actual RSS growth so the claim is causal, not correlational.
"""

import json

import weave

from utils.redis_client import get_last_n_rss, redis
from utils.redis_keys import ATTRIB_CPU, ATTRIB_INVOCATIONS, ATTRIB_MEM, EVENTS_ENRICHED

LOW_CONFIDENCE_PCT = 30.0  # below this share of growth, flag as uncertain
CPU_HIGH_CONFIDENCE_PCT = 50.0
WINDOW_SAMPLES = 30


def _decode_member(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


async def _publish_enriched(enriched: dict):
    try:
        await redis.publish(EVENTS_ENRICHED, json.dumps(enriched))
    except Exception:
        pass


@weave.op()
async def attribute_anomaly(anomaly: dict) -> dict:
    results = await redis.zrevrange(ATTRIB_MEM, 0, 0, withscores=True)
    if not results:
        enriched = {"blamed_op": None, "evidence": {}, "confidence": "none"}
        await redis.publish(EVENTS_ENRICHED, json.dumps(enriched))
        return enriched

    blamed_op, cumulative_bytes = results[0][0], int(results[0][1])

    inv_raw = await redis.hget(ATTRIB_INVOCATIONS, blamed_op)
    invocations = int(inv_raw) if inv_raw else 1
    per_call_avg = cumulative_bytes / max(invocations, 1)

    # Cross-check against measured RSS growth over the recent window.
    samples = await get_last_n_rss(WINDOW_SAMPLES)
    total_rss_growth = (samples[-1]["rss"] - samples[0]["rss"]) if len(samples) >= 2 else 0
    pct_explained = (
        (cumulative_bytes / total_rss_growth * 100.0) if total_rss_growth > 0 else 0.0
    )

    confidence = "low" if pct_explained < LOW_CONFIDENCE_PCT else "high"

    enriched = {
        "blamed_op": blamed_op,
        "confidence": confidence,
        "evidence": {
            "cumulative_bytes": cumulative_bytes,
            "invocations": invocations,
            "per_call_avg": per_call_avg,
            "total_rss_growth": total_rss_growth,
            "pct_of_growth_explained": pct_explained,
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
