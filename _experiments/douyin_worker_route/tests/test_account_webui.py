from __future__ import annotations

import json
import base64
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pipeline import account_client, account_manager, config, webui


def _signed_reply(monkeypatch, phone: str = "13800138000") -> dict[str, object]:
    private_key = Ed25519PrivateKey.generate()
    public_der = private_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(config, "ACCOUNT_PRODUCT_ID", "replay_shrimp", raising=False)
    monkeypatch.setattr(config, "ACCOUNT_LICENSE_PUBLIC_KEYS", {"account-test-v1": base64.urlsafe_b64encode(public_der).decode().rstrip("=")}, raising=False)
    now = int(time.time())
    payload = {
        "typ": "anyq.account-license.v1", "iss": "https://anyq.site", "aud": "replay_shrimp",
        "issued_at": now, "signed_until": now + 600, "server_time": "2026-07-14T00:00:00.000Z",
        "user": {"id": 7, "phone": phone, "role": "regular"},
        "products": [{"product_id": "replay_shrimp", "name": "复盘虾", "status": "active", "expires_at": "2027-07-21T00:00:00.000Z", "entitlements": ["livewatch"]}],
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "user": {"id": 7, "phone": phone, "role": "regular"},
        "products": payload["products"],
        "account_license": {"schema": "anyq.account-license.v1", "alg": "Ed25519", "key_id": "account-test-v1", "payload": base64.urlsafe_b64encode(raw).decode().rstrip("="), "signature": base64.urlsafe_b64encode(private_key.sign(raw)).decode().rstrip("=")},
        "remote_session": {"cookie_name": "wz_session", "cookie_value": "remote-token"},
    }


def test_account_login_api_saves_private_session_and_returns_public_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "ACCOUNT_SESSION_PATH", tmp_path / "account_session.json")
    monkeypatch.setattr(
        account_client,
        "login_with_sms",
        lambda phone, code: _signed_reply(monkeypatch, phone),
    )

    response = webui.api_account_login({"phone": "13800138000", "code": "123456"})
    payload = json.loads(response.body)

    assert payload["ok"] is True
    assert payload["account"]["logged_in"] is True
    assert payload["account"]["phone"] == "138****8000"
    assert payload["account"]["products"][0]["product_id"] == "replay_shrimp"
    assert "remote-token" not in response.body.decode("utf-8")
    assert account_manager.remote_session() == {"cookie_name": "wz_session", "cookie_value": "remote-token"}


def test_card_key_api_routes_are_not_exposed() -> None:
    paths = {route.path for route in webui.app.routes}

    assert not any(path.startswith("/api/license/") for path in paths)


def test_account_status_refreshes_the_signed_snapshot_without_exposing_session(monkeypatch) -> None:
    captured: dict[str, object] = {}
    session = {"cookie_name": "wz_session", "cookie_value": "remote-token"}

    monkeypatch.setattr(account_manager, "remote_session", lambda: session)
    monkeypatch.setattr(account_client, "refresh_account", lambda value: captured.setdefault("session", value) or {"account_license": {}})
    monkeypatch.setattr(account_manager, "refresh_login", lambda reply: captured.setdefault("reply", reply))
    monkeypatch.setattr(account_manager, "public_status", lambda: {"logged_in": True, "phone": "138****8000"})

    response = webui.api_account_status()
    payload = json.loads(response.body)

    assert captured["session"] == session
    assert "remote-token" not in response.body.decode("utf-8")
    assert payload["account"]["logged_in"] is True


def test_recharge_url_api_never_returns_remote_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "ACCOUNT_SESSION_PATH", tmp_path / "account_session.json")
    account_manager.save_login(_signed_reply(monkeypatch))
    captured: dict[str, object] = {}

    def create_handoff(session: dict[str, str]) -> dict[str, str]:
        captured["session"] = session
        return {"continue_url": "https://anyq.site/account/continue#ticket=one-time-ticket"}

    monkeypatch.setattr(account_client, "create_recharge_handoff", create_handoff)

    response = webui.api_account_recharge_url()
    payload = json.loads(response.body)

    assert payload == {"ok": True, "continue_url": "https://anyq.site/account/continue#ticket=one-time-ticket"}
    assert captured["session"] == {"cookie_name": "wz_session", "cookie_value": "remote-token"}
    assert "remote-token" not in response.body.decode("utf-8")
