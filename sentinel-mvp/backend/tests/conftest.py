"""Shared fixtures for the backend test suite.

Two themes the rest of the suite builds on:

1. The agent registry (``utils.agent_store``) is SQLite-backed and uses a module
   singleton connection. The ``agent_store`` fixture points it at a throwaway DB
   + upload dir per test so the "add agent / pick entry point" flow is exercised
   in isolation, never touching the real ``/data`` volume.

2. The runnable-agent contract: an uploaded file runs in the victim loop iff it
   defines ``_make_op(redis_client)`` returning the 4-tuple
   ``(initialize, <work>, <retrieve>, cleanup)``. ``load_agent_make_op`` loads an
   example exactly the way ``victim/main.py`` does (importlib from a file path),
   and ``FakeRedis`` stands in for the attribution sink.
"""

import importlib.util
import os
import sys

import pytest

# Never let the registry fall back to the default ``/data`` paths during tests.
os.environ.setdefault("ACTIVITY_DB_PATH", os.path.join(os.getcwd(), ".pytest-data", "activity.db"))
os.environ.setdefault("AGENT_UPLOAD_DIR", os.path.join(os.getcwd(), ".pytest-data", "agents"))

# ``examples/`` lives next to ``backend/``; ``victim/`` holds instrument.py +
# redis_keys.py that the example agents import at runtime.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_DIR = os.path.dirname(_BACKEND_DIR)
EXAMPLES_DIR = os.path.join(_REPO_DIR, "examples")
VICTIM_DIR = os.path.join(_REPO_DIR, "victim")

# A runnable agent file exposing _make_op(redis_client) returning a 4-tuple.
RUNNABLE_AGENT_SOURCE = '''\
import os


def get_mode():
    return os.environ.get("_RESOLVED_MODE", "buggy")


def _make_op(redis_client):
    async def initialize():
        return True

    async def embed_documents():
        # the entry point we want Sentinel to watch
        return process(8)

    async def search():
        return True

    async def cleanup():
        return True

    return initialize, embed_documents, search, cleanup


def process(n):
    return list(range(n))
'''

# Uploaded for diagnosis only: no _make_op, so it cannot run in the victim loop.
SOURCE_ONLY_AGENT_SOURCE = '''\
def embed_documents(batch):
    return list(batch)
'''


@pytest.fixture
def runnable_agent_source() -> str:
    return RUNNABLE_AGENT_SOURCE


@pytest.fixture
def source_only_agent_source() -> str:
    return SOURCE_ONLY_AGENT_SOURCE


@pytest.fixture
def agent_store(tmp_path, monkeypatch):
    """A fresh agent registry backed by a throwaway SQLite DB + upload dir."""
    from utils import activity_db
    from utils import agent_store as store

    db_path = str(tmp_path / "agents.db")
    monkeypatch.setattr(activity_db, "DB_PATH", db_path)
    monkeypatch.setattr(store, "DB_PATH", db_path)
    monkeypatch.setattr(store, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(store, "_conn", None)
    try:
        yield store
    finally:
        if store._conn is not None:
            store._conn.close()
            store._conn = None


class FakeRedis:
    """Minimal async stand-in for the attribution sink instrument.py writes to."""

    def __init__(self):
        self.calls = []

    async def zincrby(self, key, amount, member):
        self.calls.append(("zincrby", key, member))

    async def hincrby(self, key, field, n):
        self.calls.append(("hincrby", key, field))


def load_agent_module(path: str):
    """Import an agent file the way victim/main.py does (importlib from a path)."""
    if VICTIM_DIR not in sys.path:
        sys.path.insert(0, VICTIM_DIR)
    spec = importlib.util.spec_from_file_location(
        f"agent_under_test_{os.path.basename(path)}", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_agent_make_op(path: str):
    """Load an agent file and return its _make_op (the runnable contract hook)."""
    return getattr(load_agent_module(path), "_make_op", None)


@pytest.fixture
def examples_dir() -> str:
    return EXAMPLES_DIR


@pytest.fixture
def fake_redis() -> "FakeRedis":
    return FakeRedis()


@pytest.fixture
def make_op_loader():
    return load_agent_make_op


@pytest.fixture
def module_loader():
    return load_agent_module
