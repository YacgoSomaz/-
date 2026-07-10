from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from pipeline.license_manager import verify_license

from licensing_server.service import LicenseError, LicenseService, LicenseSettings


def _settings(tmp_path: Path) -> tuple[LicenseSettings, str]:
    private_key = Ed25519PrivateKey.generate()
    private_b64 = base64.urlsafe_b64encode(private_key.private_bytes_raw()).decode("ascii").rstrip("=")
    public_b64 = base64.urlsafe_b64encode(
        private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode("ascii").rstrip("=")
    return (
        LicenseSettings(
            db_path=tmp_path / "licenses.db",
            signing_private_key=private_b64,
            token_hash_secret="test-only-token-secret",
            product_code="live_replay_xia",
            license_days=3,
            grace_days=1,
        ),
        public_b64,
    )


def test_activation_returns_a_license_verified_by_the_desktop_client(tmp_path: Path) -> None:
    settings, public_key = _settings(tmp_path)
    service = LicenseService(settings)
    card_key = service.create_card_key(features={"basic", "export"}, max_devices=1)

    activated = service.activate(card_key=card_key, device_hash="device-a", app_version="1.0.0", now=1_700_000_000)

    status = verify_license(
        activated["license"],
        public_key=public_key,
        expected_device_hash="device-a",
        now=1_700_000_001,
    )
    assert status.ok is True
    assert status.features == {"basic", "export"}
    assert activated["activation_id"]
    assert activated["refresh_token"]


def test_second_device_is_rejected_when_card_device_limit_is_reached(tmp_path: Path) -> None:
    settings, _ = _settings(tmp_path)
    service = LicenseService(settings)
    card_key = service.create_card_key(features={"basic"}, max_devices=1)
    service.activate(card_key=card_key, device_hash="device-a", app_version="1.0.0", now=1_700_000_000)

    with pytest.raises(LicenseError, match="设备数"):
        service.activate(card_key=card_key, device_hash="device-b", app_version="1.0.0", now=1_700_000_001)


def test_frozen_activation_cannot_refresh_but_unbound_device_can_be_replaced(tmp_path: Path) -> None:
    settings, _ = _settings(tmp_path)
    service = LicenseService(settings)
    card_key = service.create_card_key(features={"basic", "ai_replay"}, max_devices=1)
    activated = service.activate(card_key=card_key, device_hash="device-a", app_version="1.0.0", now=1_700_000_000)

    service.freeze_activation(activated["activation_id"], reason="refund")
    with pytest.raises(LicenseError, match="冻结"):
        service.refresh(
            activation_id=activated["activation_id"],
            refresh_token=activated["refresh_token"],
            device_hash="device-a",
            app_version="1.0.1",
            now=1_700_000_100,
        )

    service.unbind_activation(activated["activation_id"], reason="device replaced")
    replacement = service.activate(card_key=card_key, device_hash="device-b", app_version="1.0.1", now=1_700_000_200)
    assert replacement["activation_id"] != activated["activation_id"]

