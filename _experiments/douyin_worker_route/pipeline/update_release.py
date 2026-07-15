"""Verification for server-signed desktop update releases.

The installer URL, hash, version and mandatory-update flag are untrusted until
the full release payload passes Ed25519 verification.  This is deliberately
separate from the account entitlement key and accepts only this desktop's
product audience.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import config


_SCHEMA = "anyq.desktop-update.v1"
_TYPE = "desktop-release"
_ISSUER = "https://anyq.site"
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PRODUCT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_PAYLOAD_BYTES = 32 * 1024
_MAX_RELEASE_SECONDS = 86_400
_CLOCK_SKEW_SECONDS = 120
_DOWNLOAD_HOSTS = {"download.anyq.site"}


class UpdateReleaseError(RuntimeError):
    """The server did not provide a safe, signed update release."""


def _base64url(value: object, *, field: str, max_bytes: int) -> bytes:
    text = str(value or "")
    if not text or len(text) > max_bytes * 2 or not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise UpdateReleaseError(f"更新签名{field}格式无效")
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, binascii.Error) as exc:
        raise UpdateReleaseError(f"更新签名{field}格式无效") from exc
    if not raw or len(raw) > max_bytes:
        raise UpdateReleaseError(f"更新签名{field}长度无效")
    return raw


def _json_object(raw: bytes) -> dict[str, Any]:
    def no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise UpdateReleaseError("更新签名载荷包含重复字段")
            result[key] = value
        return result

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateReleaseError("更新签名载荷格式无效") from exc
    if not isinstance(parsed, dict):
        raise UpdateReleaseError("更新签名载荷格式无效")
    return parsed


def _public_key(encoded: str) -> Ed25519PublicKey:
    raw = _base64url(encoded, field="公钥", max_bytes=1024)
    try:
        key = serialization.load_der_public_key(raw)
    except ValueError as exc:
        raise UpdateReleaseError("更新签名公钥无效") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise UpdateReleaseError("更新签名公钥算法无效")
    return key


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise UpdateReleaseError(f"更新签名{field}无效")
    return value


def _iso_time(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise UpdateReleaseError(f"更新签名{field}无效")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UpdateReleaseError(f"更新签名{field}无效") from exc
    return value


def _validate_payload(payload: dict[str, Any], *, expected_audience: str, now: int) -> dict[str, Any]:
    if payload.get("typ") != _TYPE or payload.get("iss") != _ISSUER:
        raise UpdateReleaseError("更新签名来源无效")
    if payload.get("aud") != expected_audience or payload.get("product_id") != expected_audience:
        raise UpdateReleaseError("更新签名受众不匹配")
    issued_at = _integer(payload.get("issued_at"), "签发时间")
    signed_until = _integer(payload.get("signed_until"), "有效期")
    if signed_until <= issued_at or signed_until - issued_at > _MAX_RELEASE_SECONDS:
        raise UpdateReleaseError("更新签名有效期无效")
    if issued_at > now + _CLOCK_SKEW_SECONDS:
        raise UpdateReleaseError("更新签名签发时间异常")
    if now > signed_until:
        raise UpdateReleaseError("更新签名已过期，请稍后重试")
    version = payload.get("version")
    minimum = payload.get("min_supported_version")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version) or not isinstance(minimum, str) or not _VERSION_RE.fullmatch(minimum):
        raise UpdateReleaseError("更新签名版本信息无效")
    mandatory = payload.get("mandatory")
    if not isinstance(mandatory, bool):
        raise UpdateReleaseError("更新签名强制更新标识无效")
    installer_url = payload.get("installer_url")
    if not isinstance(installer_url, str) or len(installer_url) > 2048:
        raise UpdateReleaseError("更新签名下载地址无效")
    parsed = urlsplit(installer_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _DOWNLOAD_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.lower().endswith(".exe")
    ):
        raise UpdateReleaseError("更新签名下载地址无效")
    sha256 = payload.get("sha256")
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        raise UpdateReleaseError("更新签名 SHA-256 无效")
    size_bytes = payload.get("size_bytes")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or not 1 <= size_bytes <= 10 * 1024 * 1024 * 1024:
        raise UpdateReleaseError("更新签名安装包大小无效")
    notes = payload.get("notes")
    if not isinstance(notes, str) or len(notes) > 4000:
        raise UpdateReleaseError("更新签名说明无效")
    return {
        "product_id": expected_audience,
        "version": version,
        "min_supported_version": minimum,
        "mandatory": mandatory,
        "installer_url": installer_url,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "notes": notes,
        "published_at": _iso_time(payload.get("published_at"), "发布时间"),
        "issued_at": issued_at,
        "signed_until": signed_until,
    }


def verify_update_release(
    reply: Mapping[str, object],
    *,
    expected_audience: str,
    public_keys: Mapping[str, str],
    now: int | None = None,
) -> dict[str, Any]:
    """Return a normalized update release after strict Ed25519 verification."""
    if not _PRODUCT_ID_RE.fullmatch(expected_audience):
        raise UpdateReleaseError("客户端更新产品标识无效")
    envelope = reply.get("update_release")
    if not isinstance(envelope, Mapping):
        raise UpdateReleaseError("更新服务器未返回签名更新信息")
    if envelope.get("schema") != _SCHEMA or envelope.get("alg") != "Ed25519":
        raise UpdateReleaseError("更新签名算法或版本无效")
    key_id = envelope.get("key_id")
    if not isinstance(key_id, str) or not _KEY_ID_RE.fullmatch(key_id):
        raise UpdateReleaseError("更新签名密钥标识无效")
    encoded_key = public_keys.get(key_id)
    if not isinstance(encoded_key, str):
        raise UpdateReleaseError("更新签名密钥未知，请升级客户端")
    payload_bytes = _base64url(envelope.get("payload"), field="载荷", max_bytes=_MAX_PAYLOAD_BYTES)
    signature = _base64url(envelope.get("signature"), field="签名", max_bytes=128)
    if len(signature) != 64:
        raise UpdateReleaseError("更新签名长度无效")
    try:
        _public_key(encoded_key).verify(signature, payload_bytes)
    except InvalidSignature as exc:
        raise UpdateReleaseError("更新签名校验失败") from exc
    return _validate_payload(
        _json_object(payload_bytes),
        expected_audience=expected_audience,
        now=int(time.time()) if now is None else int(now),
    )


def fetch_update_release(
    *,
    server_url: str | None = None,
    expected_audience: str | None = None,
    public_keys: Mapping[str, str] | None = None,
    get: Any = requests.get,
) -> dict[str, Any] | None:
    """Fetch only the signed release envelope; root-level fields are ignored."""
    base_url = str(server_url or config.ACCOUNT_API_BASE_URL).strip().rstrip("/")
    audience = str(expected_audience or config.ACCOUNT_PRODUCT_ID).strip()
    keys = public_keys if public_keys is not None else config.UPDATE_RELEASE_PUBLIC_KEYS
    if not base_url.startswith("https://"):
        raise UpdateReleaseError("未配置 HTTPS 更新服务器")
    try:
        response = get(
            f"{base_url}/api/v1/releases/latest",
            params={"product_id": audience},
            timeout=config.ACCOUNT_REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise UpdateReleaseError("无法连接更新服务器") from exc
    try:
        data = response.json()
    except (ValueError, TypeError) as exc:
        raise UpdateReleaseError("更新服务器返回格式异常") from exc
    if not isinstance(data, dict) or int(getattr(response, "status_code", 200)) >= 400 or not data.get("ok"):
        raise UpdateReleaseError("检查更新失败")
    if data.get("update_release") is None:
        return None
    return verify_update_release(data, expected_audience=audience, public_keys=keys)
