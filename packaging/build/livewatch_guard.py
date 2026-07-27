"""Compiled pre-launch guard for the commercial 复盘虾 desktop package.

The guard is intentionally separate from ``LiveWatchLauncher.exe``.  It
verifies the Ed25519-signed core manifest *before* handing control to the
PyInstaller launcher, so changing the launcher or the readable web UI alone
cannot silently disable the integrity gate.

It only covers shipped program files.  User data lives in LOCALAPPDATA and is
not inspected here: imported assets, exports, cookies and database files must
remain writable without making the application fail to start.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

APP_NAME = "复盘虾"
GUARD_EXE_NAME = "LiveWatchGuard.exe"
LAUNCHER_EXE_NAME = "LiveWatchLauncher.exe"
MANIFEST_NAME = "integrity_manifest.json"
MANIFEST_VERSION = 2
SIGNATURE_ALGORITHM = "Ed25519"
INTEGRITY_PUBLIC_KEY = "__LIVEWATCH_INTEGRITY_PUBLIC_KEY__"


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))


def _canonical_payload(manifest: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in manifest.items() if key != "signature"}
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_core_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").lower()
    if normalized in {
        "livewatchguard.exe",
        "livewatchlauncher.exe",
        "app/bin/node.exe",
        "app/sidecar/douyinlive.exe",
        "app/pipeline_data/frontend.html",
    }:
        return True
    if normalized.startswith("app/pipeline") and normalized.count("/") == 1 and normalized.endswith(".pyd"):
        return True
    return normalized.startswith("app/pipeline_data/static/") or normalized.startswith("app/pipeline_data/lexicons/")


def _verify_install_integrity(base: Path) -> list[str]:
    """Validate signature, every listed core hash and missing core records."""
    try:
        manifest = json.loads((base / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["缺少或无法读取程序完整性清单"]
    if not isinstance(manifest, dict) or manifest.get("version") != MANIFEST_VERSION:
        return ["程序完整性清单格式无效"]
    if manifest.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        return ["程序完整性清单签名算法无效"]
    signature = manifest.get("signature")
    files = manifest.get("files")
    if not isinstance(signature, str) or not signature or not isinstance(files, list):
        return ["程序完整性清单缺少签名"]
    try:
        verifier = Ed25519PublicKey.from_public_bytes(_base64url_decode(INTEGRITY_PUBLIC_KEY))
        verifier.verify(_base64url_decode(signature), _canonical_payload(manifest))
    except (ValueError, InvalidSignature):
        return ["程序完整性清单签名无效"]

    findings: list[str] = []
    covered: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            findings.append("程序完整性清单条目无效")
            continue
        relative = str(item.get("path") or "").replace("\\", "/")
        if not _is_core_path(relative):
            findings.append("程序完整性清单包含非核心文件")
            continue
        covered.add(relative.lower())
        target = base / relative
        expected_hash = str(item.get("sha256") or "")
        if not target.is_file():
            findings.append(f"核心文件缺失：{relative}")
        elif _sha256(target) != expected_hash:
            findings.append(f"核心文件已被修改：{relative}")

    for path in base.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if _is_core_path(relative) and relative.lower() not in covered:
            findings.append(f"核心文件未受签名清单保护：{relative}")
    return findings


def _show_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    base = Path(sys.executable).resolve().parent
    findings = _verify_install_integrity(base)
    if findings:
        _show_error("程序核心文件校验失败，无法安全启动。请从官网下载并重新安装。\n\n" + findings[0])
        return 1
    launcher = base / LAUNCHER_EXE_NAME
    if not launcher.is_file():
        _show_error("程序启动组件缺失，请重新安装复盘虾。")
        return 1
    try:
        subprocess.Popen([str(launcher)], cwd=str(base), close_fds=True)
    except OSError:
        _show_error("无法启动复盘虾，请重新安装。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
