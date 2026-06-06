"""The instrumented document-QA agent's steps.

Each step is a ``@weave.op()`` and goes through ``instrument.py`` (CLAUDE.md
convention). The memory beat lives in ``process_batch``:

- BUGGY mode: ``conversation_history`` grows unbounded (a new ~4 MB embedding
  batch is appended every iteration and never released).
- FIXED mode: ``conversation_history`` is a sliding window of the last K=8
  entries, so retained memory plateaus.
"""

import os

import weave

# Sliding-window size used in fixed mode.
WINDOW_K = 8

# Unbounded in buggy mode; trimmed to WINDOW_K in fixed mode.
conversation_history = []


def get_mode() -> str:
    """Buggy unless Redis flag (set at apply time) flips us to fixed."""
    return os.environ.get("_RESOLVED_MODE", "buggy")


def _make_op(redis_client):
    """Build the instrumented ops bound to a redis client.

    Returns (initialize, process_batch, cleanup).
    """
    from instrument import instrument_memory

    instr = instrument_memory(redis_client)

    @weave.op()
    @instr
    async def initialize():
        # Stand-in for loading embeddings / setting up the QA agent. Allocates a
        # small, *bounded* working set so it does not pollute attribution.
        _ = [0] * 1024
        return True

    @weave.op()
    @instr
    async def process_batch():
        # Simulate embedding a batch of retrieved documents: ~4 MB of floats.
        # 512 docs * 1024 dims * 8 bytes ≈ 4 MB.
        batch_embeddings = [[float(i) for i in range(1024)] for _ in range(512)]

        if get_mode() == "fixed":
            conversation_history.append(batch_embeddings)
            # Sliding window: only the last K iterations are retained.
            del conversation_history[:-WINDOW_K]
        else:
            # BUG: appended forever, never released -> unbounded growth.
            conversation_history.append(batch_embeddings)

        return len(conversation_history)

    @weave.op()
    @instr
    async def cleanup():
        # In fixed mode this is a real opportunity to release; in buggy mode the
        # leak is upstream so this is a no-op (the realism of the bug).
        return True

    return initialize, process_batch, cleanup
