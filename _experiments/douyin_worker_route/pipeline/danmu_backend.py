"""Danmu/backend selection without importing legacy vendor code."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from . import config
from .audio_only_fetcher import AudioOnlyFetcher
from .douyin_sidecar_client import SidecarFetcher, SidecarStatus
from .event_sink import SqliteSink


class DanmuFetcher(Protocol):
    live_id: str

    @property
    def room_id(self) -> str | None:
        ...

    @property
    def anchor_nick(self) -> str:
        ...

    @property
    def anchor_avatar(self) -> str:
        ...

    @property
    def page_state(self) -> str:
        ...

    @property
    def is_live(self) -> bool:
        ...

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...


def normalized_backend(value: str | None = None) -> str:
    backend = (value if value is not None else config.DANMU_BACKEND).strip().lower()
    return backend or "audio_only"


def is_managed_status_backend(value: str | None = None) -> bool:
    return normalized_backend(value) in {"audio_only", "sidecar"}


def create_fetcher(
    live_id: str,
    sink: SqliteSink,
    *,
    on_status: Callable[[SidecarStatus], None] | None = None,
    on_metadata: Callable[[str, str], None] | None = None,
    backend: str | None = None,
) -> DanmuFetcher:
    """Create a fetcher for the configured backend."""
    selected = normalized_backend(backend)
    if selected == "audio_only":
        return AudioOnlyFetcher(
            live_id,
            sink,
            on_status=on_status,
            on_metadata=on_metadata,
        )
    if selected == "sidecar":
        return SidecarFetcher(
            live_id,
            sink,
            base_ws=config.DOUYIN_SIDECAR_WS,
            on_status=on_status,
            on_metadata=on_metadata,
        )
    raise ValueError(f"Unsupported danmu backend: {selected}")


def backend_snapshot() -> dict[str, Any]:
    selected = normalized_backend()
    return {
        "backend": selected,
        "sidecar_ws": config.DOUYIN_SIDECAR_WS if selected == "sidecar" else "",
    }
