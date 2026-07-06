"""Project-owned live-state fetcher used when no danmu sidecar is installed.

It does not connect to Douyin's WebSocket danmu protocol. Its only job is to
tell ``RoomManager`` whether the room currently has a playable stream, so the
existing audio/video recorder can run without the legacy vendored WSS worker.
"""

from __future__ import annotations

import threading
from typing import Callable

from .audio_capture import RiskControlChallenge, fetch_candidates
from .douyin_sidecar_client import SidecarStatus


class AudioOnlyFetcher:
    """Small fetcher facade that exposes the same status surface as WSS fetchers."""

    def __init__(
        self,
        live_id: str,
        _sink: object,
        *,
        on_status: Callable[[SidecarStatus], None] | None = None,
        on_metadata: Callable[[str, str], None] | None = None,
        poll_interval: float = 60.0,
    ) -> None:
        self.live_id = str(live_id)
        self._on_status = on_status
        self._on_metadata = on_metadata
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._room_id = self.live_id
        self._anchor_nick = ""
        self._anchor_avatar = ""
        self._page_state = "unknown"
        self._is_live = False

    @property
    def room_id(self) -> str:
        return self._room_id

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

    def start(self) -> None:
        while not self._stop.is_set():
            try:
                candidates, raw_count = fetch_candidates(self.live_id)
            except RiskControlChallenge:
                self._mark_waiting("房间页要求安全验证", retry_interval=300, page_state="challenge")
            except Exception as exc:  # noqa: BLE001
                self._mark_waiting(f"直播状态探测异常: {exc!r}", retry_interval=90)
            else:
                if candidates:
                    self._is_live = True
                    self._page_state = "room"
                    self._emit_status(SidecarStatus(live=True, ended=False, room_id=self.live_id))
                else:
                    detail = f"暂未发现直播流，原始候选 {raw_count} 条"
                    self._mark_waiting(detail, retry_interval=int(self._poll_interval))
            self._stop.wait(self._poll_interval if self._is_live else min(self._poll_interval, 60.0))

    def _mark_waiting(self, message: str, *, retry_interval: int, page_state: str = "unknown") -> None:
        self._is_live = False
        self._page_state = page_state
        self._emit_status(
            SidecarStatus(
                live=False,
                ended=False,
                message=message,
                room_id=self.live_id,
                retry_interval_seconds=retry_interval,
            )
        )

    def _emit_status(self, status: SidecarStatus) -> None:
        if self._on_status is not None:
            self._on_status(status)

