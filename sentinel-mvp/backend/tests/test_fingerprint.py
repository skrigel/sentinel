from graph.fingerprint import classify_subcause


def _signals(**overrides):
    signals = {
        "blamed_op": "process_batch",
        "tracemalloc_pct": None,
        "uss_net": None,
        "fds_net": None,
        "threads_net": None,
        "cpu_pct_mean": None,
        "loop_lag_mean": None,
    }
    signals.update(overrides)
    return signals


def test_degrades_to_legacy_when_extra_signals_absent():
    memory = classify_subcause(
        "memory_leak",
        _signals(tracemalloc_pct=92.0),
    )
    cpu = classify_subcause(
        "cpu_hotpath",
        _signals(blamed_op="retrieve", loop_lag_mean=120.0),
    )
    unknown = classify_subcause(
        "memory_leak",
        _signals(blamed_op=None, tracemalloc_pct=92.0),
    )

    assert memory["subcause"] == "unbounded_collection"
    assert memory["confidence"] == 0.9
    assert memory["matched_rule"] == "legacy_memory"
    assert cpu["subcause"] == "sync_io_in_async_loop"
    assert cpu["confidence"] == 0.9
    assert cpu["matched_rule"] == "legacy_cpu"
    assert unknown["subcause"] == "unknown"
    assert unknown["confidence"] == 0.3


def test_high_tracemalloc_pct_with_uss_growth_is_python_heap_growth():
    result = classify_subcause(
        "memory_leak",
        _signals(
            tracemalloc_pct=90.0,
            uss_net=1000.0,
            fds_net=0.0,
            threads_net=0.0,
            cpu_pct_mean=1.0,
        ),
    )

    assert result["subcause"] == "unbounded_collection"
    assert result["confidence"] == 0.9
    assert result["matched_rule"] == "python_heap_growth"


def test_low_tracemalloc_pct_with_uss_growth_is_native_memory_growth():
    result = classify_subcause(
        "memory_leak",
        _signals(
            tracemalloc_pct=10.0,
            uss_net=1000.0,
            fds_net=0.0,
            threads_net=0.0,
            cpu_pct_mean=1.0,
        ),
    )

    assert result["subcause"] == "native_memory_growth"
    assert result["confidence"] == 0.8
    assert result["matched_rule"] == "native_memory_growth"


def test_big_fd_delta_is_fd_leak():
    result = classify_subcause(
        "memory_leak",
        _signals(
            tracemalloc_pct=90.0,
            uss_net=1000.0,
            fds_net=25.0,
            threads_net=0.0,
            cpu_pct_mean=1.0,
        ),
    )

    assert result["subcause"] == "fd_leak"
    assert result["confidence"] == 0.85
    assert result["matched_rule"] == "fd_leak"


def test_big_thread_delta_is_thread_leak():
    result = classify_subcause(
        "memory_leak",
        _signals(
            tracemalloc_pct=90.0,
            uss_net=1000.0,
            fds_net=0.0,
            threads_net=12.0,
            cpu_pct_mean=1.0,
        ),
    )

    assert result["subcause"] == "thread_leak"
    assert result["confidence"] == 0.85
    assert result["matched_rule"] == "thread_leak"


def test_cpu_high_cpu_pct_marks_compute_bound_but_keeps_sync_io_label():
    result = classify_subcause(
        "cpu_hotpath",
        _signals(
            blamed_op="retrieve",
            uss_net=0.0,
            fds_net=0.0,
            threads_net=0.0,
            cpu_pct_mean=85.0,
            loop_lag_mean=120.0,
        ),
    )

    assert result["subcause"] == "sync_io_in_async_loop"
    assert result["confidence"] == 0.9
    assert result["signals_summary"]["mode"] == "compute_bound"
    assert result["matched_rule"] == "cpu_compute_bound"
