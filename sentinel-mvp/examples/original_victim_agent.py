"""Uploadable example agent based on the original Sentinel victim.

Use this as the source file/project bundle and set the monitored entry point to:

    process_batch

The code intentionally mirrors ``victim/ops.py``:
- ``process_batch`` leaks a 4 MB bytearray per call in buggy mode.
- fixed mode keeps only the most recent ``WINDOW_K`` batches.
- ``_make_op(redis_client)`` returns ``initialize, process_batch, cleanup`` so it
  can replace the original victim ops module without changing ``victim/main.py``.
"""

import os

import weave

WINDOW_K = 8
conversation_history = []


def get_mode() -> str:
    """Buggy unless the runtime flips the resolved mode to fixed."""
    return os.environ.get("_RESOLVED_MODE", "buggy")


def _make_op(redis_client):
    """Build the instrumented ops bound to a Redis client.

    Returns:
        tuple: ``(initialize, process_batch, cleanup)``
    """
    from instrument import instrument_memory

    instr = instrument_memory(redis_client)

    @weave.op()
    @instr
    async def initialize():
        _ = [0] * 1024
        return True

    @weave.op()
    @instr
    async def process_batch():
        batch_embeddings = bytearray(4 * 1024 * 1024)

        if get_mode() == "fixed":
            conversation_history.append(batch_embeddings)
            del conversation_history[:-WINDOW_K]
        else:
            conversation_history.append(batch_embeddings)

        return len(conversation_history)

    @weave.op()
    @instr
    async def cleanup():
        return True

    return initialize, process_batch, cleanup
