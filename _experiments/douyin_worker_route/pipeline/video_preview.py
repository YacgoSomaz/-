"""Safe lookup for the latest closed local video segment used by the workbench."""

from __future__ import annotations

import time
from pathlib import Path


def latest_sealed_video(
    video_root: Path,
    rid: str,
    *,
    stable_age_sec: float = 3.0,
    now: float | None = None,
    started_at: float | None = None,
    ended_at: float | None = None,
) -> Path | None:
    """Return the newest MP4 not being written, without allowing path escapes."""
    root = video_root.resolve()
    room = (root / str(rid)).resolve()
    if room.parent != root or not room.is_dir():
        return None
    current_time = time.time() if now is None else float(now)
    candidates: list[Path] = []
    for path in room.glob("*.mp4"):
        try:
            stat = path.stat()
            if not path.is_file() or stat.st_size <= 50_000:
                continue
            if current_time - stat.st_mtime < stable_age_sec:
                continue
            # Segment filenames are implementation details, while mtime is the
            # stable evidence available for both old and new recordings.  A
            # small tolerance covers ffmpeg finalisation immediately after the
            # session boundary without leaking a neighbouring broadcast.
            if started_at is not None and stat.st_mtime < float(started_at) - 5:
                continue
            if ended_at is not None and stat.st_mtime > float(ended_at) + 10:
                continue
            candidates.append(path)
        except OSError:
            continue
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None
