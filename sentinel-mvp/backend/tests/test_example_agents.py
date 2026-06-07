"""Every example agent in ``examples/`` actually RUNS through the entry-point path.

These are *auto-discovered*: any ``examples/<name>_agent.py`` is picked up with no
edits here, so "drop in a new agent file + declare its entry point and it works"
is guaranteed by the suite, not just by convention.

The contract each example must satisfy (CLAUDE.md #5 — apply == flag-flip):

1. define ``_make_op(redis_client)`` returning the 4-tuple of async ops
   ``(initialize, <work>, <retrieve>, cleanup)`` the victim loop unpacks, and
2. declare module-level ``ENTRY_POINT`` (an op name in that tuple) and ``BEAT``
   ("memory" or "cpu") — the op Sentinel attributes and the beat that drives it.

The tests load each file exactly the way ``victim/main.py`` does (importlib from a
path), run one loop iteration, and confirm the declared entry point is a real op
the Diagnostician can read. This also regression-guards the bug that made the
victim feel hardcoded: an example that returns a 3-tuple instead of 4 fails here.

To add your own runnable agent, copy ``examples/test1_agent.py``, rename ops, and
set ``ENTRY_POINT`` — no changes to this file are needed.
"""

import glob
import os
import tracemalloc

import pytest

from agents.diagnostician import _extract_op_source

# Discovered at collection time (parametrize can't use fixtures): every
# examples/*_agent.py is picked up automatically.
_EXAMPLES_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "examples")
)
AGENT_FILES = sorted(
    os.path.basename(p) for p in glob.glob(os.path.join(_EXAMPLES_DIR, "*_agent.py"))
)


def _load(module_loader, examples_dir, filename):
    module = module_loader(os.path.join(examples_dir, filename))
    entry_point = getattr(module, "ENTRY_POINT", None)
    beat = getattr(module, "BEAT", "memory")
    return module, entry_point, beat


def test_at_least_one_example_agent_is_discovered():
    assert AGENT_FILES, "expected examples/*_agent.py files to discover"


@pytest.mark.parametrize("filename", AGENT_FILES)
def test_declares_make_op_and_convention(filename, examples_dir, module_loader):
    module, entry_point, beat = _load(module_loader, examples_dir, filename)

    assert callable(getattr(module, "_make_op", None)), (
        f"{filename} must define _make_op(redis_client) to be runnable"
    )
    assert entry_point, f"{filename} must declare a module-level ENTRY_POINT"
    assert beat in {"memory", "cpu"}, f"{filename} BEAT must be 'memory' or 'cpu'"


@pytest.mark.parametrize("filename", AGENT_FILES)
def test_make_op_returns_four_async_ops_including_entry_point(
    filename, examples_dir, module_loader, fake_redis
):
    module, entry_point, _ = _load(module_loader, examples_dir, filename)
    ops = module._make_op(fake_redis)

    # Exactly the 4-tuple victim/main.py unpacks: (initialize, ..., cleanup).
    assert len(ops) == 4
    for op in ops:
        assert callable(op)
    names = [op.__name__ for op in ops]
    assert names[0] == "initialize"
    assert names[-1] == "cleanup"
    assert entry_point in names, (
        f"{filename}: ENTRY_POINT {entry_point!r} is not one of its ops {names}"
    )


@pytest.mark.parametrize("filename", AGENT_FILES)
@pytest.mark.asyncio
async def test_one_loop_iteration_runs_and_attributes(
    filename, monkeypatch, examples_dir, module_loader, fake_redis
):
    module, entry_point, beat = _load(module_loader, examples_dir, filename)

    # The runtime selects mode/beat via env (the apply-time flag-flip); buggy +
    # the agent's declared beat exercises the real per-iteration work.
    monkeypatch.setenv("_RESOLVED_MODE", "buggy")
    monkeypatch.setenv("_RESOLVED_BEAT", beat)

    ops = module._make_op(fake_redis)

    tracemalloc.start()
    try:
        for op in ops:  # one full loop iteration, like victim/main.py
            await op()
    finally:
        tracemalloc.stop()

    # instrument.py records an invocation per op into attrib:invocations.
    invocations = [c for c in fake_redis.calls if c[0] == "hincrby"]
    assert len(invocations) == 4
    assert entry_point in {c[2] for c in invocations}


@pytest.mark.parametrize("filename", AGENT_FILES)
def test_entry_point_source_is_extractable_for_diagnosis(
    filename, examples_dir, module_loader
):
    module, entry_point, _ = _load(module_loader, examples_dir, filename)

    # The Diagnostician reads the chosen entry point's source from the uploaded
    # file; the op is nested inside _make_op, so extraction must find it there.
    with open(os.path.join(examples_dir, filename), "r", encoding="utf-8") as f:
        source = f.read()

    snippet = _extract_op_source(source, entry_point)
    assert f"def {entry_point}" in snippet
    assert snippet != source  # a focused slice, not the whole module
