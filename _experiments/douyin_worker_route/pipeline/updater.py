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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from . import config
from .license_manager import _version_lt
from . import update_release


class UpdateError(RuntimeError):
    """User-safe update error."""


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
        }


def _safe_installer_name(version: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_.-]+", "_", version or "latest").strip("._") or "latest"
    return f"ReplayShrimpSetup_{clean}.exe"


def _updates_dir() -> Path:
    path = config.DATA_DIR / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def download_update(manifest: UpdateManifest | None = None, *, get=requests.get) -> Path:
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


def run_installer(installer: Path, *, silent: bool = True) -> None:
    if not installer.exists() or installer.suffix.lower() != ".exe":
        raise UpdateError("更新安装包不存在")
    args = [str(installer)]
    if silent:
        args.extend(["/VERYSILENT", "/NORESTART", "/CLOSEAPPLICATIONS"])
    else:
        args.append("/NORESTART")
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

