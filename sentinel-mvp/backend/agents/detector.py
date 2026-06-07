"""Detector agent: turns the RSS stream into an anomaly verdict.

No LLM (CLAUDE.md #4). Alarms on a sustained positive RSS *slope* with strong
linear fit, not on absolute RSS (CLAUDE.md #2).
"""

import asyncio
import json
import os
import time

import weave

from utils.redis_client import get_last_n_looplag, get_last_n_rss, redis
from utils.redis_keys import BASELINE_RSS_SLOPE, EVENTS_ANOMALY
from utils.stats import linregress

# 30 samples @ 2s = 60s window.
WINDOW_SAMPLES = 30
R2_THRESHOLD = 0.85

# DEMO_MODE: skip baseline, use a fixed slope threshold so timing is predictable.
DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"
DEMO_SLOPE_THRESHOLD_BYTES_S = 1_000_000  # ~1 MB/s sustained -> leak
DEMO_LAG_THRESHOLD_MS = 50.0

BASELINE_WINDOW_S = 30
POLL_INTERVAL_S = 2.0
CPU_WINDOW_SAMPLES = 10
CPU_SUSTAINED_S = 10.0


async def _establish_baseline():
    """Watch the first ~30s of clean runtime, store mean/stddev of slope."""
    print("[detector] establishing baseline...")
    slopes = []
    deadline = time.time() + BASELINE_WINDOW_S
    while time.time() < deadline:
        samples = await get_last_n_rss(WINDOW_SAMPLES)
        if len(samples) >= 5:
            slope, _ = linregress(
                [s["timestamp"] for s in samples], [s["rss"] for s in samples]
            )
            slopes.append(slope)
        await asyncio.sleep(POLL_INTERVAL_S)

    mean = sum(slopes) / len(slopes) if slopes else 0.0
    var = sum((s - mean) ** 2 for s in slopes) / len(slopes) if slopes else 0.0
    stddev = var ** 0.5
    await redis.hset(
        BASELINE_RSS_SLOPE,
        mapping={"mean": mean, "stddev": stddev, "samples": len(slopes)},
    )
    print(f"[detector] baseline slope mean={mean:.0f} B/s stddev={stddev:.0f}")
    return mean, stddev


async def _establish_cpu_baseline():
    """Watch the first ~30s of clean runtime, return mean/stddev of mean lag."""
    print("[detector] establishing CPU baseline...")
    means = []
    deadline = time.time() + BASELINE_WINDOW_S
    while time.time() < deadline:
        samples = await get_last_n_looplag(CPU_WINDOW_SAMPLES)
        if len(samples) >= 5:
            means.append(sum(s["lag"] for s in samples) / len(samples))
        await asyncio.sleep(POLL_INTERVAL_S)

    mean = sum(means) / len(means) if means else 0.0
    var = sum((s - mean) ** 2 for s in means) / len(means) if means else 0.0
    stddev = var ** 0.5
    print(f"[detector] baseline loop-lag mean={mean:.1f} ms stddev={stddev:.1f}")
    return mean, stddev


@weave.op()
async def detect_anomaly():
    """Run forever; publish one anomaly per leak onset, then keep watching."""
    if DEMO_MODE:
        threshold = DEMO_SLOPE_THRESHOLD_BYTES_S
        print(f"[detector] DEMO_MODE: fixed threshold {threshold} B/s")
    else:
        mean, stddev = await _establish_baseline()
        threshold = mean + 3 * stddev

    sustained_since = None
    already_fired = False

    while True:
        await asyncio.sleep(POLL_INTERVAL_S)
        samples = await get_last_n_rss(WINDOW_SAMPLES)
        if len(samples) < 10:
            continue

        slope, r2 = linregress(
            [s["timestamp"] for s in samples], [s["rss"] for s in samples]
        )

        is_leaky = slope > threshold and r2 > R2_THRESHOLD
        if is_leaky:
            if sustained_since is None:
                sustained_since = time.time()
            duration = time.time() - sustained_since
            if duration >= 30 and not already_fired:
                anomaly = {
                    "type": "memory_leak",
                    "start_ts": time.time(),
                    "severity": "HIGH" if slope > threshold * 2 else "MEDIUM",
                    "slope": slope,
                    "r2": r2,
                }
                await redis.publish(EVENTS_ANOMALY, json.dumps(anomaly))
                print(f"[detector] ANOMALY slope={slope:.0f} B/s r2={r2:.2f}")
                already_fired = True
        else:
            sustained_since = None
            # After a fix lands and RSS flattens, re-arm so a second beat works.
            if already_fired and slope < threshold * 0.2:
                already_fired = False


@weave.op()
async def detect_cpu_anomaly():
    """Run forever; publish one CPU hot-path anomaly per loop-lag onset."""
    if DEMO_MODE:
        threshold = DEMO_LAG_THRESHOLD_MS
        print(f"[detector] DEMO_MODE: fixed loop-lag threshold {threshold:.1f} ms")
    else:
        mean, stddev = await _establish_cpu_baseline()
        threshold = mean + 3 * stddev

    sustained_since = None
    already_fired = False

    while True:
        await asyncio.sleep(POLL_INTERVAL_S)
        samples = await get_last_n_looplag(CPU_WINDOW_SAMPLES)
        if len(samples) < 5:
            continue

        mean_lag = sum(s["lag"] for s in samples) / len(samples)
        now = time.time()
        is_hot = mean_lag > threshold
        if is_hot:
            if sustained_since is None:
                sustained_since = now
            duration = now - sustained_since
            if duration >= CPU_SUSTAINED_S and not already_fired:
                anomaly = {
                    "type": "cpu_hotpath",
                    "start_ts": now,
                    "severity": "HIGH" if mean_lag > threshold * 2 else "MEDIUM",
                    "lag_mean": mean_lag,
                }
                try:
                    await redis.publish(EVENTS_ANOMALY, json.dumps(anomaly))
                except Exception:
                    pass
                print(f"[detector] CPU ANOMALY mean_lag={mean_lag:.1f} ms")
                already_fired = True
        else:
            sustained_since = None
            if already_fired and mean_lag < threshold * 0.5:
                already_fired = False


async def force_anomaly():
    """Manual override for demo safety (spec §5.2 'Force Detection')."""
    samples = await get_last_n_rss(WINDOW_SAMPLES)
    slope = 0.0
    if len(samples) >= 5:
        slope, _ = linregress(
            [s["timestamp"] for s in samples], [s["rss"] for s in samples]
        )
    anomaly = {
        "type": "memory_leak",
        "start_ts": time.time(),
        "severity": "HIGH",
        "slope": slope or DEMO_SLOPE_THRESHOLD_BYTES_S,
        "r2": 1.0,
        "forced": True,
    }
    await redis.publish(EVENTS_ANOMALY, json.dumps(anomaly))
    return anomaly


async def force_cpu_anomaly():
    """Manual override for CPU hot-path demo safety."""
    samples = await get_last_n_looplag(CPU_WINDOW_SAMPLES)
    mean_lag = 0.0
    if samples:
        mean_lag = sum(s["lag"] for s in samples) / len(samples)
    anomaly = {
        "type": "cpu_hotpath",
        "start_ts": time.time(),
        "severity": "HIGH",
        "lag_mean": mean_lag or DEMO_LAG_THRESHOLD_MS,
        "forced": True,
    }
    try:
        await redis.publish(EVENTS_ANOMALY, json.dumps(anomaly))
    except Exception:
        pass
    return anomaly
