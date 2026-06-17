"""Read-only runtime diagnostics for the local control panel."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path

COOKIE_TTL_SEC = 8 * 3600


def cookie_status(cache_path: Path, now: float | None = None) -> dict[str, object]:
    now = time.time() if now is None else now
    result: dict[str, object] = {
        "state": "missing",
        "has_ttwid": False,
        "has_odin_tt": False,
        "minted_ts": None,
        "age_sec": None,
    }
    if not cache_path.exists():
        return result
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        jar = dict(data.get("jar") or {})
        minted = float(data.get("ts") or 0)
    except (OSError, ValueError, TypeError):
        result["state"] = "invalid"
        return result
    age = max(0, int(now - minted)) if minted else None
    result.update({
        "has_ttwid": bool(jar.get("ttwid")),
        "has_odin_tt": bool(jar.get("odin_tt")),
        "minted_ts": int(minted) if minted else None,
        "age_sec": age,
    })
    if not jar.get("ttwid"):
        result["state"] = "invalid"
    elif age is not None and age > COOKIE_TTL_SEC:
        result["state"] = "expired"
    else:
        result["state"] = "ready"
    return result


def _scalar(db_path: Path, sql: str) -> int:
    if not db_path.exists():
        return 0
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute(sql).fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            con.close()
    except sqlite3.Error:
        return 0


def _speaker_pending(db_path: Path, speaker_db_path: Path) -> int:
    total = _scalar(db_path, "SELECT COUNT(*) FROM transcripts")
    labeled = _scalar(speaker_db_path, "SELECT COUNT(*) FROM speaker_labels")
    return max(0, total - labeled)


def build_snapshot(config_module, now: float | None = None) -> dict[str, object]:
    now = time.time() if now is None else now
    audio_files = list(config_module.AUDIO_DIR.glob("*/*.mp3"))
    latest_audio_ts = max((p.stat().st_mtime for p in audio_files), default=None)
    audio_bytes = sum(p.stat().st_size for p in audio_files)
    usage = shutil.disk_usage(getattr(config_module, "DATA_DIR", config_module.ROUTE_DIR))
    sensevoice = bool(config_module.MODEL_ONNX.exists() and config_module.MODEL_TOKENS.exists())
    speaker = bool(config_module.SPEAKER_MODEL.exists())
    return {
        "cookie": cookie_status(getattr(config_module, "COOKIE_CACHE", config_module.ROUTE_DIR / "browser_cookies.json"), now),
        "models": {
            "sensevoice": sensevoice,
            "speaker": speaker,
            "ready": sensevoice and speaker,
        },
        "storage": {
            "free_gb": round(usage.free / (1024 ** 3), 2),
            "audio_gb": round(audio_bytes / (1024 ** 3), 3),
            "audio_files": len(audio_files),
        },
        "queues": {
            "transcription_pending": _scalar(
                config_module.DB_PATH,
                "SELECT COUNT(*) FROM recording_timeline "
                "WHERE kind IN ('segment','short') AND transcribed_ts IS NULL",
            ),
            "speaker_pending": _speaker_pending(
                config_module.DB_PATH, config_module.SPEAKER_DB_PATH
            ),
        },
        "latest_audio_ts": int(latest_audio_ts) if latest_audio_ts else None,
    }
