from __future__ import annotations

import subprocess

from pipeline import config, updater
from pipeline.updater import UpdateManifest


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


def test_download_update_reports_progress_without_exposing_unverified_url(monkeypatch, tmp_path) -> None:
    class Response:
        headers = {"Content-Length": "6"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=0):
            assert chunk_size == 1024 * 1024
            yield b"abc"
            yield b"def"

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    digest = "bef57ec7f53a6d40beb640a780a639c83bc29ac8a9816f1fc6c5c6dcd93c4721"
    monkeypatch.setattr(updater, "_sha256_file", lambda _path: digest)
    progress: list[tuple[int, int]] = []

    updater.download_update(UpdateManifest(
        has_update=True,
        current_version="1.0.12",
        latest_version="1.0.13",
        min_version="1.0.12",
        mandatory=False,
        installer_url="https://download.anyq.site/replay-shrimp/1.0.13/ReplayShrimpSetup_1.0.13.exe",
        sha256=digest,
        size_bytes=6,
        notes="",
    ), get=lambda *_args, **_kwargs: Response(), on_progress=lambda done, total: progress.append((done, total)))

    assert progress == [(3, 6), (6, 6)]


def test_update_download_status_has_explicit_phases() -> None:
    status = updater.download_status()

    assert status["phase"] in {"idle", "downloading", "ready", "error", "installing"}
    assert "downloaded_bytes" in status
    assert "total_bytes" in status
    assert "percent" in status


def test_frozen_updater_uses_the_current_launcher_directory(monkeypatch, tmp_path) -> None:
    install_dir = tmp_path / "自定义安装目录"
    install_dir.mkdir()
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        updater.sys,
        "executable",
        str(install_dir / "LiveWatchLauncher.exe"),
    )

    assert updater.install_directory() == install_dir.resolve()


def test_run_installer_passes_current_directory_to_inno_setup(monkeypatch, tmp_path) -> None:
    install_dir = tmp_path / "安装位置"
    install_dir.mkdir()
    installer = tmp_path / "updates" / "ReplayShrimpSetup_1.1.18.exe"
    installer.parent.mkdir()
    installer.write_bytes(b"installer")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        updater.sys,
        "executable",
        str(install_dir / "LiveWatchLauncher.exe"),
    )
    captured: list[list[str]] = []

    def fake_popen(args, **_kwargs):
        captured.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    updater.run_installer(installer, silent=False)

    assert captured == [[
        str(installer),
        "/NORESTART",
        f'/DIR="{install_dir.resolve()}"',
    ]]
