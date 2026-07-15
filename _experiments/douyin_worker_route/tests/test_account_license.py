from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pipeline import account_license, config


NOW = 1_783_987_200


def test_replay_client_uses_the_current_account_v1_public_key() -> None:
    # SPKI DER form of the public key derived from the production account-v1
    # signing key.  It must match the server key, while the private key stays
    # on the server.
    assert config.ACCOUNT_LICENSE_PUBLIC_KEYS["account-v1"] == "MCowBQYDK2VwAyEACqLAEE2KnduTFtw1gVQIExS1qLRa-XI3TaWpbchMbKc"


def _key_material() -> tuple[Ed25519PrivateKey, dict[str, str]]:
    private_key = Ed25519PrivateKey.generate()
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, {"account-test-v1": base64.urlsafe_b64encode(public_der).decode().rstrip("=")}


def _reply(private_key: Ed25519PrivateKey, **changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "typ": "anyq.account-license.v1",
        "iss": "https://anyq.site",
        "aud": "replay_shrimp",
        "issued_at": NOW,
        "signed_until": NOW + 600,
        "server_time": "2026-07-14T00:00:00.000Z",
        "user": {"id": 7, "phone": "13800138000", "role": "regular"},
        "products": [
            {
                "product_id": "replay_shrimp",
                "name": "复盘虾 + 运营杀招教程",
                "status": "active",
                "expires_at": "2027-07-14T00:00:00.000Z",
                "entitlements": ["livewatch"],
            }
        ],
    }
    payload.update(changes)
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "ok": True,
        "account_license": {
            "schema": "anyq.account-license.v1",
            "alg": "Ed25519",
            "key_id": "account-test-v1",
            "payload": base64.urlsafe_b64encode(payload_bytes).decode().rstrip("="),
            "signature": base64.urlsafe_b64encode(private_key.sign(payload_bytes)).decode().rstrip("="),
        },
    }


def test_signed_replay_license_is_the_only_source_of_products() -> None:
    private_key, keys = _key_material()
    reply = _reply(private_key)
    reply["products"] = [{"product_id": "operation_shrimp", "status": "active", "entitlements": ["operation_course"]}]

    verified = account_license.verify_account_license(
        reply,
        expected_audience="replay_shrimp",
        public_keys=keys,
        now=NOW + 1,
    )

    assert verified["products"][0]["product_id"] == "replay_shrimp"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"issued_at": NOW - 600, "signed_until": NOW - 1}, "过期"),
        ({"aud": "comic_shrimp"}, "受众"),
    ],
)
def test_replay_license_rejects_expired_or_wrong_audience(changes: dict[str, object], message: str) -> None:
    private_key, keys = _key_material()

    with pytest.raises(account_license.AccountLicenseError, match=message):
        account_license.verify_account_license(
            _reply(private_key, **changes),
            expected_audience="replay_shrimp",
            public_keys=keys,
            now=NOW,
        )


def test_replay_license_rejects_tampered_payload_and_unknown_key() -> None:
    private_key, keys = _key_material()
    reply = _reply(private_key)
    envelope = reply["account_license"]
    assert isinstance(envelope, dict)
    tampered = json.loads(base64.urlsafe_b64decode(str(envelope["payload"]) + "==").decode())
    tampered["products"][0]["entitlements"] = ["livewatch", "admin"]
    envelope["payload"] = base64.urlsafe_b64encode(json.dumps(tampered, separators=(",", ":")).encode()).decode().rstrip("=")

    with pytest.raises(account_license.AccountLicenseError, match="签名"):
        account_license.verify_account_license(reply, expected_audience="replay_shrimp", public_keys=keys, now=NOW)

    reply = _reply(private_key)
    reply["account_license"]["key_id"] = "unknown-key"  # type: ignore[index]
    with pytest.raises(account_license.AccountLicenseError, match="密钥"):
        account_license.verify_account_license(reply, expected_audience="replay_shrimp", public_keys=keys, now=NOW)
