"""HTTPS client for the remote mobile-number account service.

SMS provider credentials and WeChat Pay credentials stay on the remote service.
The desktop only receives the opaque, HttpOnly remote session cookie after a
successful verification and must never return that cookie to the web UI.
"""

from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from . import config


class AccountClientError(RuntimeError):
    """User-safe account service error."""


Post = Callable[..., Any]
Get = Callable[..., Any]
_COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def _server_url(value: str | None = None) -> str:
    url = (value if value is not None else config.ACCOUNT_API_BASE_URL).strip().rstrip("/")
    if not url.startswith("https://"):
        raise AccountClientError("未配置 HTTPS 账号服务器地址")
    return url


def _phone(value: str) -> str:
    phone = str(value or "").strip().removeprefix("+86")
    if phone.startswith("86") and len(phone) == 13:
        phone = phone[2:]
    if len(phone) != 11 or not phone.isdigit() or phone[0] != "1" or phone[1] not in "3456789":
        raise AccountClientError("请输入正确的手机号")
    return phone


def _json_response(response: Any) -> dict[str, Any]:
    try:
        data = response.json()
    except (ValueError, TypeError) as exc:
        raise AccountClientError("账号服务器返回格式异常") from exc
    if not isinstance(data, dict):
        raise AccountClientError("账号服务器返回格式异常")
    status = int(getattr(response, "status_code", 200))
    if not bool(data.get("ok")) or status >= 400:
        detail = str(data.get("error") or data.get("detail") or "账号操作失败")
        if status == 429:
            raise AccountClientError(detail[:200])
        if status >= 500:
            raise AccountClientError("账号服务暂时不可用，请稍后再试")
        raise AccountClientError(detail[:200])
    return data


def _session_cookie(session: dict[str, str]) -> str:
    name = str(session.get("cookie_name") or "").strip()
    value = str(session.get("cookie_value") or "").strip()
    if not _COOKIE_NAME_RE.fullmatch(name) or not value or any(char in value for char in "\r\n;"):
        raise AccountClientError("本地登录会话无效，请重新登录")
    return f"{name}={value}"


def _product_headers() -> dict[str, str]:
    """Bind a signed response to this compiled desktop product, not user input."""
    return {"X-Product-Code": config.ACCOUNT_PRODUCT_ID}


def _continue_url(value: object, server_url: str) -> str:
    url = str(value or "").strip()
    expected = urlsplit(server_url)
    target = urlsplit(url)
    if (
        target.scheme != "https"
        or (target.scheme, target.netloc) != (expected.scheme, expected.netloc)
        or not target.path.startswith("/account/")
        or not target.fragment.startswith("ticket=")
        or len(target.fragment) > 512
    ):
        raise AccountClientError("账号服务返回的跳转地址无效")
    return url


def send_sms_code(phone: str, *, server_url: str | None = None, post: Post = requests.post) -> dict[str, Any]:
    value = _phone(phone)
    url = _server_url(server_url)
    try:
        response = post(
            f"{url}/api/auth/send-code",
            json={"phone": value},
            timeout=config.ACCOUNT_REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise AccountClientError("无法连接账号服务器，请检查网络后重试") from exc
    return _json_response(response)


def login_with_sms(
    phone: str,
    code: str,
    *,
    server_url: str | None = None,
    post: Post = requests.post,
) -> dict[str, Any]:
    value = _phone(phone)
    verify_code = str(code or "").strip()
    if not verify_code.isdigit() or not 4 <= len(verify_code) <= 8:
        raise AccountClientError("请输入正确的验证码")
    url = _server_url(server_url)
    try:
        response = post(
            f"{url}/api/auth/login",
            json={"phone": value, "code": verify_code},
            headers=_product_headers(),
            timeout=config.ACCOUNT_REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise AccountClientError("无法连接账号服务器，请检查网络后重试") from exc
    data = _json_response(response)
    user = data.get("user")
    products = data.get("products")
    envelope = data.get("account_license")
    if not isinstance(user, dict) or not isinstance(products, list) or not isinstance(envelope, dict):
        raise AccountClientError("账号服务器返回内容不完整")
    cookies = getattr(response, "cookies", {})
    items = list(cookies.items()) if hasattr(cookies, "items") else []
    if len(items) != 1:
        raise AccountClientError("账号服务器未返回有效会话")
    cookie_name, cookie_value = (str(items[0][0]), str(items[0][1]))
    if not cookie_name or not cookie_value:
        raise AccountClientError("账号服务器未返回有效会话")
    return {
        "user": user,
        "products": products,
        "account_license": envelope,
        "expires_at": str(data.get("membershipExpiresAt") or user.get("membership_expires_at") or ""),
        "membership_plan": str(data.get("membershipPlan") or user.get("membership_plan") or ""),
        "membership_status": str(data.get("membershipStatus") or user.get("membership_status") or ""),
        "remote_session": {"cookie_name": cookie_name, "cookie_value": cookie_value},
    }


def refresh_account(
    session: dict[str, str],
    *,
    server_url: str | None = None,
    get: Get = requests.get,
) -> dict[str, Any]:
    """Fetch a newly signed snapshot with the protected remote session."""
    url = _server_url(server_url)
    headers = {"Cookie": _session_cookie(session), **_product_headers()}
    try:
        response = get(
            f"{url}/api/auth/me",
            headers=headers,
            timeout=config.ACCOUNT_REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise AccountClientError("无法连接账号服务器，请检查网络后重试") from exc
    data = _json_response(response)
    user = data.get("user")
    products = data.get("products")
    envelope = data.get("account_license")
    if not isinstance(user, dict) or not isinstance(products, list) or not isinstance(envelope, dict):
        raise AccountClientError("登录状态已过期，请重新登录")
    return {"user": user, "products": products, "account_license": envelope}


def create_recharge_handoff(
    session: dict[str, str],
    *,
    server_url: str | None = None,
    post: Post = requests.post,
) -> dict[str, str]:
    """Create a short-lived remote web handoff without exposing its session."""
    url = _server_url(server_url)
    try:
        response = post(
            f"{url}/api/auth/web-handoff",
            headers={"Cookie": _session_cookie(session)},
            timeout=config.ACCOUNT_REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise AccountClientError("无法连接账号服务器，请检查网络后重试") from exc
    data = _json_response(response)
    return {"continue_url": _continue_url(data.get("continueUrl"), url)}


def logout_remote_session(
    session: dict[str, str],
    *,
    server_url: str | None = None,
    post: Post = requests.post,
) -> None:
    """Invalidate the remote browser-session when the desktop user logs out."""
    url = _server_url(server_url)
    try:
        response = post(
            f"{url}/api/auth/logout",
            headers={"Cookie": _session_cookie(session)},
            timeout=config.ACCOUNT_REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise AccountClientError("无法连接账号服务器，请检查网络后重试") from exc
    _json_response(response)
