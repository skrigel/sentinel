"""SQLite-backed registry of user-selected agents to monitor."""

import asyncio
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path

from .activity_db import DB_PATH

DEFAULT_AGENT_ID = "victim"
DEFAULT_AGENT_NAME = "Document-QA Agent"
DEFAULT_AGENT_FILENAME = "ops.py"
DEFAULT_ENTRY_POINT = "process_batch"
DEFAULT_SOURCE_PATH = os.path.join(
    os.environ.get("VICTIM_SRC_DIR", "/victim_src"), DEFAULT_AGENT_FILENAME
)
UPLOAD_DIR = os.environ.get("AGENT_UPLOAD_DIR", "/data/agents")
RUNNABLE_AGENT_MARKER = "def _make_op"

_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        directory = os.path.dirname(DB_PATH)
        if directory:
            os.makedirs(directory, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                filename TEXT NOT NULL,
                content_type TEXT,
                source_path TEXT,
                source_text TEXT,
                entry_point TEXT,
                monitored INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        _ensure_column(_conn, "agents", "entry_point", "TEXT")
        _seed_default_agent(_conn)
        _conn.commit()
    return _conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _seed_default_agent(conn: sqlite3.Connection) -> None:
    now = time.time()
    conn.execute(
        """
        INSERT INTO agents (
            id, display_name, filename, content_type, source_path, source_text,
            entry_point, monitored, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (
            DEFAULT_AGENT_ID,
            DEFAULT_AGENT_NAME,
            DEFAULT_AGENT_FILENAME,
            "text/x-python",
            DEFAULT_SOURCE_PATH,
            None,
            DEFAULT_ENTRY_POINT,
            1,
            now,
            now,
        ),
    )
    conn.execute(
        "UPDATE agents SET entry_point = ? WHERE entry_point IS NULL",
        (DEFAULT_ENTRY_POINT,),
    )


def _row_to_agent(row: sqlite3.Row | tuple) -> dict:
    keys = [
        "id",
        "display_name",
        "filename",
        "content_type",
        "source_path",
        "entry_point",
        "monitored",
        "created_at",
        "updated_at",
    ]
    out = dict(zip(keys, row))
    out["monitored"] = bool(out["monitored"])
    return out


def _read_source_text(source_path: str | None) -> str | None:
    if not source_path:
        return None
    try:
        with open(source_path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _is_runnable_source(agent: dict, source_text: str | None = None) -> bool:
    if agent["id"] == DEFAULT_AGENT_ID:
        return True
    source = source_text if source_text is not None else _read_source_text(agent.get("source_path"))
    return bool(source and RUNNABLE_AGENT_MARKER in source)


def _with_runtime_status(agent: dict, source_text: str | None = None) -> dict:
    if agent.get("monitored"):
        return {
            **agent,
            "runtime_status": "running",
            "runtime_message": "Running in the victim loop.",
        }
    if _is_runnable_source(agent, source_text):
        return {
            **agent,
            "runtime_status": "ready",
            "runtime_message": "Ready to run when selected.",
        }
    return {
        **agent,
        "runtime_status": "source_only",
        "runtime_message": (
            "Uploaded for source diagnosis only. To run in the victim loop, "
            "the file must expose _make_op(redis_client)."
        ),
    }


def _list_agents() -> list[dict]:
    conn = _connect()
    cur = conn.execute(
        """
        SELECT id, display_name, filename, content_type, source_path, entry_point,
               monitored, created_at, updated_at, source_text
        FROM agents
        ORDER BY created_at ASC
        """
    )
    agents = []
    for row in cur.fetchall():
        agent = _row_to_agent(row[:9])
        agents.append(_with_runtime_status(agent, row[9]))
    return agents


def _safe_filename(filename: str) -> str:
    name = Path(filename or "agent.py").name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "agent.py"


def _display_name_from_filename(filename: str) -> str:
    return filename


def _clean_entry_point(entry_point: str | None) -> str:
    cleaned = (entry_point or "").strip()
    return cleaned or DEFAULT_ENTRY_POINT


def _create_agent(
    filename: str,
    source_text: str,
    content_type: str | None,
    entry_point: str | None,
    display_name: str | None = None,
    monitored: bool = True,
) -> dict:
    conn = _connect()
    now = time.time()
    agent_id = uuid.uuid4().hex
    safe_name = _safe_filename(filename)
    source_path = None
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        source_path = os.path.join(UPLOAD_DIR, f"{agent_id}_{safe_name}")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(source_text)
    except OSError:
        source_path = None

    if monitored:
        conn.execute("UPDATE agents SET monitored = 0")
    conn.execute(
        """
        INSERT INTO agents (
            id, display_name, filename, content_type, source_path, source_text,
            entry_point, monitored, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agent_id,
            (display_name or "").strip() or _display_name_from_filename(safe_name),
            safe_name,
            content_type,
            source_path,
            source_text,
            _clean_entry_point(entry_point),
            int(monitored),
            now,
            now,
        ),
    )
    conn.commit()
    return _get_agent(agent_id)


def _get_agent(agent_id: str) -> dict | None:
    conn = _connect()
    cur = conn.execute(
        """
        SELECT id, display_name, filename, content_type, source_path, entry_point,
               monitored, created_at, updated_at
        FROM agents
        WHERE id = ?
        """,
        (agent_id,),
    )
    row = cur.fetchone()
    return _with_runtime_status(_row_to_agent(row)) if row else None


def _update_agent(
    agent_id: str,
    display_name: str | None = None,
    monitored: bool | None = None,
    entry_point: str | None = None,
) -> dict | None:
    conn = _connect()
    existing = _get_agent(agent_id)
    if not existing:
        return None

    new_name = display_name.strip() if display_name is not None else existing["display_name"]
    if not new_name:
        new_name = existing["display_name"]
    new_monitored = int(monitored) if monitored is not None else int(existing["monitored"])
    new_entry_point = (
        _clean_entry_point(entry_point)
        if entry_point is not None
        else existing.get("entry_point") or DEFAULT_ENTRY_POINT
    )
    if new_monitored:
        conn.execute("UPDATE agents SET monitored = 0 WHERE id != ?", (agent_id,))
    conn.execute(
        """
        UPDATE agents
        SET display_name = ?, monitored = ?, entry_point = ?, updated_at = ?
        WHERE id = ?
        """,
        (new_name, new_monitored, new_entry_point, time.time(), agent_id),
    )
    conn.commit()
    return _get_agent(agent_id)


def _delete_agent(agent_id: str) -> bool:
    if agent_id == DEFAULT_AGENT_ID:
        return False
    conn = _connect()
    existing = _get_agent(agent_id)
    if not existing:
        return False
    conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    conn.commit()
    source_path = existing.get("source_path")
    if source_path:
        try:
            os.remove(source_path)
        except OSError:
            pass
    return True


def _source_for_agent(agent_id: str) -> tuple[dict | None, str | None]:
    conn = _connect()
    cur = conn.execute(
        """
        SELECT id, display_name, filename, content_type, source_path, entry_point,
               monitored, created_at, updated_at, source_text
        FROM agents
        WHERE id = ?
        """,
        (agent_id,),
    )
    row = cur.fetchone()
    if not row:
        return None, None
    agent = _row_to_agent(row[:9])
    source_text = row[9]
    if source_text:
        return _with_runtime_status(agent, source_text), source_text
    source_path = agent.get("source_path")
    if source_path:
        try:
            with open(source_path, "r", encoding="utf-8") as f:
                source = f.read()
                return _with_runtime_status(agent, source), source
        except OSError:
            return _with_runtime_status(agent), None
    return _with_runtime_status(agent), None


def _primary_monitored_agent() -> dict:
    conn = _connect()
    cur = conn.execute(
        """
        SELECT id, display_name, filename, content_type, source_path, entry_point,
               monitored, created_at, updated_at
        FROM agents
        WHERE monitored = 1
        ORDER BY CASE WHEN id = ? THEN 1 ELSE 0 END, updated_at DESC
        LIMIT 1
        """,
        (DEFAULT_AGENT_ID,),
    )
    row = cur.fetchone()
    if row:
        return _with_runtime_status(_row_to_agent(row))
    return _get_agent(DEFAULT_AGENT_ID)


async def init_agent_store() -> None:
    await asyncio.to_thread(_connect)


async def list_agents() -> list[dict]:
    return await asyncio.to_thread(_list_agents)


async def create_agent(
    filename: str,
    source_text: str,
    content_type: str | None,
    entry_point: str | None,
    display_name: str | None = None,
    monitored: bool = True,
) -> dict:
    return await asyncio.to_thread(
        _create_agent,
        filename,
        source_text,
        content_type,
        entry_point,
        display_name,
        monitored,
    )


async def update_agent(
    agent_id: str,
    display_name: str | None = None,
    monitored: bool | None = None,
    entry_point: str | None = None,
) -> dict | None:
    return await asyncio.to_thread(
        _update_agent, agent_id, display_name, monitored, entry_point
    )


async def delete_agent(agent_id: str) -> bool:
    return await asyncio.to_thread(_delete_agent, agent_id)


async def get_agent_source(agent_id: str) -> tuple[dict | None, str | None]:
    return await asyncio.to_thread(_source_for_agent, agent_id)


async def get_primary_monitored_agent() -> dict:
    return await asyncio.to_thread(_primary_monitored_agent)


def get_agent_source_sync(agent_id: str) -> tuple[dict | None, str | None]:
    return _source_for_agent(agent_id)


def get_primary_monitored_agent_sync() -> dict:
    return _primary_monitored_agent()
