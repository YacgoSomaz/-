from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pipeline import account_license, account_manager, config, license_manager


def _signed_reply(monkeypatch, products: list[dict[str, object]]) -> dict[str, object]:
    private_key = Ed25519PrivateKey.generate()
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    monkeypatch.setattr(config, "ACCOUNT_PRODUCT_ID", "replay_shrimp", raising=False)
    monkeypatch.setattr(
        config,
        "ACCOUNT_LICENSE_PUBLIC_KEYS",
        {"account-test-v1": base64.urlsafe_b64encode(public_der).decode().rstrip("=")},
        raising=False,
    )
    now = int(time.time())
    payload = {
        "typ": "anyq.account-license.v1",
        "iss": "https://anyq.site",
        "aud": "replay_shrimp",
        "issued_at": now,
        "signed_until": now + 600,
        "server_time": "2026-07-14T00:00:00.000Z",
        "user": {"id": 7, "phone": "13800138000", "role": "regular"},
        "products": products,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        # These deliberately tempting unsigned fields must never control access.
        "user": {"id": 999, "phone": "13999999999", "role": "admin", "entitlements": ["live_monitor"]},
        "products": [{"product_id": "operation_shrimp", "status": "active", "entitlements": ["operation_course"]}],
        "account_license": {
            "schema": "anyq.account-license.v1",
            "alg": "Ed25519",
            "key_id": "account-test-v1",
            "payload": base64.urlsafe_b64encode(raw).decode().rstrip("="),
            "signature": base64.urlsafe_b64encode(private_key.sign(raw)).decode().rstrip("="),
        },
        "remote_session": {"cookie_name": "wz_session", "cookie_value": "opaque-remote-token"},
    }


def test_account_session_is_protected_and_only_signed_replay_product_grants_features(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "ACCOUNT_SESSION_PATH", tmp_path / "account_session.json")
    account_manager.save_login(
        _signed_reply(
            monkeypatch,
            [
                {
                    "product_id": "replay_shrimp",
                    "name": "复盘虾 + 运营杀招教程",
                    "status": "active",
                    "expires_at": "2027-07-21T00:00:00.000Z",
                    "entitlements": ["livewatch"],
                },
                {
                    "product_id": "comic_shrimp",
                    "name": "漫剧虾 + 漫剧精品课程",
                    "status": "active",
                    "expires_at": "2027-07-21T00:00:00.000Z",
                    "entitlements": ["comic_course"],
                },
            ],
        )
    )

    raw = config.ACCOUNT_SESSION_PATH.read_text(encoding="utf-8")
    assert "opaque-remote-token" not in raw
    status = account_manager.public_status()
    assert status["phone"] == "138****8000"
    assert status["role"] == "regular"
    assert status["products"][0]["product_id"] == "replay_shrimp"
    account_manager.require_feature("live_monitor")
    with pytest.raises(account_manager.AccountFeatureError, match="尚未开通"):
        account_manager.require_feature("not_a_livewatch_feature")


def test_account_manager_rejects_unsigned_or_tampered_product_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "ACCOUNT_SESSION_PATH", tmp_path / "account_session.json")
    forged = {
        "user": {"id": 7, "phone": "13800138000", "role": "admin", "entitlements": ["live_monitor"]},
        "products": [{"product_id": "replay_shrimp", "status": "active", "entitlements": ["livewatch"]}],
        "remote_session": {"cookie_name": "wz_session", "cookie_value": "opaque-remote-token"},
    }

    with pytest.raises(account_license.AccountLicenseError, match="未返回权益签名"):
        account_manager.save_login(forged)


def test_other_product_does_not_unlock_replay_client(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "ACCOUNT_SESSION_PATH", tmp_path / "account_session.json")
    account_manager.save_login(
        _signed_reply(
            monkeypatch,
            [{"product_id": "comic_shrimp", "name": "漫剧虾", "status": "active", "expires_at": "2027-07-21T00:00:00.000Z", "entitlements": ["comic_course"]}],
        )
    )

    with pytest.raises(account_manager.AccountFeatureError, match="复盘虾会员权益"):
        account_manager.require_feature("live_monitor")


def test_legacy_encrypted_session_is_refreshed_but_never_trusted_for_access(tmp_path, monkeypatch) -> None:
    path = tmp_path / "account_session.json"
    monkeypatch.setattr(config, "ACCOUNT_SESSION_PATH", path)
    raw = json.dumps({"remote_session": {"cookie_name": "wz_session", "cookie_value": "legacy-opaque-token"}}).encode()
    legacy = {"storage": "livewatch-account-session-v1", "protected": True, "version": 1, **license_manager._protect_license_bytes(raw)}
    path.write_text(json.dumps(legacy), encoding="utf-8")

    assert account_manager.remote_session() == {"cookie_name": "wz_session", "cookie_value": "legacy-opaque-token"}
    assert account_manager.public_status()["logged_in"] is False
