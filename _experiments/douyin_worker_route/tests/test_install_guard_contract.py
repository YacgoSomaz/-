from __future__ import annotations

import importlib.util
from pathlib import Path

from pipeline import integrity_manifest


def _load_guard():
    root = Path(__file__).resolve().parents[3]
    source = root / "packaging" / "build" / "livewatch_guard.py"
    spec = importlib.util.spec_from_file_location("livewatch_guard_contract", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_signed_install(install: Path) -> tuple[object, str]:
    app = install / "app"
    (app / "pipeline_data" / "static").mkdir(parents=True)
    (app / "pipeline_data" / "lexicons").mkdir(parents=True)
    (install / "LiveWatchGuard.exe").write_bytes(b"guard")
    (install / "LiveWatchLauncher.exe").write_bytes(b"launcher")
    (app / "pipeline.cp314-win_amd64.pyd").write_bytes(b"business")
    (app / "pipeline_data" / "frontend.html").write_text("frontend", encoding="utf-8")
    (app / "pipeline_data" / "static" / "app.js").write_text("ui", encoding="utf-8")
    private, public = integrity_manifest.generate_keypair()
    integrity_manifest.write_and_verify(install, private_key_b64=private, public_key_b64=public)
    guard = _load_guard()
    guard.INTEGRITY_PUBLIC_KEY = public
    return guard, public


def test_compiled_guard_contract_rejects_tampered_ui_but_not_user_data(tmp_path: Path) -> None:
    guard, _ = _make_signed_install(tmp_path / "LiveWatch")
    install = tmp_path / "LiveWatch"

    assert guard._verify_install_integrity(install) == []

    (install / "data" / "exports").mkdir(parents=True)
    (install / "data" / "exports" / "customer.mp4").write_bytes(b"user content")
    assert guard._verify_install_integrity(install) == []

    (install / "app" / "pipeline_data" / "frontend.html").write_text("patched", encoding="utf-8")
    findings = guard._verify_install_integrity(install)
    assert any("核心文件已被修改：app/pipeline_data/frontend.html" == item for item in findings)
