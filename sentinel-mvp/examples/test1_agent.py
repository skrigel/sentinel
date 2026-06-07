"""test1: a runnable memory-leak agent with a CUSTOM entry point.

This is a fully runnable victim — not just source for diagnosis. Upload it via
the dashboard and set the monitored **entry point** to:

    embed_documents

It demonstrates "add an agent + pick the entry point of any op you choose": the
leak lives in ``embed_documents`` (not the built-in ``process_batch``), so the
Attributor blames ``embed_documents`` and the Diagnostician reads that op's
source. The runnable contract is identical to the original victim:
``_make_op(redis_client)`` returns ``(initialize, embed_documents, search, cleanup)``
— four async ops the victim loop unpacks and runs every iteration.

Memory beat:
- BUGGY mode: ``embedding_store`` grows unbounded (a 4 MB vector batch is
  appended every iteration and never released).
- FIXED mode: ``embedding_store`` is a sliding window of the last K=8 batches,
  so retained memory plateaus and the Supervisor confirms recovery.
"""

import os

import weave

# --- Sentinel example convention (read by tests/docs; the runtime takes the
# entry point from the upload form, defaulting to this). Declare the op you want
# Sentinel to watch and the beat that exercises it. ---
ENTRY_POINT = "embed_documents"
BEAT = "memory"  # "memory" or "cpu"

# Sliding-window size used in fixed mode.
WINDOW_K = 8

# Unbounded in buggy mode; trimmed to WINDOW_K in fixed mode.
embedding_store = []


def get_mode() -> str:
    """Buggy unless the runtime flips the resolved mode to fixed (apply time)."""
    return os.environ.get("_RESOLVED_MODE", "buggy")


def _make_op(redis_client):
    """Build the instrumented ops bound to a redis client.

    Returns ``(initialize, embed_documents, search, cleanup)``. The chosen entry
    point — ``embed_documents`` — is the second op (the per-iteration work slot).
    """
    from instrument import instrument_memory

    instr = instrument_memory(redis_client)

    @weave.op()
    @instr
    async def initialize():
        # Bounded warmup so it never pollutes attribution.
        _ = [0] * 1024
        return True

    @weave.op()
    @instr
    async def embed_documents():
        # Simulate embedding a batch of retrieved documents: a 4 MB buffer.
        # (A contiguous bytearray so tracemalloc attributes its true size here.)
        batch_vectors = bytearray(4 * 1024 * 1024)

        if get_mode() == "buggy":
            # BUG: appended forever, never released -> unbounded growth.
            embedding_store.append(batch_vectors)
        else:
            embedding_store.append(batch_vectors)
            # FIX: sliding window — retain only the last K=8 batches.
            del embedding_store[:-WINDOW_K]

        return len(embedding_store)

    @weave.op()
    @instr
    async def search():
        # Bounded lookup over the retained batches; no leak here.
        return len(embedding_store)

    @weave.op()
    @instr
    async def cleanup():
        return True

    return initialize, embed_documents, search, cleanup
