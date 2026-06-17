"""Small thread-safe runtime health helpers."""

from __future__ import annotations

import threading
import time
import re


def classify_room_page(text: str) -> str:
    """Classify a Douyin room-page response without another network request."""
    raw = text or ""
    lowered = raw.lower()
    # Normal room pages can preload captcha/VerifyCenter scripts even when the
    # trusted session is healthy. Positive room/stream evidence must win over
    # those inert script names, otherwise a live recording is falsely stopped.
    room_evidence = (
        re.search(r'roomId.{0,12}?(\d{5,})', raw, re.DOTALL),
        '"roomstore"' in lowered and '"roominfo"' in lowered,
        ".m3u8" in lowered,
    )
    if any(room_evidence):
        return "room"
    challenge_markers = (
        "captcha",
        "verifycenter",
        "verify-center",
        "security verification",
        "安全验证",
        "滑块验证",
    )
    if any(marker in lowered for marker in challenge_markers):
        return "challenge"
    return "unknown"


class GlobalCooldown:
    """Thread-safe circuit breaker for platform-wide risk-control events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until_ts = 0.0
        self._reason = ""

    def trigger(self, duration_sec: float, reason: str) -> None:
        until = time.time() + max(0.0, duration_sec)
        with self._lock:
            self._until_ts = max(self._until_ts, until)
            self._reason = reason

    def clear(self) -> None:
        with self._lock:
            self._until_ts = 0.0
            self._reason = ""

    def active(self) -> bool:
        with self._lock:
            return self._until_ts > time.time()

    def remaining_sec(self) -> int:
        with self._lock:
            return max(0, int(self._until_ts - time.time()))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            remaining = max(0, int(self._until_ts - time.time()))
            return {
                "active": remaining > 0,
                "until_ts": int(self._until_ts) if remaining > 0 else 0,
                "remaining_sec": remaining,
                "reason": self._reason if remaining > 0 else "",
            }


class ErrorRegistry:
    def __init__(self, limit: int = 20) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self._errors: dict[str, dict[str, object]] = {}

    def record(self, component: str, error: BaseException) -> None:
        with self._lock:
            self._errors[component] = {
                "component": component,
                "message": repr(error)[:500],
                "ts": int(time.time()),
            }
            if len(self._errors) > self._limit:
                oldest = min(self._errors, key=lambda key: int(self._errors[key]["ts"]))
                del self._errors[oldest]

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            return sorted(
                (dict(row) for row in self._errors.values()),
                key=lambda row: int(row["ts"]),
                reverse=True,
            )
