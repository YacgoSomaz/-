from __future__ import annotations

import base64

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
    assert "activation-1" in saved
    assert "https://license.example.com" in saved


def test_missing_commercial_feature_is_denied_when_enforcement_is_enabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "LICENSE_ENFORCE", True)
    monkeypatch.setattr(config, "LICENSE_PATH", tmp_path / "missing-license.json")

    try:
        license_manager.require_feature("ai_replay")
    except license_manager.LicenseFeatureError as exc:
        assert "未激活" in str(exc)
    else:
        raise AssertionError("未激活时必须阻止商业功能")

