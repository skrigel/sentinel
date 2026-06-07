"""test2: a runnable CPU-hot-path agent with a CUSTOM entry point.

A fully runnable victim. Upload it via the dashboard, select the **CPU beat**,
and set the monitored **entry point** to:

    rerank_results

It demonstrates the CPU path on a custom op: ``rerank_results`` does a genuinely
CPU-bound ``json.dumps`` of a large nested dict synchronously in the async loop,
which starves the event loop (loop-lag rises without CPU% necessarily spiking —
CLAUDE.md #3). The Attributor blames ``rerank_results`` and the Diagnostician
reads that op's source.

Runnable contract: ``_make_op(redis_client)`` returns
``(initialize, prepare_candidates, rerank_results, cleanup)`` — four async ops.

CPU beat:
- BUGGY mode: ``json.dumps(payload)`` runs on the event loop and blocks it.
- FIXED mode: the same work is offloaded with ``run_in_executor`` so the loop
  stays responsive and the Supervisor confirms recovery.

The op only does the heavy work when the CPU beat is selected, mirroring the
built-in victim; under the memory beat it is a cheap no-op.
"""

import asyncio
import json
import os

import weave

# --- Sentinel example convention (read by tests/docs; the runtime takes the
# entry point from the upload form, defaulting to this). Declare the op you want
# Sentinel to watch and the beat that exercises it. ---
ENTRY_POINT = "rerank_results"
BEAT = "cpu"  # "memory" or "cpu"

# Scaled-down but real multi-MB payload so json.dumps is a genuine hot path.
CPU_PAYLOAD_DOCS = 4000
CPU_PAYLOAD_CHUNKS_PER_DOC = 6
CPU_PAYLOAD_TEXT_BYTES = 120

_nested_payload = None


def get_mode() -> str:
    """Buggy unless the runtime flips the resolved mode to fixed (apply time)."""
    return os.environ.get("_RESOLVED_MODE", "buggy")


def get_beat() -> str:
    """Memory beat unless the runtime resolved the CPU beat."""
    return os.environ.get("_RESOLVED_BEAT", "memory")


def _build_payload() -> dict:
    """Deterministic nested payload serialized by the hot path."""
    global _nested_payload
    if _nested_payload is not None:
        return _nested_payload

    shared_text = "candidate passage " + ("x" * CPU_PAYLOAD_TEXT_BYTES)
    _nested_payload = {
        "query": "cpu hot path rerank benchmark",
        "candidates": [
            {
                "doc_id": f"doc-{i:05d}",
                "score": (CPU_PAYLOAD_DOCS - i) / CPU_PAYLOAD_DOCS,
                "metadata": {"tenant": "demo", "rank": i},
                "chunks": [
                    {
                        "chunk_id": f"{i:05d}-{j:02d}",
                        "text": f"{shared_text} {i} {j}",
                        "weights": [((i * 31 + j * 17 + k) % 1000) / 1000 for k in range(10)],
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

    Returns ``(initialize, prepare_candidates, rerank_results, cleanup)``. The
    chosen entry point — ``rerank_results`` — is the third op (the retrieve slot).
    """
    from instrument import instrument_memory

    instr = instrument_memory(redis_client)

    if get_beat() == "cpu":
        _build_payload()

    @weave.op()
    @instr
    async def initialize():
        _ = [0] * 1024
        return True

    @weave.op()
    @instr
    async def prepare_candidates():
        # Bounded prep work; no leak and no blocking.
        return CPU_PAYLOAD_DOCS

    @weave.op()
    @instr
    async def rerank_results():
        if get_beat() != "cpu":
            return 0

        big = _build_payload()
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

    return initialize, prepare_candidates, rerank_results, cleanup
