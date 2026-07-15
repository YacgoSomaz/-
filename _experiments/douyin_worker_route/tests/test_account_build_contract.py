from __future__ import annotations

from pathlib import Path


BUILD_SCRIPT = Path(__file__).resolve().parents[3] / "packaging" / "build" / "build_release.ps1"


def test_commercial_build_embeds_only_public_account_and_update_verification_material() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "[string]$AccountApiUrl" in script
    assert "[string]$AccountPublicKey" in script
    assert "[string]$AccountProductCode" in script
    assert "[string]$UpdatePublicKey" in script
    assert 'LICENSE_ENFORCE = False' in script
    assert 'ACCOUNT_API_URL = "$AccountApiUrl"' in script
    assert 'ACCOUNT_PUBLIC_KEY = "$AccountPublicKey"' in script
    assert 'ACCOUNT_PRODUCT_CODE = "$AccountProductCode"' in script
    assert 'UPDATE_PUBLIC_KEY = "$UpdatePublicKey"' in script
    assert "LICENSE_ENFORCE = True" not in script
    assert "完整性签名密钥格式无效" in script
