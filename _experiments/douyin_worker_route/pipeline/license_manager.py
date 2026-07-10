"""Commercial license verification and feature gates.

The client is not trusted: it only verifies a license signed by the license
server. Private signing keys must never be bundled with the installer.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows platforms
    winreg = None

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import config, license_clock

FREE_FEATURES = {"basic"}
COMMERCIAL_FEATURES = {
    "export",
    "batch",
    "live_monitor",
    "ai_replay",
    "short_video_ai",
    "lead_radar",
}
ALL_FEATURES = FREE_FEATURES | COMMERCIAL_FEATURES


@dataclass(frozen=True)
class LicenseStatus:
    ok: bool
    mode: str
    reason: str
    features: set[str]
    payload: dict[str, Any]
    expires_at: int = 0
    grace_until: int = 0


class LicenseFeatureError(PermissionError):
    """Raised when a commercial capability is used without a valid license."""


def _b64url_decode(value: str) -> bytes:
    value = value.strip()
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _machine_guid_windows() -> str:
    if winreg is None:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value)
    except OSError:
        return ""


def device_fingerprint_parts() -> list[str]:
    """Return local-only fingerprint fields. Raw values are never uploaded."""
    parts = [
        f"os={platform.system()}",
        f"node={platform.node()}",
        f"machine={platform.machine()}",
        f"processor={platform.processor()}",
    ]
    if platform.system().lower() == "windows":
        guid = _machine_guid_windows()
        if guid:
            parts.append(f"machine_guid={guid}")
    else:
        for candidate in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
            try:
                raw = candidate.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if raw:
                parts.append(f"machine_id={raw}")
                break
    mac = uuid.getnode()
    if mac:
        parts.append(f"mac={mac:012x}")
    return [p.strip().lower() for p in parts if p and not p.endswith("=")]


def current_device_hash(*, salt: str | None = None, parts: list[str] | None = None) -> str:
    normalized = "\n".join(sorted(parts or device_fingerprint_parts()))
    product_salt = salt if salt is not None else config.LICENSE_PRODUCT_SALT
    return hashlib.sha256(f"{product_salt}\n{normalized}".encode("utf-8")).hexdigest()


def _load_license(path: Path | None = None) -> dict[str, Any] | None:
    target = path or config.LICENSE_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _public_key_from_config(public_key: str | None = None) -> Ed25519PublicKey:
    raw = (public_key if public_key is not None else config.LICENSE_PUBLIC_KEY).strip()
    if not raw:
        raise ValueError("未配置授权公钥")
    if "-----BEGIN" in raw:
        raise ValueError("请配置 base64/raw Ed25519 公钥，不要在客户端放私钥或 PEM 私钥")
    return Ed25519PublicKey.from_public_bytes(_b64url_decode(raw))


def verify_license(
    license_doc: dict[str, Any],
    *,
    public_key: str | None = None,
    now: int | None = None,
    expected_device_hash: str | None = None,
    product_code: str | None = None,
) -> LicenseStatus:
    now_ts = int(now if now is not None else time.time())
    product = product_code or config.LICENSE_PRODUCT_CODE
    try:
        payload_b64 = str(license_doc["payload"])
        signature_b64 = str(license_doc["signature"])
        alg = str(license_doc.get("alg") or "")
    except KeyError:
        return LicenseStatus(False, "invalid", "授权文件缺少字段", FREE_FEATURES, {})
    if alg and alg != "Ed25519":
        return LicenseStatus(False, "invalid", "授权签名算法不受支持", FREE_FEATURES, {})

    try:
        payload_bytes = _b64url_decode(payload_b64)
        signature = _b64url_decode(signature_b64)
        _public_key_from_config(public_key).verify(signature, payload_bytes)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (InvalidSignature, ValueError, json.JSONDecodeError, TypeError) as exc:
        return LicenseStatus(False, "invalid", f"授权验签失败：{exc}", FREE_FEATURES, {})

    if str(payload.get("product_code") or "") != product:
        return LicenseStatus(False, "invalid", "授权产品不匹配", FREE_FEATURES, payload)
    expected_hash = expected_device_hash or current_device_hash()
    if str(payload.get("device_hash") or "") != expected_hash:
        return LicenseStatus(False, "invalid", "授权不属于当前设备", FREE_FEATURES, payload)

    expires_at = int(payload.get("expires_at") or 0)
    grace_until = int(payload.get("grace_until") or expires_at)
    features = set(str(x) for x in (payload.get("features") or [])) | FREE_FEATURES
    features &= ALL_FEATURES
    if expires_at and now_ts <= expires_at:
        return LicenseStatus(True, "licensed", "授权有效", features, payload, expires_at, grace_until)
    if grace_until and now_ts <= grace_until:
        return LicenseStatus(True, "grace", "授权已到期，宽限期内可继续使用，请尽快联网刷新", features, payload, expires_at, grace_until)
    return LicenseStatus(False, "expired", "授权已过期", FREE_FEATURES, payload, expires_at, grace_until)


def current_status(*, now: int | None = None) -> LicenseStatus:
    if not config.LICENSE_ENFORCE:
        return LicenseStatus(True, "development", "开发模式未强制授权", ALL_FEATURES, {})
    doc = _load_license()
    if not doc:
        return LicenseStatus(False, "missing", "未激活，请输入卡密激活", FREE_FEATURES, {})
    status = verify_license(doc, now=now)
    if not status.ok:
        return status
    clock = license_clock.check_and_record(now=now)
    if not clock.ok:
        return LicenseStatus(
            False,
            "clock_error",
            clock.reason,
            FREE_FEATURES,
            status.payload,
            status.expires_at,
            status.grace_until,
        )
    return status


def has_feature(feature: str) -> bool:
    return feature in current_status().features


def require_feature(feature: str) -> None:
    """Require one feature without coupling license rules to the web framework."""
    status = current_status()
    if feature in status.features:
        return
    raise LicenseFeatureError(status.reason)


def public_status() -> dict[str, Any]:
    status = current_status()
    return {
        "ok": status.ok,
        "mode": status.mode,
        "reason": status.reason,
        "features": sorted(status.features),
        "enforced": config.LICENSE_ENFORCE,
        "expires_at": status.expires_at,
        "grace_until": status.grace_until,
    }


def save_license_doc(doc: dict[str, Any], path: Path | None = None) -> None:
    target = path or config.LICENSE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def install_license_doc(doc: dict[str, Any], path: Path | None = None) -> LicenseStatus:
    """Verify and persist a signed license package.

    Invalid licenses are rejected before writing, so a bad paste cannot replace
    a previously working local license file.
    """
    status = verify_license(doc)
    if not status.ok:
        return status
    save_license_doc(doc, path=path)
    return status
