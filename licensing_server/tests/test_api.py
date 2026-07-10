from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from licensing_server.app import create_app
from licensing_server.rate_limit import IpRateLimiter, RateLimitPolicy
from licensing_server.service import LicenseService, LicenseSettings


def _service(tmp_path: Path) -> LicenseService:
    private_key = Ed25519PrivateKey.generate()
    private_b64 = base64.urlsafe_b64encode(private_key.private_bytes_raw()).decode("ascii").rstrip("=")
    return LicenseService(
        LicenseSettings(
            db_path=tmp_path / "licenses.db",
            signing_private_key=private_b64,
            token_hash_secret="test-only-token-secret",
        )
    )


def test_activation_api_and_freeze_protect_refresh(tmp_path: Path) -> None:
    service = _service(tmp_path)
    card_key = service.create_card_key(features={"basic", "export"})
    client = TestClient(create_app(service, admin_token="admin-test-token"))

    root = client.get("/", follow_redirects=False)
    assert root.status_code == 302
    assert root.headers["location"] == "/admin"

    console = client.get("/admin")
    assert console.status_code == 200
    assert "授权管理台" in console.text

    cards = client.get("/admin/cards", headers={"Authorization": "Bearer admin-test-token"})
    assert cards.status_code == 200
    assert cards.json()["cards"][0]["key_prefix"] == card_key[:8]

    activation = client.post(
        "/v1/activate",
        json={"card_key": card_key, "device_hash": "device-a", "app_version": "1.0.0"},
    )
    assert activation.status_code == 200
    body = activation.json()

    activations = client.get(
        "/admin/activations",
        headers={"Authorization": "Bearer admin-test-token"},
    )
    assert activations.status_code == 200
    assert activations.json()["activations"][0]["id"] == body["activation_id"]
    assert activations.json()["activations"][0]["status"] == "active"

    unauthorized = client.post(f"/admin/activations/{body['activation_id']}/freeze", json={"reason": "refund"})
    assert unauthorized.status_code == 401

    frozen = client.post(
        f"/admin/activations/{body['activation_id']}/freeze",
        headers={"Authorization": "Bearer admin-test-token"},
        json={"reason": "refund"},
    )
    assert frozen.status_code == 200

    refreshed = client.post(
        "/v1/refresh",
        json={
            "activation_id": body["activation_id"],
            "refresh_token": body["refresh_token"],
            "device_hash": "device-a",
            "app_version": "1.0.1",
        },
    )
    assert refreshed.status_code == 403
    assert refreshed.json()["detail"] == "当前设备授权已冻结"


def test_public_activation_endpoint_is_rate_limited(tmp_path: Path) -> None:
    service = _service(tmp_path)
    client = TestClient(
        create_app(
            service,
            admin_token="admin-test-token",
            rate_limiter=IpRateLimiter(RateLimitPolicy(window_seconds=60, activate_attempts=1, refresh_attempts=5)),
        )
    )

    first = client.post("/v1/activate", json={"card_key": "LRX-INVALID", "device_hash": "device-a"})
    second = client.post("/v1/activate", json={"card_key": "LRX-INVALID", "device_hash": "device-a"})

    assert first.status_code == 400
    assert second.status_code == 429
    assert second.headers["retry-after"].isdigit()
