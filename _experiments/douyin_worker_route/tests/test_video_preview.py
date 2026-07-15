from __future__ import annotations

import os
import time
from pathlib import Path

from pipeline import config, video_preview, webui


def test_latest_sealed_video_uses_the_newest_stable_mp4_inside_the_selected_room(tmp_path) -> None:
    room_dir = tmp_path / "58308379389"
    room_dir.mkdir()
    old = room_dir / "v00001.mp4"
    latest = room_dir / "v00002.mp4"
    writing = room_dir / "v00003.mp4"
    for path in (old, latest, writing):
        path.write_bytes(b"v" * 60_000)
    now = time.time()
    os.utime(old, (now - 120, now - 120))
    os.utime(latest, (now - 20, now - 20))
    os.utime(writing, (now, now))

    selected = video_preview.latest_sealed_video(tmp_path, "58308379389", stable_age_sec=3, now=now)

    assert selected == latest


def test_latest_sealed_video_rejects_room_path_escape_and_unstable_only_file(tmp_path) -> None:
    room_dir = tmp_path / "58308379389"
    room_dir.mkdir()
    current = room_dir / "v00001.mp4"
    current.write_bytes(b"v" * 60_000)

    assert video_preview.latest_sealed_video(tmp_path, "../outside", stable_age_sec=3, now=time.time()) is None
    assert video_preview.latest_sealed_video(tmp_path, "58308379389", stable_age_sec=3, now=time.time()) is None


def test_latest_sealed_video_can_be_limited_to_a_completed_session_window(tmp_path) -> None:
    room_dir = tmp_path / "58308379389"
    room_dir.mkdir()
    previous = room_dir / "v00001.mp4"
    selected = room_dir / "v00002.mp4"
    newer = room_dir / "v00003.mp4"
    for path in (previous, selected, newer):
        path.write_bytes(b"v" * 60_000)
    os.utime(previous, (800, 800))
    os.utime(selected, (980, 980))
    os.utime(newer, (1_200, 1_200))

    result = video_preview.latest_sealed_video(
        tmp_path,
        "58308379389",
        stable_age_sec=3,
        now=1_300,
        started_at=900,
        ended_at=1_000,
    )

    assert result == selected


def test_live_preview_api_serves_only_a_stable_segment_for_an_active_video_room(tmp_path, monkeypatch) -> None:
    room_dir = tmp_path / "58308379389"
    room_dir.mkdir()
    segment = room_dir / "v00001.mp4"
    segment.write_bytes(b"v" * 60_000)
    now = time.time()
    os.utime(segment, (now - 10, now - 10))
    monkeypatch.setattr(config, "VIDEO_DIR", tmp_path)
    monkeypatch.setattr(webui._mgr, "status", lambda: [
        {"rid": "58308379389", "phase": "recording", "record_video": True},
    ])

    response = webui.api_live_preview("58308379389")

    assert Path(response.path) == segment
