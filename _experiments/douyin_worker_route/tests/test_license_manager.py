import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from pipeline import license_clock, license_manager


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _signed_doc(private_key, payload):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {"payload": _b64(raw), "signature": _b64(private_key.sign(raw)), "alg": "Ed25519", "key_id": "test"}


def _keypair():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private_key, _b64(public_key)


def test_valid_signed_license_enables_features():
    private_key, public_key = _keypair()
    device_hash = "device_hash_1"
    doc = _signed_doc(
        private_key,
        {
            "product_code": "live_replay_xia",
            "device_hash": device_hash,
            "features": ["export", "ai_replay"],
            "expires_at": 2000,
            "grace_until": 3000,
        },
    )

    status = license_manager.verify_license(
        doc,
        public_key=public_key,
        now=1000,
        expected_device_hash=device_hash,
        product_code="live_replay_xia",
    )

    assert status.ok is True
    assert status.mode == "licensed"
    assert {"basic", "export", "ai_replay"} <= status.features


def test_signed_license_policy_is_available_after_verification():
    private_key, public_key = _keypair()
    device_hash = "device_hash_1"
    doc = _signed_doc(
        private_key,
        {
            "product_code": "live_replay_xia",
            "device_hash": device_hash,
            "features": ["live_monitor"],
            "policy": {"max_active_rooms": 4, "export_watermark": False},
            "expires_at": 2000,
            "grace_until": 3000,
        },
    )

    status = license_manager.verify_license(
        doc,
        public_key=public_key,
        now=1000,
        expected_device_hash=device_hash,
        product_code="live_replay_xia",
    )

    assert status.ok is True
    assert license_manager.normalize_policy(status.payload.get("policy"))["max_active_rooms"] == 4
    assert license_manager.normalize_policy(status.payload.get("policy"))["export_watermark"] is False


def test_normalize_policy_sanitizes_disabled_features():
    policy = license_manager.normalize_policy(
        {
            "disabled_features": ["ai_replay", "basic", "bad_feature", "ai_replay", 123],
        }
    )

    assert policy["disabled_features"] == ["ai_replay"]


def test_signed_policy_can_disable_features_in_current_status(tmp_path, monkeypatch):
    private_key, public_key = _keypair()
    device_hash = "device_hash_1"
    license_path = tmp_path / "license.json"
    clock_path = tmp_path / "clock.json"
    monkeypatch.setattr(license_manager.config, "LICENSE_ENFORCE", True)
    monkeypatch.setattr(license_manager.config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(license_manager.config, "LICENSE_PATH", license_path)
    monkeypatch.setattr(license_manager.config, "LICENSE_CLOCK_PATH", clock_path, raising=False)
    monkeypatch.setattr(license_manager, "current_device_hash", lambda: device_hash)
    license_manager.save_license_doc(
        _signed_doc(
            private_key,
            {
                "product_code": "live_replay_xia",
                "device_hash": device_hash,
                "features": ["export", "ai_replay", "short_video_ai"],
                "policy": {"disabled_features": ["ai_replay", "bad_feature", "basic"]},
                "expires_at": 9_999_999_999,
                "grace_until": 10_000_000_000,
            },
        ),
        path=license_path,
    )

    status = license_manager.current_status(now=5_000)
    public = license_manager.public_status()

    assert status.ok is True
    assert "basic" in status.features
    assert "export" in status.features
    assert "short_video_ai" in status.features
    assert "ai_replay" not in status.features
    assert public["policy"]["disabled_features"] == ["ai_replay"]


def test_require_feature_rejects_policy_disabled_feature(tmp_path, monkeypatch):
    private_key, public_key = _keypair()
    device_hash = "device_hash_1"
    license_path = tmp_path / "license.json"
    clock_path = tmp_path / "clock.json"
    monkeypatch.setattr(license_manager.config, "LICENSE_ENFORCE", True)
    monkeypatch.setattr(license_manager.config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(license_manager.config, "LICENSE_PATH", license_path)
    monkeypatch.setattr(license_manager.config, "LICENSE_CLOCK_PATH", clock_path, raising=False)
    monkeypatch.setattr(license_manager, "current_device_hash", lambda: device_hash)
    license_manager.save_license_doc(
        _signed_doc(
            private_key,
            {
                "product_code": "live_replay_xia",
                "device_hash": device_hash,
                "features": ["short_video_ai"],
                "policy": {"disabled_features": ["short_video_ai"]},
                "expires_at": 9_999_999_999,
                "grace_until": 10_000_000_000,
            },
        ),
        path=license_path,
    )

    try:
        license_manager.require_feature("short_video_ai")
    except license_manager.LicenseFeatureError as exc:
        assert "当前功能已被管理员停用" in str(exc)
    else:
        raise AssertionError("policy-disabled feature should be rejected")


def test_tampered_payload_is_rejected():
    private_key, public_key = _keypair()
    doc = _signed_doc(
        private_key,
        {
            "product_code": "live_replay_xia",
            "device_hash": "device_hash_1",
            "features": ["basic"],
            "expires_at": 2000,
        },
    )
    payload = json.loads(base64.urlsafe_b64decode(doc["payload"] + "==").decode("utf-8"))
    payload["features"] = ["export", "batch"]
    doc["payload"] = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    status = license_manager.verify_license(
        doc,
        public_key=public_key,
        now=1000,
        expected_device_hash="device_hash_1",
        product_code="live_replay_xia",
    )

    assert status.ok is False
    assert status.mode == "invalid"
    assert status.features == {"basic"}


def test_tampered_policy_is_rejected():
    private_key, public_key = _keypair()
    doc = _signed_doc(
        private_key,
        {
            "product_code": "live_replay_xia",
            "device_hash": "device_hash_1",
            "features": ["live_monitor"],
            "policy": {"max_active_rooms": 3},
            "expires_at": 2000,
        },
    )
    payload = json.loads(base64.urlsafe_b64decode(doc["payload"] + "==").decode("utf-8"))
    payload["policy"] = {"max_active_rooms": 50}
    doc["payload"] = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    status = license_manager.verify_license(
        doc,
        public_key=public_key,
        now=1000,
        expected_device_hash="device_hash_1",
        product_code="live_replay_xia",
    )

    assert status.ok is False
    assert status.mode == "invalid"


def test_device_mismatch_is_rejected():
    private_key, public_key = _keypair()
    doc = _signed_doc(
        private_key,
        {
            "product_code": "live_replay_xia",
            "device_hash": "device_hash_1",
            "features": ["export"],
            "expires_at": 2000,
        },
    )

    status = license_manager.verify_license(
        doc,
        public_key=public_key,
        now=1000,
        expected_device_hash="device_hash_2",
        product_code="live_replay_xia",
    )

    assert status.ok is False
    assert status.reason == "授权不属于当前设备"


def test_expired_license_enters_grace_before_final_expiry():
    private_key, public_key = _keypair()
    doc = _signed_doc(
        private_key,
        {
            "product_code": "live_replay_xia",
            "device_hash": "device_hash_1",
            "features": ["export"],
            "expires_at": 2000,
            "grace_until": 3000,
        },
    )

    grace = license_manager.verify_license(
        doc,
        public_key=public_key,
        now=2500,
        expected_device_hash="device_hash_1",
        product_code="live_replay_xia",
    )
    expired = license_manager.verify_license(
        doc,
        public_key=public_key,
        now=3001,
        expected_device_hash="device_hash_1",
        product_code="live_replay_xia",
    )

    assert grace.ok is True
    assert grace.mode == "grace"
    assert "export" in grace.features
    assert expired.ok is False
    assert expired.mode == "expired"
    assert expired.features == {"basic"}


def test_install_license_rejects_bad_doc_without_overwriting(tmp_path, monkeypatch):
    private_key, public_key = _keypair()
    monkeypatch.setattr(license_manager.config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(license_manager, "current_device_hash", lambda *args, **kwargs: "device_hash_1")
    path = tmp_path / "license.json"
    valid_doc = _signed_doc(
        private_key,
        {
            "product_code": "live_replay_xia",
            "device_hash": "device_hash_1",
            "features": ["export"],
            "expires_at": 9_999_999_999,
        },
    )
    valid = license_manager.install_license_doc(valid_doc, path=path)
    original = path.read_text(encoding="utf-8")

    bad_doc = dict(valid_doc)
    bad_doc["payload"] = _b64(
        json.dumps(
            {
                "product_code": "live_replay_xia",
                "device_hash": "device_hash_2",
                "features": ["export", "batch"],
                "expires_at": 9_999_999_999,
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    rejected = license_manager.install_license_doc(bad_doc, path=path)

    assert valid.ok is True
    assert rejected.ok is False
    assert path.read_text(encoding="utf-8") == original


def test_commercial_status_rejects_large_local_clock_rollback(tmp_path, monkeypatch):
    private_key, public_key = _keypair()
    device_hash = "device_hash_1"
    license_path = tmp_path / "license.json"
    clock_path = tmp_path / "clock.json"
    monkeypatch.setattr(license_manager.config, "LICENSE_ENFORCE", True)
    monkeypatch.setattr(license_manager.config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(license_manager.config, "LICENSE_PATH", license_path)
    monkeypatch.setattr(license_manager.config, "LICENSE_CLOCK_PATH", clock_path, raising=False)
    monkeypatch.setattr(license_manager, "current_device_hash", lambda: device_hash)
    license_manager.save_license_doc(
        _signed_doc(
            private_key,
            {
                "product_code": "live_replay_xia",
                "device_hash": device_hash,
                "features": ["export"],
                "expires_at": 9_999,
                "grace_until": 10_000,
            },
        ),
        path=license_path,
    )
    assert license_clock.check_and_record(now=5_000, path=clock_path).ok is True

    status = license_manager.current_status(now=4_000)

    assert status.ok is False
    assert status.mode == "clock_error"


def test_commercial_status_can_force_upgrade_by_signed_policy(tmp_path, monkeypatch):
    private_key, public_key = _keypair()
    device_hash = "device_hash_1"
    license_path = tmp_path / "license.json"
    clock_path = tmp_path / "clock.json"
    monkeypatch.setattr(license_manager.config, "LICENSE_ENFORCE", True)
    monkeypatch.setattr(license_manager.config, "LICENSE_PUBLIC_KEY", public_key)
    monkeypatch.setattr(license_manager.config, "LICENSE_PATH", license_path)
    monkeypatch.setattr(license_manager.config, "LICENSE_CLOCK_PATH", clock_path, raising=False)
    monkeypatch.setattr(license_manager.config, "LICENSE_APP_VERSION", "1.0.0")
    monkeypatch.setattr(license_manager, "current_device_hash", lambda: device_hash)
    license_manager.save_license_doc(
        _signed_doc(
            private_key,
            {
                "product_code": "live_replay_xia",
                "device_hash": device_hash,
                "features": ["live_monitor"],
                "policy": {"force_upgrade_below": "1.1.0"},
                "expires_at": 9_999,
                "grace_until": 10_000,
            },
        ),
        path=license_path,
    )

    status = license_manager.current_status(now=5_000)

    assert status.ok is False
    assert status.mode == "upgrade_required"
