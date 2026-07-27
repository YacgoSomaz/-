from pathlib import Path


def test_account_entitlement_refresh_defaults_to_ten_seconds() -> None:
    """A revoked product must be noticed promptly during a running session."""
    config = (Path(__file__).resolve().parents[1] / "pipeline" / "config.py").read_text(encoding="utf-8")

    assert 'ACCOUNT_REFRESH_INTERVAL_SEC = max(10, int(os.environ.get("LIVEWATCH_ACCOUNT_REFRESH_INTERVAL_SEC", "10")))' in config
