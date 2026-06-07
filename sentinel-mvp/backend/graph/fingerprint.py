"""Deterministic cross-signal incident fingerprinting."""

FD_LEAK_NET = 20
THREAD_LEAK_NET = 10
TRACEMALLOC_COLLECTION_PCT = 60
TRACEMALLOC_NATIVE_PCT = 30
CPU_COMPUTE_BOUND_PCT = 70

_EXTRA_SIGNAL_KEYS = ("uss_net", "fds_net", "threads_net", "cpu_pct_mean")


def _summary(signals: dict, matched_rule: str) -> dict:
    return {
        "tracemalloc_pct": signals.get("tracemalloc_pct"),
        "uss_net": signals.get("uss_net"),
        "fds_net": signals.get("fds_net"),
        "threads_net": signals.get("threads_net"),
        "cpu_pct_mean": signals.get("cpu_pct_mean"),
        "loop_lag_mean": signals.get("loop_lag_mean"),
        "matched_rule": matched_rule,
    }


def _result(subcause: str, confidence: float, matched_rule: str, signals: dict) -> dict:
    return {
        "subcause": subcause,
        "confidence": confidence,
        "matched_rule": matched_rule,
        "signals_summary": _summary(signals, matched_rule),
    }


def _legacy_result(symptom_type: str, signals: dict) -> dict:
    if symptom_type == "memory_leak" and signals.get("blamed_op"):
        return _result("unbounded_collection", 0.9, "legacy_memory", signals)
    if symptom_type == "cpu_hotpath":
        return _result("sync_io_in_async_loop", 0.9, "legacy_cpu", signals)
    return _result("unknown", 0.3, "legacy_unknown", signals)


def classify_subcause(symptom_type: str, signals: dict) -> dict:
    """Classify a subcause from deterministic process/runtime signals."""
    if all(signals.get(key) is None for key in _EXTRA_SIGNAL_KEYS):
        return _legacy_result(symptom_type, signals)

    if symptom_type == "memory_leak":
        fds_net = signals.get("fds_net")
        threads_net = signals.get("threads_net")
        tracemalloc_pct = signals.get("tracemalloc_pct")
        uss_net = signals.get("uss_net")

        if fds_net is not None and fds_net >= FD_LEAK_NET:
            return _result("fd_leak", 0.85, "fd_leak", signals)
        if threads_net is not None and threads_net >= THREAD_LEAK_NET:
            return _result("thread_leak", 0.85, "thread_leak", signals)
        if (
            tracemalloc_pct is not None
            and tracemalloc_pct >= TRACEMALLOC_COLLECTION_PCT
        ):
            return _result("unbounded_collection", 0.9, "python_heap_growth", signals)
        if (
            tracemalloc_pct is not None
            and tracemalloc_pct < TRACEMALLOC_NATIVE_PCT
            and (uss_net or 0) > 0
        ):
            return _result("native_memory_growth", 0.8, "native_memory_growth", signals)
        return _result("unbounded_collection", 0.6, "memory_default", signals)

    if symptom_type == "cpu_hotpath":
        mode = (
            "compute_bound"
            if (signals.get("cpu_pct_mean") or 0) >= CPU_COMPUTE_BOUND_PCT
            else "blocking_io"
        )
        confidence = 0.9 if signals.get("loop_lag_mean") else 0.6
        result = _result(
            "sync_io_in_async_loop",
            confidence,
            f"cpu_{mode}",
            signals,
        )
        result["signals_summary"]["mode"] = mode
        return result

    return _result("unknown", 0.3, "unknown", signals)
