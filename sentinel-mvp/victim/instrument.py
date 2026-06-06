"""Per-op memory attribution wrapper.

Design invariant (CLAUDE.md #1): tracemalloc *attributes* (which op leaked,
line-accurate, via cumulative ranking); psutil RSS slope *alarms* (whether a
leak exists). We never treat a single op's tracemalloc delta as ground truth for
total memory — only as a relative signal for ranking ops.
"""

import time
import tracemalloc

import weave

# Cap the per-call measurement so instrumentation can never hang the victim.
OP_TIMEOUT_S = 30.0


def instrument_memory(redis_client):
    """Decorator factory. Wraps an async op so each call records:

    - its tracemalloc size delta into the ``attrib:mem`` ZSet (cumulative),
    - its invocation count into ``attrib:invocations``,
    - span attributes onto the enclosing Weave op for the trace view.

    The decorated fn is expected to already be wrapped with ``@weave.op()`` so
    that ``weave.attributes`` lands on the right span.
    """

    def decorator(fn):
        op_name = fn.__name__

        async def wrapper(*args, **kwargs):
            snap0 = tracemalloc.take_snapshot()
            t0 = time.perf_counter()

            result = await fn(*args, **kwargs)

            self_time = time.perf_counter() - t0
            snap1 = tracemalloc.take_snapshot()
            diff = snap1.compare_to(snap0, "lineno")
            py_delta = sum(s.size_diff for s in diff)
            top_alloc = diff[0] if diff else None

            # Span attributes for the Weave trace (best-effort).
            try:
                weave.attributes(
                    {
                        "mem_delta_py": py_delta,
                        "self_time_s": self_time,
                        "top_alloc": str(top_alloc) if top_alloc else None,
                    }
                )
            except Exception:
                pass

            # Cumulative attribution in Redis. Negative deltas (frees) are
            # clamped to 0 so a leaking op's score only ever grows — ranking,
            # not accounting.
            try:
                if py_delta > 0:
                    await redis_client.zincrby(_ATTRIB_MEM, py_delta, op_name)
                await redis_client.hincrby(_ATTRIB_INVOCATIONS, op_name, 1)
            except Exception:
                # Measurement must never kill the victim.
                pass

            return result

        wrapper.__name__ = op_name
        return wrapper

    return decorator


# Imported here (not at top of decorated module) to keep the contract local.
from redis_keys import ATTRIB_INVOCATIONS as _ATTRIB_INVOCATIONS  # noqa: E402
from redis_keys import ATTRIB_MEM as _ATTRIB_MEM  # noqa: E402
