"""Client-side update checks for the packaged desktop app.

The updater is intentionally conservative:
  - update manifests must be signed by the dedicated update-v1 key;
  - installers are downloaded to the user data directory, not the app folder;
  - SHA-256 must match the server manifest before the installer is launched.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from . import config
from .license_manager import _version_lt
from . import update_release


class UpdateError(RuntimeError):
    """User-safe update error."""


@dataclass
class _DownloadState:
    phase: str = "idle"
    downloaded_bytes: int = 0
    total_bytes: int = 0
    percent: float = 0.0
    speed_bytes_per_sec: float = 0.0
    latest_version: str = ""
    mandatory: bool = False
    notes: str = ""
    message: str = ""
    error: str = ""
    can_install: bool = False
    started_at: float = 0.0
    finished_at: float = 0.0


_download_lock = threading.RLock()
_download_state = _DownloadState()
_download_thread: threading.Thread | None = None


@dataclass(frozen=True)
class UpdateManifest:
    has_update: bool
    current_version: str
    latest_version: str
    min_version: str
    mandatory: bool
    installer_url: str
    sha256: str
    size_bytes: int
    notes: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "has_update": self.has_update,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "min_version": self.min_version,
            "mandatory": self.mandatory,
            "installer_url": self.installer_url,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "notes": self.notes,
            "install_dir": str(install_directory() or ""),
        }


def _safe_installer_name(version: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_.-]+", "_", version or "latest").strip("._") or "latest"
    return f"ReplayShrimpSetup_{clean}.exe"


def _updates_dir() -> Path:
    path = config.DATA_DIR / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def install_directory() -> Path | None:
    """Return the directory containing the running launcher, when frozen.

    The installer must be told this path explicitly.  Inno Setup otherwise
    falls back to its default directory when a customer originally selected a
    different location, leaving the desktop shortcut pointing at the old
    binary.  Source-mode runs intentionally return ``None``.
    """
    if not bool(getattr(sys, "frozen", False)):
        return None
    executable = Path(sys.executable).resolve()
    if executable.name.lower() != "livewatchlauncher.exe":
        return None
    return executable.parent


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_update(*, get=requests.get) -> UpdateManifest:
    try:
        release = update_release.fetch_update_release(get=get)
    except update_release.UpdateReleaseError as exc:
        raise UpdateError(str(exc)) from exc
    if release is None:
        return UpdateManifest(
            has_update=False,
            current_version=config.LICENSE_APP_VERSION,
            latest_version="",
            min_version="",
            mandatory=False,
            installer_url="",
            sha256="",
            size_bytes=0,
            notes="",
        )

    latest = str(release["version"])
    minimum = str(release["min_supported_version"])
    should_update = _version_lt(config.LICENSE_APP_VERSION, latest)
    mandatory = bool(release["mandatory"]) or _version_lt(config.LICENSE_APP_VERSION, minimum)

    return UpdateManifest(
        has_update=should_update,
        current_version=config.LICENSE_APP_VERSION,
        latest_version=latest,
        min_version=minimum,
        mandatory=mandatory,
        installer_url=str(release["installer_url"]) if should_update else "",
        sha256=str(release["sha256"]) if should_update else "",
        size_bytes=int(release["size_bytes"]) if should_update else 0,
        notes=str(release["notes"]),
    )


def _set_download_state(**changes: object) -> None:
    with _download_lock:
        for key, value in changes.items():
            if hasattr(_download_state, key):
                setattr(_download_state, key, value)


def download_status() -> dict[str, Any]:
    """Return a user-facing snapshot of the current background download."""
    with _download_lock:
        return {
            "phase": _download_state.phase,
            "downloaded_bytes": _download_state.downloaded_bytes,
            "total_bytes": _download_state.total_bytes,
            "percent": round(_download_state.percent, 1),
            "speed_bytes_per_sec": round(_download_state.speed_bytes_per_sec),
            "latest_version": _download_state.latest_version,
            "mandatory": _download_state.mandatory,
            "notes": _download_state.notes,
            "message": _download_state.message,
            "error": _download_state.error,
            "can_install": _download_state.can_install,
            "started_at": _download_state.started_at,
            "finished_at": _download_state.finished_at,
            "install_dir": str(install_directory() or ""),
        }


def _progress_callback(manifest: UpdateManifest, started: float) -> Callable[[int, int], None]:
    def update(done: int, total: int) -> None:
        elapsed = max(time.monotonic() - started, 0.001)
        speed = done / elapsed
        percent = min(100.0, done * 100.0 / total) if total else 0.0
        _set_download_state(
            downloaded_bytes=done,
            total_bytes=total,
            percent=percent,
            speed_bytes_per_sec=speed,
            message=f"正在下载更新包：{done / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB",
        )

    return update


def download_update(
    manifest: UpdateManifest | None = None,
    *,
    get=requests.get,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    manifest = manifest or check_update(get=get)
    if not manifest.has_update:
        raise UpdateError("当前已经是最新版本")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest.sha256):
        raise UpdateError("更新包校验信息无效")
    if not isinstance(manifest.size_bytes, int) or manifest.size_bytes < 1:
        raise UpdateError("更新包大小信息无效")
    parsed = urlparse(manifest.installer_url)
    if parsed.scheme != "https" or parsed.hostname != "download.anyq.site" or parsed.query or parsed.fragment:
        raise UpdateError("更新包下载地址无效")
    target = _updates_dir() / _safe_installer_name(manifest.latest_version)
    if target.exists() and _sha256_file(target) == manifest.sha256:
        if on_progress:
            on_progress(manifest.size_bytes, manifest.size_bytes)
        return target

    tmp = target.with_suffix(target.suffix + f".{int(time.time())}.part")
    try:
        with get(manifest.installer_url, stream=True, timeout=60) as response:
            response.raise_for_status()
            raw_length = str(getattr(response, "headers", {}).get("Content-Length", "")).strip()
            if raw_length and (not raw_length.isdigit() or int(raw_length) != manifest.size_bytes):
                raise UpdateError("更新包大小校验失败，已拒绝安装")
            written = 0
            with tmp.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        written += len(chunk)
                        if on_progress:
                            on_progress(written, manifest.size_bytes)
            if written != manifest.size_bytes:
                raise UpdateError("更新包大小校验失败，已拒绝安装")
        digest = _sha256_file(tmp)
        if digest != manifest.sha256:
            raise UpdateError("更新包校验失败，已拒绝安装")
        tmp.replace(target)
        return target
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def start_download(manifest: UpdateManifest | None = None, *, get=requests.get) -> dict[str, Any]:
    """Start a verified installer download in the background.

    Only the signed manifest is accepted.  The worker never exposes the URL to
    the UI and publishes byte-level progress through ``download_status``.
    """
    global _download_thread
    with _download_lock:
        if _download_state.phase in {"checking", "downloading", "installing"}:
            return download_status()
    manifest = manifest or check_update(get=get)
    if not manifest.has_update:
        raise UpdateError("当前已经是最新版本")
    started = time.monotonic()
    _set_download_state(
        phase="downloading",
        downloaded_bytes=0,
        total_bytes=manifest.size_bytes,
        percent=0.0,
        speed_bytes_per_sec=0.0,
        latest_version=manifest.latest_version,
        mandatory=manifest.mandatory,
        notes=manifest.notes,
        message="正在准备下载更新包…",
        error="",
        can_install=False,
        started_at=time.time(),
        finished_at=0.0,
    )

    def worker() -> None:
        global _download_thread
        try:
            installer = download_update(
                manifest,
                get=get,
                on_progress=_progress_callback(manifest, started),
            )
            _set_download_state(
                phase="ready",
                downloaded_bytes=manifest.size_bytes,
                total_bytes=manifest.size_bytes,
                percent=100.0,
                speed_bytes_per_sec=0.0,
                message=f"更新包 {manifest.latest_version} 已下载完成，可以安装。",
                error="",
                can_install=installer.exists(),
                finished_at=time.time(),
            )
        except Exception as exc:  # noqa: BLE001
            _set_download_state(
                phase="error",
                message="更新包下载失败",
                error=str(exc),
                can_install=False,
                finished_at=time.time(),
            )
        finally:
            _download_thread = None

    _download_thread = threading.Thread(target=worker, name="livewatch-update-download", daemon=True)
    _download_thread.start()
    return download_status()


def install_download(*, silent: bool = False) -> dict[str, Any]:
    """Launch an already verified installer after the UI confirms installation."""
    with _download_lock:
        if _download_state.phase != "ready" or not _download_state.can_install:
            raise UpdateError("更新包尚未下载完成")
        version = _download_state.latest_version
        installer = _updates_dir() / _safe_installer_name(version)
        mandatory = _download_state.mandatory
        _download_state.phase = "installing"
        _download_state.message = "正在启动安装向导…"
        _download_state.can_install = False
    run_installer(installer, silent=silent)
    return {"installer": str(installer), "latest_version": version, "silent": silent, "mandatory": mandatory}


def run_installer(
    installer: Path,
    *,
    silent: bool = True,
    install_dir: Path | None = None,
) -> None:
    if not installer.exists() or installer.suffix.lower() != ".exe":
        raise UpdateError("更新安装包不存在")
    args = [str(installer)]
    if silent:
        args.extend(["/VERYSILENT", "/NORESTART", "/CLOSEAPPLICATIONS"])
    else:
        args.append("/NORESTART")
    target_dir = install_dir or install_directory()
    if target_dir is not None:
        # Pass one *unquoted* argv item.  ``subprocess.Popen([...])`` performs
        # Windows quoting itself.  Embedding quotes here serializes as
        # ``/DIR=\"E:\\LiveWatch\"`` and Inno then loses the explicit target,
        # creating a second install at the registered/default directory.
        args.append(f"/DIR={Path(target_dir).resolve()}")
    subprocess.Popen(args, close_fds=True)


def download_and_install(*, silent: bool = False) -> dict[str, Any]:
    manifest = check_update()
    installer = download_update(manifest)
    run_installer(installer, silent=silent)
    return {
        "installer": str(installer),
        "latest_version": manifest.latest_version,
        "silent": silent,
    }

