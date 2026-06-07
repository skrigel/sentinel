"""Durable agent-activity log (SQLite).

The Redis ``timeline:events`` stream holds only the *current* incident (it's
cleared on reset / new incident). This SQLite table is the append-only history
across all incidents so the frontend can show the full, scrollable activity.

stdlib ``sqlite3`` is synchronous; calls are dispatched via ``asyncio.to_thread``
so they never block the event loop. Volume is tiny (one row per node decision).
"""

import asyncio
import json
import os
import sqlite3
import time

DB_PATH = os.environ.get("ACTIVITY_DB_PATH", "/data/activity.db")

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
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT,
                node TEXT,
                decision TEXT,
                reason TEXT,
                confidence TEXT,
                status TEXT,
                timestamp REAL
            )
            """
        )
        # One row per incident (latest snapshot), so resolved interventions
        # persist in the Agent Activity feed with their diagnosis + code diff.
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                timestamp REAL,
                status TEXT,
                data TEXT
            )
            """
        )
        _conn.commit()
    return _conn


def _insert(event: dict) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO activity "
        "(incident_id, node, decision, reason, confidence, status, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            event.get("incident_id"),
            event.get("node"),
            event.get("decision"),
            event.get("reason"),
            event.get("confidence"),
            event.get("status"),
            event.get("timestamp"),
        ),
    )
    conn.commit()


def _fetch(limit: int, offset: int) -> list[dict]:
    conn = _connect()
    cur = conn.execute(
        "SELECT incident_id, node, decision, reason, confidence, status, timestamp "
        "FROM activity ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    rows.reverse()  # oldest-first within the returned page
    return rows


def _upsert_incident(doc: dict) -> None:
    incident_id = doc.get("incident_id")
    if not incident_id:
        return
    anomaly = doc.get("anomaly") or {}
    ts = anomaly.get("start_ts") or time.time()
    conn = _connect()
    conn.execute(
        "INSERT INTO incidents (incident_id, timestamp, status, data) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(incident_id) DO UPDATE SET status=excluded.status, data=excluded.data",
        (incident_id, ts, doc.get("status"), json.dumps(doc, default=str)),
    )
    conn.commit()


def _fetch_incidents(limit: int) -> list[dict]:
    conn = _connect()
    cur = conn.execute(
        "SELECT data FROM incidents ORDER BY timestamp DESC LIMIT ?", (limit,)
    )
    out = []
    for (data,) in cur.fetchall():
        try:
            out.append(json.loads(data))
        except (TypeError, ValueError):
            continue
    return out  # newest-first


async def init_activity_db() -> None:
    await asyncio.to_thread(_connect)


async def record_activity(event: dict) -> None:
    try:
        await asyncio.to_thread(_insert, event)
    except Exception:
        pass  # logging must never break the pipeline


async def fetch_activity(limit: int = 300, offset: int = 0) -> list[dict]:
    return await asyncio.to_thread(_fetch, limit, offset)


async def record_incident(doc: dict) -> None:
    try:
        await asyncio.to_thread(_upsert_incident, doc)
    except Exception:
        pass


async def fetch_incidents(limit: int = 50) -> list[dict]:
    return await asyncio.to_thread(_fetch_incidents, limit)
