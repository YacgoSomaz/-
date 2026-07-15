import importlib

from pipeline import config, license_runtime


def test_config_uses_the_build_time_runtime_version_when_env_is_absent(monkeypatch) -> None:
    original = license_runtime.LICENSE_APP_VERSION
    monkeypatch.delenv("LIVEWATCH_APP_VERSION", raising=False)
    monkeypatch.setattr(license_runtime, "LICENSE_APP_VERSION", "1.2.34")
    try:
        reloaded = importlib.reload(config)
        assert reloaded.LICENSE_APP_VERSION == "1.2.34"
    finally:
        monkeypatch.setattr(license_runtime, "LICENSE_APP_VERSION", original)
        importlib.reload(config)
