import pathlib


ROOT = pathlib.Path(__file__).parent
LAUNCHER = (ROOT / "livewatch_launcher.py").read_text(encoding="utf-8-sig")
SMOKE = (ROOT / "smoke_test.ps1").read_text(encoding="utf-8-sig")


def test_frozen_launcher_smoke_test_isolates_local_app_data() -> None:
    assert 'override = None if _is_frozen() else os.environ.get("LIVEWATCH_DATA_DIR")' in LAUNCHER
    assert "$originalLocalAppData" in SMOKE
    assert "$isolatedLocalAppData" in SMOKE
    assert '$env:LOCALAPPDATA = $isolatedLocalAppData' in SMOKE
    assert '$data = Join-Path $isolatedLocalAppData "LiveWatch\\data"' in SMOKE
    assert '$env:LOCALAPPDATA = $originalLocalAppData' in SMOKE
