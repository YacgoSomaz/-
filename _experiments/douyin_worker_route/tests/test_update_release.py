from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pipeline import update_release


NOW = 1_784_068_800


def _keys() -> tuple[Ed25519PrivateKey, dict[str, str]]:
    private_key = Ed25519PrivateKey.generate()
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, {"update-test-v1": base64.urlsafe_b64encode(public_der).decode().rstrip("=")}


def _envelope(private_key: Ed25519PrivateKey, **changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "typ": "desktop-release",
        "iss": "https://anyq.site",
        "aud": "replay_shrimp",
        "issued_at": NOW,
        "signed_until": NOW + 3600,
        "product_id": "replay_shrimp",
        "version": "1.0.13",
        "min_supported_version": "1.0.12",
        "mandatory": False,
        "installer_url": "https://download.anyq.site/replay-shrimp/1.0.13/ReplayShrimpSetup_1.0.13.exe",
        "sha256": "a" * 64,
        "size_bytes": 314_182_000,
        "notes": "修复更新安装与登录体验。",
        "published_at": "2026-07-14T12:00:00.000Z",
    }
    payload.update(changes)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "schema": "anyq.desktop-update.v1",
        "alg": "Ed25519",
        "key_id": "update-test-v1",
        "payload": base64.urlsafe_b64encode(raw).decode().rstrip("="),
        "signature": base64.urlsafe_b64encode(private_key.sign(raw)).decode().rstrip("="),
    }


def test_update_release_accepts_only_a_valid_signed_release_for_this_product() -> None:
    private_key, public_keys = _keys()

    release = update_release.verify_update_release(
        {"update_release": _envelope(private_key)},
        expected_audience="replay_shrimp",
        public_keys=public_keys,
        now=NOW + 1,
    )

    assert release["version"] == "1.0.13"
    assert release["mandatory"] is False
    assert release["installer_url"].startswith("https://download.anyq.site/")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"aud": "comic_shrimp", "product_id": "comic_shrimp"}, "受众"),
        ({"installer_url": "https://example.test/installer.exe"}, "下载地址"),
        ({"issued_at": NOW - 3_600, "signed_until": NOW - 1}, "过期"),
    ],
)
def test_update_release_rejects_wrong_product_unsafe_host_or_expiry(changes: dict[str, object], message: str) -> None:
    private_key, public_keys = _keys()

    with pytest.raises(update_release.UpdateReleaseError, match=message):
        update_release.verify_update_release(
            {"update_release": _envelope(private_key, **changes)},
            expected_audience="replay_shrimp",
            public_keys=public_keys,
            now=NOW,
        )


def test_update_release_rejects_tampering_and_duplicate_json_keys() -> None:
    private_key, public_keys = _keys()
    reply = {"update_release": _envelope(private_key)}
    envelope = reply["update_release"]
    assert isinstance(envelope, dict)
    payload = json.loads(base64.urlsafe_b64decode(str(envelope["payload"]) + "==").decode())
    payload["mandatory"] = True
    envelope["payload"] = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    with pytest.raises(update_release.UpdateReleaseError, match="签名"):
        update_release.verify_update_release(reply, expected_audience="replay_shrimp", public_keys=public_keys, now=NOW)

    duplicate = b'{"typ":"desktop-release","typ":"other","iss":"https://anyq.site"}'
    envelope = _envelope(private_key)
    envelope["payload"] = base64.urlsafe_b64encode(duplicate).decode().rstrip("=")
    envelope["signature"] = base64.urlsafe_b64encode(private_key.sign(duplicate)).decode().rstrip("=")
    with pytest.raises(update_release.UpdateReleaseError, match="重复字段"):
        update_release.verify_update_release({"update_release": envelope}, expected_audience="replay_shrimp", public_keys=public_keys, now=NOW)
