from __future__ import annotations

import json
import sqlite3

from pipeline import config, live_workbench, webui
from pipeline.transcript_store import TranscriptStore


def _seed_event_db(path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, room_id TEXT, live_id TEXT, event_type TEXT, user_name TEXT, content TEXT, extra TEXT, ts INTEGER)"
    )
    con.executemany(
        "INSERT INTO events (room_id, live_id, event_type, user_name, content, extra, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("1001", "1001", "chat", "历史观众", "七月一日的问题？", "", 890_000),
            ("1001", "1001", "room_stats", "", "", json.dumps({"current": 1286}), 999_000),
            ("1001", "1001", "chat", "观众甲", "价格是多少？", "", 980_000),
            ("1001", "1001", "chat", "观众乙", "价格是多少？", "", 990_000),
            ("1001", "1001", "chat", "观众丙", "什么时候发货？", "", 995_000),
            ("1002", "1002", "chat", "其他房间", "不应出现？", "", 999_000),
        ],
    )
    con.commit()
    con.close()


def _seed_transcript_db(path) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE transcripts (id INTEGER PRIMARY KEY, room_id TEXT, text TEXT, created_ts INTEGER)")
    con.execute(
        "CREATE TABLE recording_timeline (id INTEGER PRIMARY KEY, room_id TEXT, seq INTEGER, kind TEXT, "
        "status TEXT, capture_start REAL, capture_end REAL, created_ts INTEGER)"
    )
    con.executemany(
        "INSERT INTO transcripts (room_id, text, created_ts) VALUES (?, ?, ?)",
        [
            ("1001", "七月一日历史转写", 800),
            ("1001", "第一段真实转写", 970),
            ("1001", "第二段真实转写", 990),
            ("1002", "其他房间转写", 995),
        ],
    )
    con.executemany(
        "INSERT INTO recording_timeline (room_id, seq, kind, status, capture_start, capture_end, created_ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("1001", 1, "segment", "ok", 700, 820, 820),
            ("1001", 2, "segment", "ok", 900, 960, 960),
            ("1001", 3, "short", "short", 960, 1_000, 1_000),
            ("1002", 1, "segment", "ok", 900, 995, 995),
        ],
    )
    con.commit()
    con.close()


def test_workbench_only_lists_recording_rooms_and_reads_selected_room_data(tmp_path) -> None:
    event_db = tmp_path / "events.db"
    transcript_db = tmp_path / "transcripts.db"
    _seed_event_db(event_db)
    _seed_transcript_db(transcript_db)
    rooms = [
        {"rid": "1001", "phase": "recording", "anchor_name": "主播一", "recording_since": 900},
        {"rid": "1002", "phase": "waiting", "anchor_name": "主播二", "recording_since": 0},
    ]

    snapshot = live_workbench.build_snapshot(
        rooms, event_db=event_db, transcript_db=transcript_db, selected_rid="1001", now=1_000
    )

    assert snapshot["rooms"][0]["rid"] == "1001"
    assert snapshot["rooms"][0]["phase"] == "recording"
    assert snapshot["selected_rid"] == snapshot["room"]["session_id"]
    assert snapshot["room"]["anchor_name"] == "主播一"
    assert [row["text"] for row in snapshot["transcripts"]] == ["第一段真实转写", "第二段真实转写"]
    assert snapshot["stats"] == {"online": 1286, "chats_per_min": 3, "recording_seconds": 100, "events": 4}
    assert snapshot["questions"] == [
        {"text": "价格是多少？", "count": 2},
        {"text": "什么时候发货？", "count": 1},
    ]


def test_workbench_keeps_the_latest_completed_session_after_recording_stops(tmp_path) -> None:
    event_db = tmp_path / "events.db"
    transcript_db = tmp_path / "transcripts.db"
    _seed_event_db(event_db)
    _seed_transcript_db(transcript_db)

    snapshot = live_workbench.build_snapshot(
        [{"rid": "1001", "phase": "stopped", "anchor_name": "主播一", "recording_since": 0}],
        event_db=event_db,
        transcript_db=transcript_db,
        now=1_005,
    )

    assert len(snapshot["rooms"]) == 2
    assert snapshot["room"]["phase"] == "completed"
    assert snapshot["room"]["recording_since"] == 900
    assert snapshot["room"]["recording_end"] == 1_000
    assert snapshot["room"]["session_id"].startswith("history:1001:900:")
    assert [row["text"] for row in snapshot["transcripts"]] == ["第一段真实转写", "第二段真实转写"]
    assert snapshot["stats"] == {"online": 1286, "chats_per_min": 3, "recording_seconds": 100, "events": 4}


def test_workbench_can_select_an_older_completed_session_without_mixing_newer_text(tmp_path) -> None:
    event_db = tmp_path / "events.db"
    transcript_db = tmp_path / "transcripts.db"
    _seed_event_db(event_db)
    _seed_transcript_db(transcript_db)
    initial = live_workbench.build_snapshot(
        [{"rid": "1001", "phase": "stopped", "anchor_name": "主播一"}],
        event_db=event_db,
        transcript_db=transcript_db,
        now=1_005,
    )
    older = initial["rooms"][1]

    snapshot = live_workbench.build_snapshot(
        [{"rid": "1001", "phase": "stopped", "anchor_name": "主播一"}],
        event_db=event_db,
        transcript_db=transcript_db,
        selected_rid=older["session_id"],
        now=1_005,
    )

    assert snapshot["selected_rid"] == older["session_id"]
    assert [row["text"] for row in snapshot["transcripts"]] == ["七月一日历史转写"]


def test_workbench_never_uses_history_when_the_recording_start_time_is_missing(tmp_path) -> None:
    event_db = tmp_path / "events.db"
    transcript_db = tmp_path / "transcripts.db"
    _seed_event_db(event_db)
    _seed_transcript_db(transcript_db)

    snapshot = live_workbench.build_snapshot(
        [{"rid": "1001", "phase": "recording", "anchor_name": "主播一", "recording_since": 0}],
        event_db=event_db,
        transcript_db=transcript_db,
        now=1_000,
    )

    assert snapshot["transcripts"] == []
    assert snapshot["questions"] == []
    assert snapshot["stats"] == {"online": 0, "chats_per_min": 0, "recording_seconds": 0, "events": 0}


def test_workbench_returns_empty_selection_when_no_room_is_recording(tmp_path) -> None:
    snapshot = live_workbench.build_snapshot(
        [{"rid": "1002", "phase": "waiting", "anchor_name": "主播二"}],
        event_db=tmp_path / "missing-events.db",
        transcript_db=tmp_path / "missing-transcripts.db",
        now=1_000,
    )

    assert snapshot["rooms"] == []
    assert snapshot["selected_rid"] == ""
    assert snapshot["room"] is None


def test_workbench_api_reads_the_manager_snapshot_and_local_databases(tmp_path, monkeypatch) -> None:
    event_db = tmp_path / "events.db"
    transcript_db = tmp_path / "transcripts.db"
    _seed_event_db(event_db)
    _seed_transcript_db(transcript_db)
    monkeypatch.setattr(config, "EVENTS_DB", event_db)
    monkeypatch.setattr(config, "DB_PATH", transcript_db)
    monkeypatch.setattr(webui._mgr, "status", lambda: [
        {"rid": "1001", "phase": "recording", "anchor_name": "主播一", "recording_since": 900},
        {"rid": "1002", "phase": "waiting", "anchor_name": "主播二"},
    ])
    payload = json.loads(webui.api_live_workbench("1001").body)

    assert payload["selected_rid"] == payload["room"]["session_id"]
    assert payload["room"]["anchor_name"] == "主播一"
    assert payload["stats"]["online"] == 1286


def test_batch_control_apis_return_an_explicit_success_result(monkeypatch) -> None:
    monkeypatch.setattr(webui._mgr, "start_all", lambda: 2)
    monkeypatch.setattr(webui._mgr, "stop_all", lambda: 3)

    assert json.loads(webui.api_start_all().body) == {"ok": True, "started": 2}
    assert json.loads(webui.api_stop_all().body) == {"ok": True, "stopped": 3}


def test_transcript_store_persists_completed_session_boundaries_idempotently(tmp_path) -> None:
    db_path = tmp_path / "transcripts.db"
    store = TranscriptStore(db_path)
    store.complete_session("1001", 900, 1_000)
    store.complete_session("1001", 900, 1_005)
    store.close()

    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT room_id, started_ts, ended_ts FROM recording_sessions"
    ).fetchall()
    con.close()
    assert rows == [("1001", 900, 1_005)]
