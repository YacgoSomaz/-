from pathlib import Path


def test_release_build_supports_optional_authenticode_signing():
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "packaging" / "build" / "build_release.ps1").read_text(encoding="utf-8")

    assert "CodeSignThumbprint" in script
    assert "Sign-ReleaseBinary" in script
    assert "Get-AuthenticodeSignature" in script
    assert "LiveWatchLauncher.exe" in script
    assert "LiveWatchSetup*.exe" in script
