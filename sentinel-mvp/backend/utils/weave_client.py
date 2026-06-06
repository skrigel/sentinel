"""Best-effort Weave init for the backend.

If WANDB_API_KEY is missing or the network is down, tracing degrades silently —
the agents still run (CLAUDE.md / spec §5.1).
"""

import os

_initialized = False


def init_weave():
    global _initialized
    if _initialized:
        return
    try:
        import weave

        weave.init(os.environ.get("WEAVE_PROJECT", "sentinel") + "-backend")
        _initialized = True
    except Exception as e:
        print(f"[weave] init failed ({e}); continuing without tracing")
