from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from pipeline import config, license_client, license_manager


class _Response:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = "request failed"

    def json(self) -> dict[str, object]:
        return self._payload


def _signed_package(device_hash: str) -> tuple[dict[str, object], str]:
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.urlsafe_b64encode(
        private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode("ascii").rstrip("=")
    payload = {
        "product_code": config.LICENSE_PRODUCT_CODE,
        "device_hash": device_hash,
        "features": ["basic", "export"],
        "issued_at": 1_700_000_000,
        "expires_at": 4_000_000_000,
        "grace_until": 4_000_086_400,
    }
    import json

    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return (
        {
            "license": {
                "alg": "Ed25519",
                "payload": base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="),
                "signature": base64.urlsafe_b64encode(private_key.sign(raw)).decode("ascii").rstrip("="),
            },
            "activation_id": "activation-1",
            "refresh_token": "x" * 40,
        },
        public_key,
    )


def test_activate_card_key_persists_verified_server_package(tmp_path, monkeypatch) -> None:
    device_hash = "device-a"
    server_reply, public_key = _signed_package(device_hash)
    monkeypatch.setattr(config, "LICENSE_PATH", tmp_path / "license.json")
    monkeypatch.setattr(config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(license_manager, "current_device_hash", lambda: device_hash)

    result = license_client.activate_card_key(
        "LRX-ABCDE-ABCDE-ABCDE-ABCDE",
        server_url="https://license.example.com",
        post=lambda *_args, **_kwargs: _Response(server_reply),
    )

    assert result["ok"] is True
    assert config.LICENSE_PATH.exists()
    saved = config.LICENSE_PATH.read_text(encoding="utf-8")
    assert "activation-1" not in saved
    assert "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" not in saved
    assert "https://license.example.com" not in saved
    assert license_client._load_package()["activation_id"] == "activation-1"
    assert license_client._load_package()["refresh_token"] == "x" * 40


def test_activate_card_key_sends_hmac_replay_protection_headers(tmp_path, monkeypatch) -> None:
    device_hash = "device-a"
    server_reply, public_key = _signed_package(device_hash)
    monkeypatch.setattr(config, "LICENSE_PATH", tmp_path / "license.json")
    monkeypatch.setattr(config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(config, "LICENSE_APP_VERSION", "1.2.3")
    monkeypatch.setattr(license_manager, "current_device_hash", lambda: device_hash)
    monkeypatch.setattr(license_client.time, "time", lambda: 1_700_000_000)
    monkeypatch.setattr(license_client.uuid, "uuid4", lambda: "nonce-1")
    captured: dict[str, object] = {}

    def post(url: str, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["headers"] = kwargs["headers"]
        return _Response(server_reply)

    license_client.activate_card_key(
        "LRX-ABCDE-ABCDE-ABCDE-ABCDE",
        server_url="https://license.example.com",
        post=post,
    )

    headers = captured["headers"]
    assert headers["X-LiveWatch-Timestamp"] == "1700000000"
    assert headers["X-LiveWatch-Nonce"] == "nonce-1"
    assert headers["X-LiveWatch-Device"] == device_hash
    assert headers["X-LiveWatch-App-Version"] == "1.2.3"
    assert headers["X-LiveWatch-Signature"]
    assert "LRX-ABCDE" not in json.dumps(headers)
    assert captured["json"]["product_code"] == config.LICENSE_PRODUCT_CODE


def test_refresh_license_reads_protected_package_without_leaking_token(tmp_path, monkeypatch) -> None:
    device_hash = "device-a"
    server_reply, public_key = _signed_package(device_hash)
    monkeypatch.setattr(config, "LICENSE_PATH", tmp_path / "license.json")
    monkeypatch.setattr(config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(license_manager, "current_device_hash", lambda: device_hash)
    license_client.activate_card_key(
        "LRX-ABCDE-ABCDE-ABCDE-ABCDE",
        server_url="https://license.example.com",
        post=lambda *_args, **_kwargs: _Response(server_reply),
    )

    posted: list[dict[str, str]] = []

    def post(_url: str, **kwargs):
        posted.append(kwargs["json"])
        return _Response(server_reply)

    refreshed = license_client.refresh_license(post=post)

    assert refreshed["ok"] is True
    assert posted[0]["activation_id"] == "activation-1"
    assert posted[0]["refresh_token"] == "x" * 40
    saved = config.LICENSE_PATH.read_text(encoding="utf-8")
    assert "activation-1" not in saved
    assert "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" not in saved


def test_refresh_license_signs_request_with_refresh_token(tmp_path, monkeypatch) -> None:
    device_hash = "device-a"
    server_reply, public_key = _signed_package(device_hash)
    monkeypatch.setattr(config, "LICENSE_PATH", tmp_path / "license.json")
    monkeypatch.setattr(config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(license_manager, "current_device_hash", lambda: device_hash)
    license_client.activate_card_key(
        "LRX-ABCDE-ABCDE-ABCDE-ABCDE",
        server_url="https://license.example.com",
        post=lambda *_args, **_kwargs: _Response(server_reply),
    )
    monkeypatch.setattr(license_client.time, "time", lambda: 1_700_000_100)
    monkeypatch.setattr(license_client.uuid, "uuid4", lambda: "nonce-2")
    captured: dict[str, object] = {}

    def post(url: str, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["headers"] = kwargs["headers"]
        return _Response(server_reply)

    license_client.refresh_license(post=post)

    headers = captured["headers"]
    assert headers["X-LiveWatch-Timestamp"] == "1700000100"
    assert headers["X-LiveWatch-Nonce"] == "nonce-2"
    assert headers["X-LiveWatch-Device"] == device_hash
    assert headers["X-LiveWatch-Signature"]
    assert "xxxxxxxx" not in json.dumps(headers)
    assert captured["json"]["product_code"] == config.LICENSE_PRODUCT_CODE


def test_refresh_license_clears_local_cache_on_server_denial(tmp_path, monkeypatch) -> None:
    device_hash = "device-a"
    server_reply, public_key = _signed_package(device_hash)
    monkeypatch.setattr(config, "LICENSE_PATH", tmp_path / "license.json")
    monkeypatch.setattr(config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(license_manager, "current_device_hash", lambda: device_hash)
    license_client.activate_card_key(
        "LRX-ABCDE-ABCDE-ABCDE-ABCDE",
        server_url="https://license.example.com",
        post=lambda *_args, **_kwargs: _Response(server_reply),
    )
    assert config.LICENSE_PATH.exists()

    def deny(_url: str, **_kwargs):
        return _Response({"detail": "卡密已到期"}, status_code=403)

    try:
        license_client.refresh_license(post=deny)
    except license_client.LicenseServerDenial as exc:
        assert "卡密已到期" in str(exc)
    else:
        raise AssertionError("服务器拒绝时必须抛出 LicenseServerDenial")

    assert not config.LICENSE_PATH.exists()


def test_refresh_license_keeps_local_cache_on_server_error(tmp_path, monkeypatch) -> None:
    device_hash = "device-a"
    server_reply, public_key = _signed_package(device_hash)
    monkeypatch.setattr(config, "LICENSE_PATH", tmp_path / "license.json")
    monkeypatch.setattr(config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(license_manager, "current_device_hash", lambda: device_hash)
    license_client.activate_card_key(
        "LRX-ABCDE-ABCDE-ABCDE-ABCDE",
        server_url="https://license.example.com",
        post=lambda *_args, **_kwargs: _Response(server_reply),
    )
    assert config.LICENSE_PATH.exists()

    def fail(_url: str, **_kwargs):
        return _Response({"detail": "授权服务器暂时不可用"}, status_code=500)

    try:
        license_client.refresh_license(post=fail)
    except license_client.LicenseClientError as exc:
        assert "授权服务器暂时不可用" in str(exc)
    else:
        raise AssertionError("服务器错误时必须抛出 LicenseClientError")

    assert config.LICENSE_PATH.exists()


def test_legacy_plain_license_is_migrated_to_protected_cache(tmp_path, monkeypatch) -> None:
    device_hash = "device-a"
    server_reply, public_key = _signed_package(device_hash)
    monkeypatch.setattr(config, "LICENSE_PATH", tmp_path / "license.json")
    monkeypatch.setattr(config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(license_manager, "current_device_hash", lambda: device_hash)
    legacy = dict(server_reply["license"])
    legacy.update(
        {
            "activation_id": "activation-1",
            "refresh_token": "x" * 40,
            "server_url": "https://license.example.com",
        }
    )
    config.LICENSE_PATH.write_text(json.dumps(legacy), encoding="utf-8")

    package = license_client._load_package()

    assert package["activation_id"] == "activation-1"
    saved = config.LICENSE_PATH.read_text(encoding="utf-8")
    assert "activation-1" not in saved
    assert "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" not in saved


def test_missing_commercial_feature_is_denied_when_enforcement_is_enabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "LICENSE_ENFORCE", True)
    monkeypatch.setattr(config, "LICENSE_PATH", tmp_path / "missing-license.json")

    try:
        license_manager.require_feature("ai_replay")
    except license_manager.LicenseFeatureError as exc:
        assert "未激活" in str(exc)
    else:
        raise AssertionError("未激活时必须阻止商业功能")
