from pipeline import config, license_manager


def test_license_status_defaults_to_development_mode(monkeypatch):
    monkeypatch.setattr(config, "LICENSE_ENFORCE", False)

    status = license_manager.public_status()

    assert status["mode"] == "development"
    assert status["enforced"] is False
    assert "ai_replay" in status["features"]
    assert len(license_manager.current_device_hash()[:12]) == 12
