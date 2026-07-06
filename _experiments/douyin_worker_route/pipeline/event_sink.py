"""SQLite event sink for live comments and room events.

This is project-owned code. Keep it independent from any Douyin WSS backend so
the event database can be fed by an external sidecar service or future
self-developed collectors.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id    TEXT,
    live_id    TEXT,
    event_type TEXT,
    user_id    TEXT,
    user_name  TEXT,
    content    TEXT,
    extra      TEXT,
    ts         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ev_room ON events(room_id);
CREATE INDEX IF NOT EXISTS idx_ev_type ON events(event_type);

CREATE TABLE IF NOT EXISTS room_meta (
    live_id    TEXT PRIMARY KEY,
    nickname   TEXT,
    updated_ts INTEGER
);
"""


class SqliteSink:
    """Thread-safe event writer shared by live collectors and exports."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()
        self.counts: dict[str, int] = {}

    def emit(
        self,
        *,
        room_id: str,
        live_id: str,
        event_type: str,
        user_id: str = "",
        user_name: str = "",
        content: str = "",
        extra: dict | None = None,
    ) -> None:
        ts = int(time.time() * 1000)
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(room_id, live_id, event_type, user_id, user_name, content, extra, ts)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(room_id or ""),
                    str(live_id or ""),
                    event_type,
                    str(user_id or ""),
                    str(user_name or ""),
                    content or "",
                    json.dumps(extra, ensure_ascii=False) if extra else None,
                    ts,
                ),
            )
            self._conn.commit()
            self.counts[event_type] = self.counts.get(event_type, 0) + 1

    def set_room_meta(self, live_id: str, nickname: str) -> None:
        """Record or update anchor nickname for exports. Empty values are ignored."""
        if not nickname:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO room_meta(live_id, nickname, updated_ts) VALUES (?,?,?) "
                "ON CONFLICT(live_id) DO UPDATE SET "
                "nickname=excluded.nickname, updated_ts=excluded.updated_ts",
                (str(live_id or ""), nickname, int(time.time())),
            )
            self._conn.commit()

    def total(self) -> int:
        return sum(self.counts.values())

    def clear_all(self) -> None:
        """Clear live events and room nicknames while keeping the database file."""
        with self._lock:
            for table in ("events", "room_meta"):
                try:
                    self._conn.execute(f"DELETE FROM {table}")
                except sqlite3.Error:
                    pass
            self._conn.commit()
            self.counts.clear()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
