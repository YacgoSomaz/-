from pipeline import config, license_refresh


def test_license_refresh_default_interval_is_ten_minutes() -> None:
    assert config.LICENSE_REFRESH_INTERVAL_SEC == 600


def test_refresh_loop_skips_development_builds(monkeypatch) -> None:
    monkeypatch.setattr(config, "LICENSE_ENFORCE", False)

    assert license_refresh.refresh_once() == "skipped"


def test_refresh_loop_reports_server_denial_without_crashing(monkeypatch) -> None:
    monkeypatch.setattr(config, "LICENSE_ENFORCE", True)
    monkeypatch.setattr(license_refresh.license_client, "refresh_license", lambda: (_ for _ in ()).throw(license_refresh.license_client.LicenseServerDenial("当前设备授权已冻结")))

    assert license_refresh.refresh_once() == "revoked: 当前设备授权已冻结"
