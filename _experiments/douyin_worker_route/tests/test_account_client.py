from __future__ import annotations

import pytest

from pipeline import account_client


class _Response:
    def __init__(self, payload: dict[str, object], status_code: int = 200, cookies: dict[str, str] | None = None):
        self._payload = payload
        self.status_code = status_code
        self.cookies = cookies or {}

    def json(self) -> dict[str, object]:
        return self._payload


def test_login_uses_https_and_keeps_remote_session_out_of_public_user() -> None:
    captured: dict[str, object] = {}

    def post(url: str, **kwargs: object) -> _Response:
        captured["url"] = url
        captured.update(kwargs)
        return _Response(
            {
                "ok": True,
                "user": {
                    "id": 7,
                    "phone": "13800138000",
                    "role": "regular",
                    "entitlements": [],
                    "membership_plan": "专业版",
                "membership_status": "active",
                },
                "products": [],
                "account_license": {"schema": "anyq.account-license.v1", "alg": "Ed25519", "key_id": "account-v1", "payload": "opaque", "signature": "opaque"},
                "expiresAt": "2026-07-21T00:00:00.000Z",
                "membershipExpiresAt": "2026-08-21T00:00:00.000Z",
            },
            cookies={"wz_session": "remote-secret-token"},
        )

    result = account_client.login_with_sms(
        "13800138000",
        "123456",
        server_url="https://anyq.example",
        post=post,
    )

    assert captured["url"] == "https://anyq.example/api/auth/login"
    assert captured["json"] == {"phone": "13800138000", "code": "123456"}
    assert captured["headers"] == {"X-Product-Code": "replay_shrimp"}
    assert result["user"] == {
        "id": 7,
        "phone": "13800138000",
        "role": "regular",
        "entitlements": [],
        "membership_plan": "专业版",
        "membership_status": "active",
    }
    assert result["expires_at"] == "2026-08-21T00:00:00.000Z"
    assert result["membership_plan"] == "专业版"
    assert result["membership_status"] == "active"
    assert result["remote_session"] == {"cookie_name": "wz_session", "cookie_value": "remote-secret-token"}


def test_account_client_carries_signed_license_for_local_verification() -> None:
    def post(url: str, **kwargs: object) -> _Response:
        del url, kwargs
        return _Response(
            {
                "ok": True,
                "user": {"id": 7, "phone": "13800138000", "role": "regular"},
                "products": [{"product_id": "replay_shrimp", "status": "active", "entitlements": ["livewatch"]}],
                "account_license": {"schema": "anyq.account-license.v1", "alg": "Ed25519", "key_id": "account-v1", "payload": "signed-payload", "signature": "signed-signature"},
            },
            cookies={"wz_session": "remote-secret-token"},
        )

    result = account_client.login_with_sms("13800138000", "123456", server_url="https://anyq.example", post=post)

    assert result["account_license"]["key_id"] == "account-v1"
    assert result["products"][0]["product_id"] == "replay_shrimp"


def test_account_client_rejects_insecure_server_url() -> None:
    with pytest.raises(account_client.AccountClientError, match="HTTPS"):
        account_client.send_sms_code("13800138000", server_url="http://insecure.example")


def test_create_recharge_handoff_uses_private_cookie_and_returns_only_continue_url() -> None:
    captured: dict[str, object] = {}

    def post(url: str, **kwargs: object) -> _Response:
        captured["url"] = url
        captured.update(kwargs)
        return _Response({"ok": True, "continueUrl": "https://anyq.example/account/continue#ticket=one-time-ticket"})

    result = account_client.create_recharge_handoff(
        {"cookie_name": "wz_session", "cookie_value": "opaque-remote-session"},
        server_url="https://anyq.example",
        post=post,
    )

    assert captured["url"] == "https://anyq.example/api/auth/web-handoff"
    assert captured["headers"] == {"Cookie": "wz_session=opaque-remote-session"}
    assert result == {"continue_url": "https://anyq.example/account/continue#ticket=one-time-ticket"}


def test_create_recharge_handoff_rejects_cross_origin_continue_url() -> None:
    def post(url: str, **kwargs: object) -> _Response:
        del url, kwargs
        return _Response({"ok": True, "continueUrl": "https://evil.example/account/continue#ticket=stolen"})

    with pytest.raises(account_client.AccountClientError, match="跳转地址"):
        account_client.create_recharge_handoff(
            {"cookie_name": "wz_session", "cookie_value": "opaque-remote-session"},
            server_url="https://anyq.example",
            post=post,
        )


def test_account_client_marks_authoritative_revocation_errors() -> None:
    response = _Response({"ok": False, "error": "产品权益已停用"}, status_code=403)

    with pytest.raises(account_client.AccountClientError) as caught:
        account_client._json_response(response)

    assert caught.value.status == 403
    assert caught.value.authoritative is True
