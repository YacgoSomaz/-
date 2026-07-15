from __future__ import annotations

from pipeline import config, updater


def _release(**changes: object) -> dict[str, object]:
    release: dict[str, object] = {
        "version": "1.0.13",
        "min_supported_version": "1.0.12",
        "mandatory": False,
        "installer_url": "https://download.anyq.site/replay-shrimp/1.0.13/ReplayShrimpSetup_1.0.13.exe",
        "sha256": "a" * 64,
        "size_bytes": 314_182_000,
        "notes": "修复更新安装与登录体验。",
    }
    release.update(changes)
    return release


def test_check_update_uses_only_the_verified_release_payload(monkeypatch) -> None:
    monkeypatch.setattr(config, "LICENSE_APP_VERSION", "1.0.12")
    monkeypatch.setattr(updater.update_release, "fetch_update_release", lambda **_: _release())

    manifest = updater.check_update()

    assert manifest.has_update is True
    assert manifest.latest_version == "1.0.13"
    assert manifest.installer_url.startswith("https://download.anyq.site/")
    assert manifest.size_bytes == 314_182_000


def test_check_update_has_no_update_when_the_server_has_no_published_release(monkeypatch) -> None:
    monkeypatch.setattr(config, "LICENSE_APP_VERSION", "1.0.12")
    monkeypatch.setattr(updater.update_release, "fetch_update_release", lambda **_: None)

    manifest = updater.check_update()

    assert manifest.has_update is False
    assert manifest.mandatory is False
    assert manifest.installer_url == ""
