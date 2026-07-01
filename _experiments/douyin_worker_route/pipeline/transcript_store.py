"""转写结果存储（SQLite）。

一段音频一行：房间号、对应 mp3、录制起止、文本、音量、时长。
后续打分/LLM 清洗从这里读。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id      TEXT NOT NULL,
    mp3_name     TEXT NOT NULL,
    segment_ts   INTEGER NOT NULL,   -- 录制开始的 epoch 秒
    duration_sec REAL,
    mean_volume  REAL,
    text         TEXT,
    char_count   INTEGER,
    created_ts   INTEGER NOT NULL,
    UNIQUE(mp3_name)
);
CREATE INDEX IF NOT EXISTS idx_transcripts_room ON transcripts(room_id);

CREATE TABLE IF NOT EXISTS recording_timeline (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id        TEXT NOT NULL,
    seq            INTEGER,
    kind           TEXT NOT NULL,     -- segment / gap / partial / short / stopped
    status         TEXT NOT NULL,     -- ok / short / partial / gap / failed / stopped
    file_path      TEXT,
    capture_start  REAL,
    capture_end    REAL,
    duration_sec   REAL,
    file_size      INTEGER,
    error          TEXT,
    transcribed_ts INTEGER,
    created_ts     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recording_timeline_room_time
    ON recording_timeline(room_id, capture_start);
CREATE UNIQUE INDEX IF NOT EXISTS idx_recording_timeline_room_seq
    ON recording_timeline(room_id, seq) WHERE seq IS NOT NULL;
"""


@dataclass(frozen=True)
class RecordingSegment:
    id: int
    room_id: str
    seq: int | None
    kind: str
    status: str
    file_path: str | None
    capture_start: float | None
    capture_end: float | None
    duration_sec: float | None
    file_size: int | None
    error: str | None


class TranscriptStore:
    """线程安全的转写库写入。"""

    def __init__(self, db_path: Path = config.DB_PATH) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._ensure_transcript_columns()
        self._conn.commit()

    def _ensure_transcript_columns(self) -> None:
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(transcripts)")}
        additions = {
            "segment_id": "INTEGER",
            "recording_status": "TEXT",
            "capture_start": "REAL",
            "capture_end": "REAL",
        }
        for name, ddl in additions.items():
            if name not in cols:
                self._conn.execute(f"ALTER TABLE transcripts ADD COLUMN {name} {ddl}")

    def add(
        self,
        room_id: str,
        mp3_name: str,
        segment_ts: int,
        text: str,
        duration_sec: float | None = None,
        mean_volume: float | None = None,
        segment_id: int | None = None,
        recording_status: str | None = None,
        capture_start: float | None = None,
        capture_end: float | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO transcripts "
                "(room_id, mp3_name, segment_ts, duration_sec, mean_volume, text, char_count, "
                "created_ts, segment_id, recording_status, capture_start, capture_end) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (room_id, mp3_name, segment_ts, duration_sec, mean_volume,
                 text, len(text or ""), int(time.time()), segment_id, recording_status,
                 capture_start, capture_end),
            )
            if segment_id is not None:
                self._conn.execute(
                    "UPDATE recording_timeline SET transcribed_ts = ? WHERE id = ?",
                    (int(time.time()), segment_id),
                )
            self._conn.commit()

    def has(self, mp3_name: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM transcripts WHERE mp3_name = ? LIMIT 1", (mp3_name,)
            )
            return cur.fetchone() is not None

    def add_segment(
        self,
        room_id: str,
        seq: int,
        file_path: str,
        capture_start: float,
        capture_end: float,
        duration_sec: float,
        file_size: int,
        status: str = "ok",
        error: str | None = None,
        kind: str = "segment",
    ) -> int:
        """Upsert a sealed recording segment and return its timeline id."""
        return self._upsert_timeline(
            room_id=room_id,
            seq=seq,
            kind=kind,
            status=status,
            file_path=file_path,
            capture_start=capture_start,
            capture_end=capture_end,
            duration_sec=duration_sec,
            file_size=file_size,
            error=error,
        )

    def add_partial(
        self,
        room_id: str,
        seq: int,
        file_path: str,
        capture_start: float | None,
        capture_end: float | None,
        duration_sec: float | None,
        file_size: int,
        error: str | None = None,
    ) -> int:
        status = "short" if duration_sec and duration_sec > 0 else "partial"
        return self._upsert_timeline(
            room_id=room_id,
            seq=seq,
            kind="partial",
            status=status,
            file_path=file_path,
            capture_start=capture_start,
            capture_end=capture_end,
            duration_sec=duration_sec,
            file_size=file_size,
            error=error,
        )

    def add_gap(
        self,
        room_id: str,
        capture_start: float,
        capture_end: float,
        reason: str = "",
    ) -> int:
        duration = max(0.0, capture_end - capture_start)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO recording_timeline "
                "(room_id, seq, kind, status, file_path, capture_start, capture_end, "
                "duration_sec, file_size, error, created_ts) "
                "VALUES (?, NULL, 'gap', 'gap', NULL, ?, ?, ?, NULL, ?, ?)",
                (room_id, capture_start, capture_end, duration, reason, int(time.time())),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def max_seq(self, room_id: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM recording_timeline WHERE room_id = ?",
                (room_id,),
            )
            return int(cur.fetchone()[0] or 0)

    def pending_sealed_segments(self, room_id: str | None = None) -> list[RecordingSegment]:
        """Segments that are sealed in the timeline and not yet transcribed."""
        where = [
            "rt.file_path IS NOT NULL",
            # partial 是断流/停止时留下的已封口短段；只要探测到真实时长和文件内容，
            # 它同样是有效话术证据，必须进入转写队列。
            "(rt.kind IN ('segment', 'short') OR "
            "(rt.kind = 'partial' AND COALESCE(rt.duration_sec, 0) > 0 "
            "AND COALESCE(rt.file_size, 0) > 0))",
            "rt.transcribed_ts IS NULL",
            "tr.id IS NULL",
        ]
        params: list[object] = []
        if room_id is not None:
            where.append("rt.room_id = ?")
            params.append(room_id)
        sql = (
            "SELECT rt.* FROM recording_timeline rt "
            "LEFT JOIN transcripts tr ON tr.segment_id = rt.id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY rt.capture_start, rt.id"
        )
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [self._row_to_segment(r) for r in rows]

    def mark_transcribed(self, segment_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE recording_timeline SET transcribed_ts = ? WHERE id = ?",
                (int(time.time()), segment_id),
            )
            self._conn.commit()

    def _upsert_timeline(
        self,
        *,
        room_id: str,
        seq: int,
        kind: str,
        status: str,
        file_path: str | None,
        capture_start: float | None,
        capture_end: float | None,
        duration_sec: float | None,
        file_size: int | None,
        error: str | None,
    ) -> int:
        with self._lock:
            existing = self._conn.execute(
                "SELECT id FROM recording_timeline WHERE room_id = ? AND seq = ?",
                (room_id, seq),
            ).fetchone()
            if existing:
                segment_id = int(existing["id"])
                self._conn.execute(
                    "UPDATE recording_timeline SET kind = ?, status = ?, file_path = ?, "
                    "capture_start = ?, capture_end = ?, duration_sec = ?, file_size = ?, error = ? "
                    "WHERE id = ?",
                    (kind, status, file_path, capture_start, capture_end, duration_sec,
                     file_size, error, segment_id),
                )
            else:
                cur = self._conn.execute(
                    "INSERT INTO recording_timeline "
                    "(room_id, seq, kind, status, file_path, capture_start, capture_end, "
                    "duration_sec, file_size, error, created_ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (room_id, seq, kind, status, file_path, capture_start, capture_end,
                     duration_sec, file_size, error, int(time.time())),
                )
                segment_id = int(cur.lastrowid)
            self._conn.commit()
            return segment_id

    @staticmethod
    def _row_to_segment(row: sqlite3.Row) -> RecordingSegment:
        return RecordingSegment(
            id=int(row["id"]),
            room_id=row["room_id"],
            seq=row["seq"],
            kind=row["kind"],
            status=row["status"],
            file_path=row["file_path"],
            capture_start=row["capture_start"],
            capture_end=row["capture_end"],
            duration_sec=row["duration_sec"],
            file_size=row["file_size"],
            error=row["error"],
        )

    def clear_all(self) -> None:
        """清空所有转写与录制台账（一键清除数据用）。库文件保留，只删行。"""
        with self._lock:
            for table in ("transcripts", "recording_timeline"):
                try:
                    self._conn.execute(f"DELETE FROM {table}")
                except sqlite3.Error:
                    pass
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
