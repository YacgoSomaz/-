from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_commercial_build_bundles_the_pinned_wss_sidecar_and_its_notice() -> None:
    script = (ROOT / "packaging" / "build" / "build_release.ps1").read_text(encoding="utf-8")

    assert "douyinLive-v2.0.24-79453ece4a44-windows-amd64.zip" in script
    assert 'Join-Path $AppDir "sidecar"' in script
    assert "THIRD_PARTY_NOTICES.md" in script


def test_launcher_defaults_to_sidecar_only_when_the_packaged_executable_exists() -> None:
    launcher = (ROOT / "packaging" / "build" / "livewatch_launcher.py").read_text(encoding="utf-8")

    assert 'app_dir / "sidecar" / "douyinLive.exe"' in launcher
    assert 'os.environ.setdefault("LIVEWATCH_DANMU_BACKEND", "sidecar")' in launcher


def test_commercial_build_keeps_the_sensitive_lexicons_as_runtime_data() -> None:
    script = (ROOT / "packaging" / "build" / "build_release.ps1").read_text(encoding="utf-8")

    assert 'Join-Path $PipelineData "lexicons"' in script
    assert '"sensitive_regex_seed.json"' in script
    assert '"yunyingxia_forbidden_words.v1.json"' in script
