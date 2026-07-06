import os
import sys

import pytest

from pipeline import danmu_backend
from pipeline.audio_only_fetcher import AudioOnlyFetcher
from pipeline.douyin_sidecar_client import SidecarFetcher


class FakeSink:
    def emit(self, **_kwargs):
        pass

    def set_room_meta(self, _live_id: str, _nickname: str) -> None:
        pass


def test_backend_normalization_defaults_to_audio_only(monkeypatch) -> None:
    monkeypatch.setattr(danmu_backend.config, "DANMU_BACKEND", "")

    assert danmu_backend.normalized_backend() == "audio_only"


def test_factory_returns_audio_only_fetcher_by_default_without_importing_legacy_worker(monkeypatch) -> None:
    sys.modules.pop("run_worker", None)
    monkeypatch.setattr(danmu_backend.config, "DANMU_BACKEND", "")

    fetcher = danmu_backend.create_fetcher("123", FakeSink())

    assert isinstance(fetcher, AudioOnlyFetcher)
    assert "run_worker" not in sys.modules


def test_factory_returns_sidecar_fetcher_without_importing_legacy_worker(monkeypatch) -> None:
    sys.modules.pop("run_worker", None)
    monkeypatch.setattr(danmu_backend.config, "DANMU_BACKEND", "sidecar")
    monkeypatch.setattr(danmu_backend.config, "DOUYIN_SIDECAR_WS", "ws://127.0.0.1:1999")

    fetcher = danmu_backend.create_fetcher("123", FakeSink())

    assert isinstance(fetcher, SidecarFetcher)
    assert "run_worker" not in sys.modules


def test_factory_rejects_unknown_backend(monkeypatch) -> None:
    monkeypatch.setattr(danmu_backend.config, "DANMU_BACKEND", "unknown")

    with pytest.raises(ValueError, match="Unsupported danmu backend"):
        danmu_backend.create_fetcher("123", FakeSink())


def test_factory_rejects_legacy_vendor_backend(monkeypatch) -> None:
    sys.modules.pop("run_worker", None)
    monkeypatch.setattr(danmu_backend.config, "DANMU_BACKEND", "vendor")

    with pytest.raises(ValueError, match="Unsupported danmu backend"):
        danmu_backend.create_fetcher("123", FakeSink())

    assert "run_worker" not in sys.modules


def test_importing_backend_module_does_not_change_cwd() -> None:
    before = os.getcwd()
    __import__("pipeline.danmu_backend")

    assert os.getcwd() == before
