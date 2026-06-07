"""Uploadable copy of the original Sentinel victim (document-QA agent).

Upload this file (or a bundle containing it) via the dashboard and set the
monitored **entry point** to:

    process_batch

It mirrors ``victim/ops.py`` exactly so it can replace the built-in victim ops
without changing ``victim/main.py``:

- ``process_batch`` leaks a 4 MB bytearray per call in buggy mode (memory beat);
  fixed mode keeps only the most recent ``WINDOW_K`` batches.
- ``retrieve`` does a synchronous CPU-bound ``json.dumps`` in buggy mode (CPU
  beat); fixed mode offloads it with ``run_in_executor``.
- ``_make_op(redis_client)`` returns the 4-tuple
  ``(initialize, process_batch, retrieve, cleanup)`` the victim loop unpacks.

The runnable contract (CLAUDE.md #5 — apply == flag-flip): a file is runnable in
the victim loop iff it defines ``_make_op(redis_client)`` returning four async
ops in this order. Anything else is uploaded for source-only diagnosis.
"""

import asyncio
import json
import os

import weave

# --- Sentinel example convention (read by tests/docs; the runtime takes the
# entry point from the upload form, defaulting to this). Declare the op you want
# Sentinel to watch and the beat that exercises it. ---
ENTRY_POINT = "process_batch"
BEAT = "memory"  # "memory" or "cpu"

# Sliding-window size used in fixed mode.
WINDOW_K = 8

# Unbounded in buggy mode; trimmed to WINDOW_K in fixed mode.
conversation_history = []

# CPU beat payload size (scaled to a real, multi-MB json.dumps hot path).
CPU_PAYLOAD_DOCS = 9000
CPU_PAYLOAD_CHUNKS_PER_DOC = 8
CPU_PAYLOAD_TEXT_BYTES = 160

_nested_payload = None


def get_mode() -> str:
    """Buggy unless the runtime flips the resolved mode to fixed."""
    return os.environ.get("_RESOLVED_MODE", "buggy")


def get_beat() -> str:
    """Memory beat unless the runtime resolved the CPU beat."""
    return os.environ.get("_RESOLVED_BEAT", "memory")


def _build_nested_payload() -> dict:
    """Build the deterministic retrieval payload used by the CPU beat."""
    global _nested_payload
    if _nested_payload is not None:
        return _nested_payload

    shared_text = "retrieved passage with dense tokens " + ("x" * CPU_PAYLOAD_TEXT_BYTES)
    _nested_payload = {
        "query": "cpu hot path retrieve benchmark",
        "documents": [
            {
                "doc_id": f"doc-{i:05d}",
                "score": (CPU_PAYLOAD_DOCS - i) / CPU_PAYLOAD_DOCS,
                "metadata": {"tenant": "demo", "source": "synthetic", "rank": i},
                "chunks": [
                    {
                        "chunk_id": f"{i:05d}-{j:02d}",
                        "text": f"{shared_text} {i} {j}",
                        "weights": [
                            ((i * 31 + j * 17 + k) % 1000) / 1000 for k in range(12)
                        ],
                    }
                    for j in range(CPU_PAYLOAD_CHUNKS_PER_DOC)
                ],
            }
            for i in range(CPU_PAYLOAD_DOCS)
        ],
    }
    return _nested_payload


def _make_op(redis_client):
    """Build the instrumented ops bound to a redis client.

    Returns ``(initialize, process_batch, retrieve, cleanup)``.
    """
    from instrument import instrument_memory

    instr = instrument_memory(redis_client)

    if get_beat() == "cpu":
        _build_nested_payload()

    @weave.op()
    @instr
    async def initialize():
        _ = [0] * 1024
        return True

    @weave.op()
    @instr
    async def process_batch():
        batch_embeddings = bytearray(4 * 1024 * 1024)

        if get_beat() == "memory" and get_mode() == "buggy":
            # BUG: appended forever, never released -> unbounded growth.
            conversation_history.append(batch_embeddings)
        else:
            conversation_history.append(batch_embeddings)
            # Sliding window: only the last K iterations are retained.
            del conversation_history[:-WINDOW_K]

        return len(conversation_history)

    @weave.op()
    @instr
    async def retrieve():
        if get_beat() != "cpu":
            return 0

        big = _build_nested_payload()
        if get_mode() == "buggy":
            # BUG: CPU-bound JSON serialization blocks the event loop.
            payload = json.dumps(big)
        else:
            loop = asyncio.get_running_loop()
            payload = await loop.run_in_executor(None, json.dumps, big)
        return len(payload)

    @weave.op()
    @instr
    async def cleanup():
        return True

    return initialize, process_batch, retrieve, cleanup
