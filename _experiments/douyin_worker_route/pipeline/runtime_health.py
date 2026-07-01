"""Small thread-safe runtime health helpers."""

from __future__ import annotations

import threading
import time
import re


# 主播下播后直播间页的标记。正常下播绝不能误判成验证页，否则会触发假的风控冷却 +
# 要求用户重新验证（实测下播页会保留预加载的 captcha SDK 脚本，旧逻辑据此误判）。
_ENDED_MARKERS = ("直播已结束", "本场直播已结束", "已下播", "直播间已关闭", "暂未开播")
# 真验证页特有的「可见验证文案」——正常/下播页不会出现，命中即可确判验证页。
_STRONG_CHALLENGE_CN = ("安全验证", "滑块验证", "拖动滑块", "完成验证")
_STRONG_CHALLENGE_EN = ("security verification",)
# 仅是预加载的 SDK 脚本名，正常页面也内联，单独出现绝不能判验证页。
_WEAK_CHALLENGE = ("captcha", "verifycenter", "verify-center")
# 真验证页是个很小的中间页（约 6KB）；正常直播间/下播页都远大于此。弱标记只在小页面上才算数。
_CHALLENGE_PAGE_MAX_CHARS = 20000


def classify_room_page(text: str) -> str:
    """Classify a Douyin room-page response without another network request.

    返回 room / ended / challenge / unknown。关键：把「正常下播页（保留 inert captcha 脚本）」
    与「真验证墙（小中间页 / 可见验证文案）」严格区分，避免下播误触发风控冷却。
    """
    raw = text or ""
    lowered = raw.lower()
    # 1) 有房间/取流正面证据 → 直播间页（在播或刚下播仍带 roomStore）
    room_evidence = (
        re.search(r'roomId.{0,12}?(\d{5,})', raw, re.DOTALL),
        '"roomstore"' in lowered and '"roominfo"' in lowered,
        ".m3u8" in lowered,
    )
    if any(room_evidence):
        return "room"
    # 2) 明确的下播/未开播文案 → 已结束，绝非验证页
    if any(m in raw for m in _ENDED_MARKERS):
        return "ended"
    # 3) 真验证页：可见验证文案，或「小中间页 + SDK 脚本」
    if any(m in raw for m in _STRONG_CHALLENGE_CN) or any(m in lowered for m in _STRONG_CHALLENGE_EN):
        return "challenge"
    if len(raw) < _CHALLENGE_PAGE_MAX_CHARS and any(m in lowered for m in _WEAK_CHALLENGE):
        return "challenge"
    # 4) 其余（含「大页面只内联了 captcha 脚本」的下播页）→ 未知，交由调用方长退避重试，不进风控冷却
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
