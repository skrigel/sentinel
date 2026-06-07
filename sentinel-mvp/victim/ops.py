"""The instrumented document-QA agent's steps.

Each step is a ``@weave.op()`` and goes through ``instrument.py`` (CLAUDE.md
convention). The memory beat lives in ``process_batch``:

- BUGGY mode: ``conversation_history`` grows unbounded (a new ~4 MB embedding
  batch is appended every iteration and never released).
- FIXED mode: ``conversation_history`` is a sliding window of the last K=8
  entries, so retained memory plateaus.
"""

import asyncio
import json
import os

import weave

# Sliding-window size used in fixed mode.
WINDOW_K = 8

# Unbounded in buggy mode; trimmed to WINDOW_K in fixed mode.
conversation_history = []

# CPU beat payload size: 9,000 documents x 8 chunks serializes to roughly
# 24.3 MB and json.dumps takes about 160 ms on the development MacBook.
CPU_PAYLOAD_DOCS = 9000
CPU_PAYLOAD_CHUNKS_PER_DOC = 8
CPU_PAYLOAD_TEXT_BYTES = 160

_nested_payload = None


def get_mode() -> str:
    """Buggy unless Redis flag (set at apply time) flips us to fixed."""
    return os.environ.get("_RESOLVED_MODE", "buggy")


def get_beat() -> str:
    """Memory beat unless Redis/env startup resolution selected CPU."""
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
                            ((i * 31 + j * 17 + k) % 1000) / 1000
                            for k in range(12)
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

    Returns (initialize, process_batch, retrieve, cleanup).
    """
    from instrument import instrument_memory

    instr = instrument_memory(redis_client)

    if get_beat() == "cpu":
        _build_nested_payload()

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
        # Simulate embedding a batch of retrieved documents: a 4 MB buffer.
        # A bytearray is allocated as one contiguous block, so tracemalloc
        # attributes its true size to this line — keeping per-op attribution in
        # line with the RSS growth it causes (vs. a list of millions of boxed
        # Python floats, whose RSS footprint dwarfs what tracemalloc reports).
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
        # In fixed mode this is a real opportunity to release; in buggy mode the
        # leak is upstream so this is a no-op (the realism of the bug).
        return True

    return initialize, process_batch, retrieve, cleanup
