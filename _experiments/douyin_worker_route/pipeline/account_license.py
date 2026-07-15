"""Verification of short-lived, server-signed account entitlement snapshots.

The signed payload is deliberately the only source accepted by the desktop for
commercial access.  The unwrapped JSON response remains useful to browser UI
clients during migration, but must never be used for local authorization.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from collections.abc import Mapping
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


_SCHEMA = "anyq.account-license.v1"
_ISSUER = "https://anyq.site"
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PRODUCT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_MAX_PAYLOAD_BYTES = 16 * 1024
_MAX_LICENSE_SECONDS = 600
_CLOCK_SKEW_SECONDS = 120


class AccountLicenseError(PermissionError):
    """The account snapshot is absent, invalid, expired, or for another app."""


def _base64url(value: object, *, field: str, max_bytes: int) -> bytes:
    text = str(value or "")
    if not text or len(text) > max_bytes * 2 or not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise AccountLicenseError(f"权益签名{field}格式无效")
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, binascii.Error) as exc:
        raise AccountLicenseError(f"权益签名{field}格式无效") from exc
    if not raw or len(raw) > max_bytes:
        raise AccountLicenseError(f"权益签名{field}长度无效")
    return raw


def _json_object(raw: bytes) -> dict[str, Any]:
    def no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise AccountLicenseError("权益签名载荷包含重复字段")
            result[key] = value
        return result

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AccountLicenseError("权益签名载荷格式无效") from exc
    if not isinstance(parsed, dict):
        raise AccountLicenseError("权益签名载荷格式无效")
    return parsed


def _public_key(encoded: str) -> Ed25519PublicKey:
    raw = _base64url(encoded, field="公钥", max_bytes=1024)
    try:
        key = serialization.load_der_public_key(raw)
    except ValueError as exc:
        raise AccountLicenseError("权益签名公钥无效") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise AccountLicenseError("权益签名公钥算法无效")
    return key


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AccountLicenseError(f"权益签名{field}无效")
    return value


def _validate_payload(payload: dict[str, Any], *, expected_audience: str, now: int) -> dict[str, Any]:
    if payload.get("typ") != _SCHEMA or payload.get("iss") != _ISSUER:
        raise AccountLicenseError("权益签名来源无效")
    if payload.get("aud") != expected_audience:
        raise AccountLicenseError("权益签名受众不匹配")
    issued_at = _integer(payload.get("issued_at"), "签发时间")
    signed_until = _integer(payload.get("signed_until"), "有效期")
    if signed_until <= issued_at or signed_until - issued_at > _MAX_LICENSE_SECONDS:
        raise AccountLicenseError("权益签名有效期无效")
    if issued_at > now + _CLOCK_SKEW_SECONDS:
        raise AccountLicenseError("权益签名签发时间异常")
    if now > signed_until:
        raise AccountLicenseError("权益签名已过期，请联网刷新账号")
    user = payload.get("user")
    products = payload.get("products")
    if not isinstance(user, dict) or not isinstance(products, list) or len(products) > 64:
        raise AccountLicenseError("权益签名账户数据无效")
    user_id = user.get("id")
    phone = user.get("phone")
    role = user.get("role")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0 or not isinstance(phone, str) or not re.fullmatch(r"1[3-9]\d{9}", phone) or not isinstance(role, str) or len(role) > 64:
        raise AccountLicenseError("权益签名账户数据无效")
    normalized_products: list[dict[str, Any]] = []
    seen_products: set[str] = set()
    for product in products:
        if not isinstance(product, dict):
            raise AccountLicenseError("权益签名产品数据无效")
        product_id = product.get("product_id")
        name = product.get("name")
        status = product.get("status")
        expires_at = product.get("expires_at")
        entitlements = product.get("entitlements")
        if (
            not isinstance(product_id, str)
            or not _PRODUCT_ID_RE.fullmatch(product_id)
            or product_id in seen_products
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > 120
            or status not in {"active", "expired"}
            or not isinstance(expires_at, str)
            or len(expires_at) > 64
            or not isinstance(entitlements, list)
            or len(entitlements) > 64
            or any(not isinstance(item, str) or not item.strip() or len(item) > 80 for item in entitlements)
        ):
            raise AccountLicenseError("权益签名产品数据无效")
        seen_products.add(product_id)
        normalized_products.append(
            {
                "product_id": product_id,
                "name": name.strip(),
                "status": status,
                "expires_at": expires_at,
                "entitlements": sorted(set(entitlements)),
            }
        )
    return {
        "user": {"id": user_id, "phone": phone, "role": role.strip() or "regular"},
        "products": normalized_products,
        "issued_at": issued_at,
        "signed_until": signed_until,
        "server_time": str(payload.get("server_time") or "")[:64],
    }


def verify_account_license(
    reply: Mapping[str, object],
    *,
    expected_audience: str,
    public_keys: Mapping[str, str],
    now: int | None = None,
) -> dict[str, Any]:
    """Return a normalized payload only after strict Ed25519 verification."""
    if not _PRODUCT_ID_RE.fullmatch(expected_audience):
        raise AccountLicenseError("客户端产品标识无效")
    envelope = reply.get("account_license")
    if not isinstance(envelope, Mapping):
        raise AccountLicenseError("账号服务器未返回权益签名")
    if envelope.get("schema") != _SCHEMA or envelope.get("alg") != "Ed25519":
        raise AccountLicenseError("权益签名算法或版本无效")
    key_id = envelope.get("key_id")
    if not isinstance(key_id, str) or not _KEY_ID_RE.fullmatch(key_id):
        raise AccountLicenseError("权益签名密钥标识无效")
    encoded_key = public_keys.get(key_id)
    if not isinstance(encoded_key, str):
        raise AccountLicenseError("权益签名密钥未知，请升级客户端")
    payload_bytes = _base64url(envelope.get("payload"), field="载荷", max_bytes=_MAX_PAYLOAD_BYTES)
    signature = _base64url(envelope.get("signature"), field="签名", max_bytes=128)
    if len(signature) != 64:
        raise AccountLicenseError("权益签名长度无效")
    try:
        _public_key(encoded_key).verify(signature, payload_bytes)
    except InvalidSignature as exc:
        raise AccountLicenseError("权益签名校验失败") from exc
    return _validate_payload(
        _json_object(payload_bytes),
        expected_audience=expected_audience,
        now=int(time.time()) if now is None else int(now),
    )
