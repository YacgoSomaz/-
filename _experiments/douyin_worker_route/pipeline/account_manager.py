"""Protected local account state backed by a signed remote entitlement snapshot.

The remote session is encrypted at rest and never crosses the local web API.
The local feature gate re-verifies the server's Ed25519 snapshot every time it
reads the state, so an unsigned `user`/`products` JSON response cannot unlock
the replay product.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import account_license, config, license_manager


_STORAGE = "livewatch-account-session-v2"
_REPLAY_ENTITLEMENT = "livewatch"
_REPLAY_FEATURES = frozenset({"live_monitor", "ai_replay", "short_video_ai", "lead_radar", "export"})


class AccountFeatureError(PermissionError):
    """Raised when the signed-in account has not purchased a feature."""


def _read(path: Path | None = None) -> dict[str, Any] | None:
    target = path or config.ACCOUNT_SESSION_PATH
    try:
        container = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # v1 has no signed envelope and can never authorize anything.  It is read
    # only long enough to reuse its protected remote session and refresh it
    # into v2, so existing users are not unnecessarily forced to re-login.
    if not isinstance(container, dict) or container.get("storage") not in {_STORAGE, "livewatch-account-session-v1"} or container.get("protected") is not True:
        return None
    raw = license_manager._unprotect_license_bytes(container)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write(payload: dict[str, Any], path: Path | None = None) -> None:
    target = path or config.ACCOUNT_SESSION_PATH
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    protected = license_manager._protect_license_bytes(raw)
    document = {"storage": _STORAGE, "protected": True, "version": 2, **protected}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _session_from(reply: dict[str, Any]) -> dict[str, str]:
    value = reply.get("remote_session")
    if not isinstance(value, dict):
        raise ValueError("账号登录结果不完整")
    name = str(value.get("cookie_name") or "").strip()
    token = str(value.get("cookie_value") or "").strip()
    if not name or not token:
        raise ValueError("账号登录结果不完整")
    return {"cookie_name": name, "cookie_value": token}


def _verified_payload(state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise account_license.AccountLicenseError("请先使用手机号登录")
    envelope = state.get("account_license")
    if not isinstance(envelope, dict):
        raise account_license.AccountLicenseError("账号权益签名缺失，请重新登录")
    return account_license.verify_account_license(
        {"account_license": envelope},
        expected_audience=config.ACCOUNT_PRODUCT_ID,
        public_keys=config.ACCOUNT_LICENSE_PUBLIC_KEYS,
    )


def _normalize_login(reply: dict[str, Any], session: dict[str, str]) -> dict[str, Any]:
    # Verify before persistence and retain the signed envelope itself.  Never
    # persist root-level `user`/`products`, because they are not authorization.
    envelope = reply.get("account_license")
    if not isinstance(envelope, dict):
        raise account_license.AccountLicenseError("账号服务器未返回权益签名")
    account_license.verify_account_license(
        {"account_license": envelope},
        expected_audience=config.ACCOUNT_PRODUCT_ID,
        public_keys=config.ACCOUNT_LICENSE_PUBLIC_KEYS,
    )
    return {"account_license": dict(envelope), "remote_session": session}


def save_login(reply: dict[str, Any]) -> None:
    """Verify a successful login and store only its signed envelope + session."""
    _write(_normalize_login(reply, _session_from(reply)))


def refresh_login(reply: dict[str, Any]) -> None:
    """Replace an expiring snapshot while preserving the protected session."""
    session = remote_session()
    if session is None:
        raise ValueError("请先使用手机号登录")
    _write(_normalize_login(reply, session))


def clear_login() -> None:
    try:
        config.ACCOUNT_SESSION_PATH.unlink()
    except OSError:
        pass


def remote_session() -> dict[str, str] | None:
    current = _read()
    session = current.get("remote_session") if isinstance(current, dict) else None
    if not isinstance(session, dict):
        return None
    name = str(session.get("cookie_name") or "").strip()
    value = str(session.get("cookie_value") or "").strip()
    return {"cookie_name": name, "cookie_value": value} if name and value else None


def _masked_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) == 11 else ""


def _active_replay_product(payload: dict[str, Any]) -> dict[str, Any] | None:
    for product in payload.get("products") or []:
        if not isinstance(product, dict) or product.get("product_id") != config.ACCOUNT_PRODUCT_ID:
            continue
        if product.get("status") != "active" or _REPLAY_ENTITLEMENT not in set(product.get("entitlements") or []):
            return None
        try:
            expires = datetime.fromisoformat(str(product.get("expires_at") or "").replace("Z", "+00:00"))
            if expires.tzinfo is None:
                return None
            if expires.astimezone(UTC) <= datetime.now(UTC):
                return None
        except ValueError:
            return None
        return product
    return None


def public_status() -> dict[str, Any]:
    try:
        payload = _verified_payload(_read())
    except account_license.AccountLicenseError:
        return {
            "logged_in": False,
            "phone": "",
            "role": "",
            "entitlements": [],
            "expires_at": "",
            "membership_plan": "",
            "membership_status": "",
            "products": [],
        }
    replay = _active_replay_product(payload)
    user = payload["user"]
    return {
        "logged_in": True,
        "phone": _masked_phone(str(user["phone"])),
        "role": str(user["role"]),
        "entitlements": list(replay.get("entitlements") or []) if replay else [],
        "expires_at": str(replay.get("expires_at") or "") if replay else "",
        "membership_plan": str(replay.get("name") or "") if replay else "",
        "membership_status": "active" if replay else "unopened",
        "products": list(payload["products"]),
    }


def require_feature(feature: str) -> None:
    """Allow only replay features backed by a current signed replay entitlement."""
    if feature not in _REPLAY_FEATURES:
        raise AccountFeatureError("当前账号尚未开通复盘虾会员权益，请前往账户中心开通后再使用")
    try:
        payload = _verified_payload(_read())
    except account_license.AccountLicenseError as exc:
        raise AccountFeatureError("请先使用手机号登录或刷新账号权益") from exc
    if _active_replay_product(payload) is not None:
        return
    raise AccountFeatureError("当前账号尚未开通复盘虾会员权益，请前往账户中心开通后再使用")
