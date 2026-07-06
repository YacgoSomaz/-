"""Client adapter for an external Douyin live WebSocket sidecar.

This optional adapter connects to an external JSON-emitting event service while
keeping the main app independent from any bundled WSS collector.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.parse import quote

import websocket


DEFAULT_SIDECAR_WS = os.environ.get("LIVEWATCH_DOUYIN_SIDECAR_WS", "ws://127.0.0.1:1088")


class EventSink(Protocol):
    def emit(self, **kwargs: Any) -> None:
        ...

    def set_room_meta(self, live_id: str, nickname: str) -> None:
        ...


def _first_str(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _get_path(data: Any, *keys: Any) -> Any:
    cur: Any = data
    for key in keys:
        if isinstance(cur, dict):
            cur = cur.get(key)
            continue
        if isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
            continue
        else:
            return None
    return cur


def _user_fields(data: dict[str, Any]) -> tuple[str, str]:
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    user_id = _first_str(
        user.get("id"),
        user.get("idStr"),
        user.get("id_str"),
        user.get("secUid"),
        user.get("sec_uid"),
        user.get("webRid"),
    )
    user_name = _first_str(
        user.get("nickname"),
        user.get("nickName"),
        user.get("nick_name"),
        user.get("displayName"),
        user.get("display_name"),
    )
    return user_id, user_name


def _method_to_event(data: dict[str, Any], live_id: str, fallback_room_id: str = "") -> dict[str, Any] | None:
    """Normalize sidecar JSON into the current ``SqliteSink.emit`` kwargs.

    The Go sidecar serializes protobuf with ``protojson``. Field names may be
    lowerCamelCase or legacy snake_case depending on the generated proto, so
    this mapper accepts both shapes.
    """
    method = str(data.get("method") or "")
    if not method:
        return None

    room_id = _first_str(
        data.get("roomId"),
        data.get("room_id"),
        _get_path(data, "common", "roomId"),
        _get_path(data, "common", "room_id"),
        fallback_room_id,
    )
    user_id, user_name = _user_fields(data)

    base = {
        "room_id": room_id,
        "live_id": live_id,
        "user_id": user_id,
        "user_name": user_name,
        "content": "",
        "extra": None,
    }

    if method == "WebcastChatMessage":
        return {**base, "event_type": "chat", "content": _first_str(data.get("content"))}

    if method == "WebcastGiftMessage":
        gift = data.get("gift") if isinstance(data.get("gift"), dict) else {}
        gift_name = _first_str(gift.get("name"), data.get("giftName"), data.get("gift_name"))
        combo_count = data.get("comboCount", data.get("combo_count"))
        return {
            **base,
            "event_type": "gift",
            "content": gift_name,
            "extra": {"gift_name": gift_name, "combo_count": combo_count},
        }

    if method == "WebcastLikeMessage":
        count = data.get("count", data.get("likeCount", data.get("like_count")))
        return {
            **base,
            "event_type": "like",
            "content": _first_str(count),
            "extra": {"count": count},
        }

    if method == "WebcastMemberMessage":
        return {**base, "event_type": "member", "content": "进入直播间", "extra": None}

    if method == "WebcastSocialMessage":
        return {**base, "event_type": "social", "content": "关注了主播", "extra": None}

    if method == "WebcastFansclubMessage":
        return {**base, "event_type": "fansclub", "content": _first_str(data.get("content")), "extra": None}

    if method == "WebcastRoomUserSeqMessage":
        current = data.get("total", data.get("onlineCount", data.get("online_count")))
        total_pv = data.get(
            "totalPvForAnchor",
            data.get("total_pv_for_anchor", data.get("totalPv", data.get("total_pv"))),
        )
        return {
            **base,
            "event_type": "stat",
            "content": f"current={current or 0};total_pv={total_pv or 0}",
            "extra": {"current": current or 0, "total_pv": total_pv or 0},
        }

    if method == "WebcastRoomStatsMessage":
        current = data.get("total", data.get("onlineCount", data.get("online_count")))
        total_pv = _first_str(
            data.get("displayValue"),
            data.get("display_value"),
            data.get("totalPvForAnchor"),
            data.get("total_pv_for_anchor"),
            data.get("totalPv"),
            data.get("total_pv"),
        )
        return {
            **base,
            "event_type": "stat",
            "content": f"current={current or 0};total_pv={total_pv or 0}",
            "extra": {"current": current or 0, "total_pv": total_pv or 0},
        }

    if method == "WebcastControlMessage":
        status = data.get("status")
        return {
            **base,
            "event_type": "control",
            "content": _first_str(status),
            "extra": {"status": status},
        }

    return None


@dataclass
class SidecarStatus:
    live: bool | None = None
    ended: bool = False
    message: str = ""
    room_id: str = ""
    retry_interval_seconds: int | None = None


class SidecarFetcher:
    """Drop-in style fetcher for a JSON-emitting Douyin sidecar service."""

    def __init__(
        self,
        live_id: str,
        sink: EventSink,
        *,
        base_ws: str = DEFAULT_SIDECAR_WS,
        on_status: Callable[[SidecarStatus], None] | None = None,
        on_metadata: Callable[[str, str], None] | None = None,
    ) -> None:
        self.live_id = str(live_id)
        self._sink = sink
        self._base_ws = base_ws.rstrip("/")
        self._on_status = on_status
        self._on_metadata = on_metadata
        self._stop = threading.Event()
        self._ws: websocket.WebSocketApp | None = None
        self._room_id = ""
        self._anchor_nick = ""
        self._anchor_avatar = ""
        self._page_state = "unknown"
        self._is_live = False

    @property
    def room_id(self) -> str:
        return self._room_id or self.live_id

    @property
    def anchor_nick(self) -> str:
        return self._anchor_nick

    @property
    def anchor_avatar(self) -> str:
        return self._anchor_avatar

    @property
    def page_state(self) -> str:
        return self._page_state

    @property
    def is_live(self) -> bool:
        return self._is_live

    def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass

    def start(self) -> None:
        url = f"{self._base_ws}/ws/{quote(self.live_id, safe='')}"
        self._ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws.run_forever(ping_interval=30, ping_timeout=10)

    def _handle_system(self, data: dict[str, Any]) -> None:
        event = data.get("event")
        if event != "live_status":
            return
        status = SidecarStatus(
            live=data.get("live") if isinstance(data.get("live"), bool) else None,
            ended=bool(data.get("ended")),
            message=_first_str(data.get("message")),
            room_id=_first_str(data.get("room_id"), data.get("roomId")),
            retry_interval_seconds=data.get("retry_interval_seconds"),
        )
        if status.room_id:
            self._room_id = status.room_id
        if status.live is True:
            self._is_live = True
            self._page_state = "room"
        elif status.live is False and status.ended:
            self._is_live = False
            self._page_state = "ended"
        elif status.live is False:
            self._is_live = False
            self._page_state = "unknown"
        if self._on_status is not None:
            self._on_status(status)

    def _on_message(self, _ws: websocket.WebSocketApp, message: str) -> None:
        if self._stop.is_set() or message == "pong":
            return
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return

        if data.get("type") == "system":
            self._handle_system(data)
            return

        live_name = _first_str(data.get("livename"), data.get("liveName"), data.get("title"))
        avatar = _first_str(data.get("avatarThumb"), _get_path(data, "avatar_thumb", "urlList", 0))
        if live_name:
            self._anchor_nick = live_name
            self._sink.set_room_meta(self.live_id, live_name)
        if avatar:
            self._anchor_avatar = avatar
        if self._on_metadata is not None and (live_name or avatar):
            self._on_metadata(live_name, avatar)

        event = _method_to_event(data, self.live_id, self.room_id)
        if event is not None:
            self._sink.emit(**event)

    def _on_error(self, _ws: websocket.WebSocketApp, _error: Any) -> None:
        self._page_state = "unknown"

    def _on_close(self, _ws: websocket.WebSocketApp, *_args: Any) -> None:
        self._is_live = False
        if not self._stop.is_set():
            time.sleep(0.1)
