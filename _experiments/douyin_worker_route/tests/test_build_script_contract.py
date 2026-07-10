from pathlib import Path


def test_release_build_supports_optional_authenticode_signing():
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "packaging" / "build" / "build_release.ps1").read_text(encoding="utf-8")

    assert "CodeSignThumbprint" in script
    assert "Sign-ReleaseBinary" in script
    assert "Get-AuthenticodeSignature" in script
    assert "LiveWatchLauncher.exe" in script
    assert "LiveWatchSetup*.exe" in script


def test_commercial_wrapper_delegates_to_hardened_release_build_without_secrets():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "packaging" / "build" / "build_commercial_release.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert script_path.exists()
    assert "build_release.ps1" in script
    assert "-Commercial" in script
    assert "LIVEWATCH_LICENSE_PUBLIC_KEY" in script
    assert "LIVEWATCH_LICENSE_ADMIN_TOKEN" in script
    assert "/admin/public-key" in script
    assert "Authorization" in script
    assert "Bearer $token" in script
    assert "No admin token or private key will be written into the installer" in script
    assert "sk-" not in script
    assert "AIshixun" not in script


def test_release_build_generates_integrity_manifest_before_scanning():
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "packaging" / "build" / "build_release.ps1").read_text(encoding="utf-8")
    launcher = (repo_root / "packaging" / "build" / "livewatch_launcher.py").read_text(encoding="utf-8")

    assert "integrity_manifest.write_and_verify" in script
    assert "LIVEWATCH_INTEGRITY_PRIVATE_KEY" in script
    assert "Initialize-IntegritySigning" in script
    assert "__LIVEWATCH_INTEGRITY_PUBLIC_KEY__" in script
    assert "COMMERCIAL_NOTICE.txt" in script
    assert "完整性清单" in script
    assert "INTEGRITY_PUBLIC_KEY" in launcher
    assert "完整性清单签名无效" in launcher
    assert "_verify_integrity_manifest(base)" in launcher
    assert "_runtime_security_findings(base, app_dir)" in launcher
    assert "app/pipeline*.pyd" in launcher
    assert "检测到调试器附加" in launcher
    assert "完整性校验失败" in launcher


def test_release_launcher_bundles_license_crypto_dependencies():
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "packaging" / "build" / "build_release.ps1").read_text(encoding="utf-8")
    launcher = (repo_root / "packaging" / "build" / "livewatch_launcher.py").read_text(encoding="utf-8")

    assert "cryptography.hazmat.primitives.asymmetric.ed25519" in script
    assert "cryptography.hazmat.primitives.ciphers.aead" in script
    assert "Ed25519PublicKey" in launcher
    assert "AESGCM" in launcher
