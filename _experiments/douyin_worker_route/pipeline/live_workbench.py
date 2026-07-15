"""Read-only live workbench snapshots built from local recording evidence.

The workbench never opens Douyin or invokes an AI model.  It reads the same
local SQLite stores and sealed video segments that the recorder already owns.
Active and completed sessions are represented explicitly so stopping a room
does not make the just-recorded evidence disappear or mix it with older data.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from . import video_preview


_SESSION_GAP_SEC = 75
_RECENT_SESSION_LIMIT = 12


def _session_id(prefix: str, rid: str, started_at: int, ended_at: int = 0) -> str:
    suffix = f":{int(ended_at)}" if ended_at else ""
    return f"{prefix}:{rid}:{int(started_at)}{suffix}"


def _recording_rooms(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return public fields for rooms actively being recorded."""
    result: list[dict[str, Any]] = []
    for room in rooms:
        if str(room.get("phase") or "") != "recording":
            continue
        rid = str(room.get("rid") or "")
        if not rid:
            continue
        started_at = int(room.get("recording_since") or 0)
        result.append({
            "session_id": _session_id("live", rid, started_at),
            "rid": rid,
            "anchor_name": str(room.get("anchor_name") or rid),
            "avatar_url": str(room.get("avatar_url") or ""),
            "recording_since": started_at,
            "recording_end": 0,
            "record_video": bool(room.get("record_video")),
            "phase": "recording",
        })
    return result


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def _read_completed_sessions(
    path: Path,
    rooms: list[dict[str, Any]],
    active_rooms: list[dict[str, Any]],
    *,
    video_root: Path | None = None,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    metadata = {
        str(room.get("rid") or ""): room
        for room in rooms
        if str(room.get("rid") or "")
    }
    if not metadata:
        return []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        explicit: list[tuple[str, int, int]] = []
        if _table_exists(con, "recording_sessions"):
            placeholders = ",".join("?" for _ in metadata)
            explicit = [
                (str(row[0]), int(row[1]), int(row[2]))
                for row in con.execute(
                    "SELECT room_id, started_ts, ended_ts FROM recording_sessions "
                    f"WHERE room_id IN ({placeholders}) AND ended_ts > started_ts "
                    "ORDER BY ended_ts DESC",
                    tuple(metadata),
                )
            ]

        inferred: list[tuple[str, int, int]] = []
        if _table_exists(con, "recording_timeline"):
            placeholders = ",".join("?" for _ in metadata)
            rows = con.execute(
                "SELECT room_id, capture_start, capture_end FROM recording_timeline "
                f"WHERE room_id IN ({placeholders}) "
                "AND capture_start IS NOT NULL AND capture_end IS NOT NULL "
                "AND capture_end > capture_start "
                "AND kind IN ('segment', 'short', 'partial') "
                "ORDER BY room_id, capture_start, id",
                tuple(metadata),
            ).fetchall()
            current: tuple[str, int, int] | None = None
            for raw_rid, raw_start, raw_end in rows:
                rid = str(raw_rid)
                start, end = int(float(raw_start)), int(float(raw_end))
                if current and current[0] == rid and start - current[2] <= _SESSION_GAP_SEC:
                    current = (rid, current[1], max(current[2], end))
                else:
                    if current:
                        inferred.append(current)
                    current = (rid, start, end)
            if current:
                inferred.append(current)
        con.close()
    except sqlite3.Error:
        return []

    # New recordings use exact session boundaries.  Timeline inference remains
    # for installations created before recording_sessions existed.
    sessions = list(explicit)
    for candidate in inferred:
        if any(
            candidate[0] == saved[0]
            and _overlaps((candidate[1], candidate[2]), (saved[1], saved[2]))
            for saved in explicit
        ):
            continue
        sessions.append(candidate)

    # Never duplicate the current live session as a completed historical one.
    active_windows = [
        (str(room["rid"]), int(room.get("recording_since") or 0))
        for room in active_rooms
        if int(room.get("recording_since") or 0) > 0
    ]
    sessions = [
        item for item in sessions
        if not any(item[0] == rid and item[2] >= start for rid, start in active_windows)
    ]
    sessions.sort(key=lambda item: (item[2], item[1]), reverse=True)

    result: list[dict[str, Any]] = []
    for rid, started_at, ended_at in sessions[:_RECENT_SESSION_LIMIT]:
        meta = metadata[rid]
        has_video = False
        if video_root is not None:
            has_video = video_preview.latest_sealed_video(
                video_root,
                rid,
                started_at=started_at,
                ended_at=ended_at,
            ) is not None
        result.append({
            "session_id": _session_id("history", rid, started_at, ended_at),
            "rid": rid,
            "anchor_name": str(meta.get("anchor_name") or rid),
            "avatar_url": str(meta.get("avatar_url") or ""),
            "recording_since": started_at,
            "recording_end": ended_at,
            "record_video": has_video,
            "phase": "completed",
        })
    return result


def _read_transcripts(
    path: Path,
    rid: str,
    recording_since: int,
    recording_end: int = 0,
) -> list[dict[str, Any]]:
    """Read text whose capture time falls inside exactly one session."""
    if not path.exists() or recording_since <= 0:
        return []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        if not _table_exists(con, "transcripts"):
            con.close()
            return []
        columns = _table_columns(con, "transcripts")
        time_columns = [name for name in ("capture_start", "segment_ts", "created_ts") if name in columns]
        if not time_columns:
            con.close()
            return []
        event_time = time_columns[0] if len(time_columns) == 1 else f"COALESCE({', '.join(time_columns)})"
        where = ["room_id = ?", f"{event_time} >= ?", "COALESCE(text, '') <> ''"]
        params: list[object] = [rid, recording_since]
        if recording_end > 0:
            where.append(f"{event_time} <= ?")
            params.append(recording_end)
        rows = con.execute(
            f"SELECT text, {event_time} AS event_time FROM transcripts "
            f"WHERE {' AND '.join(where)} ORDER BY event_time DESC, id DESC LIMIT 40",
            params,
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return []
    return [
        {"time": int(float(row[1] or 0)), "speaker": "主播", "text": str(row[0] or "")}
        for row in reversed(rows)
    ]


def _read_events(
    path: Path,
    rid: str,
    recording_since: int,
    recording_end: int,
    now: int,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    empty = {"online": 0, "chats_per_min": 0, "events": 0}
    if not path.exists() or recording_since <= 0:
        return empty, []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        if not _table_exists(con, "events"):
            con.close()
            return empty, []
        where = ["(live_id = ? OR room_id = ?)", "ts >= ?"]
        params: list[object] = [rid, rid, recording_since * 1000]
        if recording_end > 0:
            where.append("ts <= ?")
            params.append(recording_end * 1000)
        rows = con.execute(
            "SELECT event_type, content, extra, ts FROM events "
            f"WHERE {' AND '.join(where)} ORDER BY ts ASC, id ASC",
            params,
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return empty, []

    online = 0
    questions: list[str] = []
    recent_chat_count = 0
    reference_time = recording_end or now
    cutoff_ms = reference_time * 1000 - 60_000
    for event_type, content, extra_raw, ts in rows:
        if str(event_type or "") in {"room_stats", "room_user_seq"}:
            try:
                extra = json.loads(extra_raw or "{}")
                online = int(extra.get("current") or 0)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        if str(event_type or "") != "chat":
            continue
        if int(ts or 0) >= cutoff_ms:
            recent_chat_count += 1
        text = str(content or "").strip()
        if text and (text.endswith("？") or text.endswith("?")):
            questions.append(text)

    counts = Counter(questions)
    first_seen: dict[str, int] = {}
    for index, text in enumerate(questions):
        first_seen.setdefault(text, index)
    ranked_questions = [
        {"text": text, "count": count}
        for text, count in sorted(counts.items(), key=lambda item: (-item[1], first_seen[item[0]]))[:5]
    ]
    return {"online": online, "chats_per_min": recent_chat_count, "events": len(rows)}, ranked_questions


def build_snapshot(
    rooms: list[dict[str, Any]],
    *,
    event_db: Path,
    transcript_db: Path,
    selected_rid: str | None = None,
    now: int,
    video_root: Path | None = None,
) -> dict[str, Any]:
    """Build one active or completed session snapshot from local evidence."""
    active = _recording_rooms(rooms)
    completed = _read_completed_sessions(
        transcript_db,
        rooms,
        active,
        video_root=video_root,
    )
    available = active + completed
    selection = str(selected_rid or "")
    selected = next((item for item in available if item["session_id"] == selection), None)
    # Compatibility with older clients that sent a room id instead of session id.
    if selected is None:
        selected = next((item for item in available if item["rid"] == selection), None)
    if selected is None and available:
        selected = available[0]
    if selected is None:
        return {
            "rooms": [], "selected_rid": "", "room": None, "transcripts": [],
            "stats": {"online": 0, "chats_per_min": 0, "recording_seconds": 0, "events": 0},
            "questions": [],
        }

    started_at = int(selected.get("recording_since") or 0)
    ended_at = int(selected.get("recording_end") or 0)
    event_stats, questions = _read_events(
        event_db, selected["rid"], started_at, ended_at, now
    )
    recording_seconds = max(0, (ended_at or now) - started_at) if started_at else 0
    return {
        "rooms": available,
        "selected_rid": selected["session_id"],
        "room": selected,
        "transcripts": _read_transcripts(transcript_db, selected["rid"], started_at, ended_at),
        "stats": {**event_stats, "recording_seconds": recording_seconds},
        "questions": questions,
    }
