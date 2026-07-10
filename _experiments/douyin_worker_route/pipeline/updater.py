"""Client-side update checks for the packaged desktop app.

The updater is intentionally conservative:
  - update manifests must come from the HTTPS licensing server;
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
            "notes": self.notes,
        }


def _server_url() -> str:
    url = config.LICENSE_SERVER_URL.strip().rstrip("/")
    if not url.startswith("https://"):
        raise UpdateError("未配置 HTTPS 更新服务器")
    return url


def _safe_installer_name(version: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_.-]+", "_", version or "latest").strip("._") or "latest"
    return f"LiveWatchSetup_{clean}.exe"


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
        response = get(
            f"{_server_url()}/v1/update",
            params={
                "product_code": config.LICENSE_PRODUCT_CODE,
                "current_version": config.LICENSE_APP_VERSION,
            },
            timeout=config.LICENSE_REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise UpdateError("无法连接更新服务器") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise UpdateError("更新服务器返回格式异常") from exc
    if int(getattr(response, "status_code", 200)) >= 400 or not isinstance(data, dict):
        raise UpdateError(str(data.get("detail") if isinstance(data, dict) else "") or "检查更新失败")

    latest = str(data.get("latest_version") or "").strip()
    url = str(data.get("installer_url") or "").strip()
    digest = str(data.get("sha256") or "").strip().lower()
    server_has_update = bool(data.get("has_update")) and latest and url and digest
    should_update = server_has_update and _version_lt(config.LICENSE_APP_VERSION, latest)
    mandatory = bool(data.get("mandatory")) or _version_lt(config.LICENSE_APP_VERSION, str(data.get("min_version") or ""))

    return UpdateManifest(
        has_update=should_update,
        current_version=config.LICENSE_APP_VERSION,
        latest_version=latest,
        min_version=str(data.get("min_version") or "").strip(),
        mandatory=mandatory,
        installer_url=url if should_update else "",
        sha256=digest if should_update else "",
        notes=str(data.get("notes") or "").strip(),
    )


def download_update(manifest: UpdateManifest | None = None, *, get=requests.get) -> Path:
    manifest = manifest or check_update(get=get)
    if not manifest.has_update:
        raise UpdateError("当前已经是最新版本")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest.sha256):
        raise UpdateError("更新包校验信息无效")
    parsed = urlparse(manifest.installer_url)
    if parsed.scheme != "https":
        raise UpdateError("更新包必须通过 HTTPS 下载")
    target = _updates_dir() / _safe_installer_name(manifest.latest_version)
    if target.exists() and _sha256_file(target) == manifest.sha256:
        return target

    tmp = target.with_suffix(target.suffix + f".{int(time.time())}.part")
    try:
        with get(manifest.installer_url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
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


def download_and_install(*, silent: bool = True) -> dict[str, Any]:
    manifest = check_update()
    installer = download_update(manifest)
    run_installer(installer, silent=silent)
    return {
        "installer": str(installer),
        "latest_version": manifest.latest_version,
        "silent": silent,
    }

