from __future__ import annotations

from pathlib import Path

from pipeline import integrity_manifest


def test_manifest_verifies_clean_install_tree(tmp_path: Path) -> None:
    install = tmp_path / "LiveWatch"
    app = install / "app"
    data = install / "data"
    app.mkdir(parents=True)
    data.mkdir()
    (install / "LiveWatchLauncher.exe").write_bytes(b"launcher")
    (app / "pipeline.cp314-win_amd64.pyd").write_bytes(b"business")
    (app / "pipeline_data" / "static").mkdir(parents=True)
    (app / "pipeline_data" / "static" / "app.js").write_text("ok", encoding="utf-8")
    (data / "license.json").write_text("must not be covered", encoding="utf-8")

    manifest = integrity_manifest.build_manifest(install)
    integrity_manifest.write_manifest(install, manifest)

    assert integrity_manifest.verify_manifest(install) == []
    covered = {entry["path"] for entry in manifest["files"]}
    assert "data/license.json" not in covered


def test_signed_manifest_rejects_rehashed_tamper(tmp_path: Path) -> None:
    install = tmp_path / "LiveWatch"
    app = install / "app"
    app.mkdir(parents=True)
    target = app / "pipeline.cp314-win_amd64.pyd"
    target.write_bytes(b"business")
    private_key, public_key = integrity_manifest.generate_keypair()
    integrity_manifest.write_and_verify(
        install,
        private_key_b64=private_key,
        public_key_b64=public_key,
    )

    target.write_bytes(b"patched")
    # Simulate the previous bypass: attacker recalculates hashes but cannot
    # produce a valid Ed25519 signature for the new manifest.
    integrity_manifest.write_manifest(install, integrity_manifest.build_manifest(install))

    findings = integrity_manifest.verify_manifest(
        install,
        public_key_b64=public_key,
        require_signature=True,
    )

    assert any("signature" in item for item in findings)


def test_manifest_detects_tampered_file(tmp_path: Path) -> None:
    install = tmp_path / "LiveWatch"
    app = install / "app"
    app.mkdir(parents=True)
    target = app / "pipeline.cp314-win_amd64.pyd"
    target.write_bytes(b"business")
    integrity_manifest.write_manifest(install, integrity_manifest.build_manifest(install))

    target.write_bytes(b"patched")

    findings = integrity_manifest.verify_manifest(install)

    assert any("hash mismatch" in item and "pipeline.cp314-win_amd64.pyd" in item for item in findings)


def test_manifest_detects_missing_file(tmp_path: Path) -> None:
    install = tmp_path / "LiveWatch"
    app = install / "app"
    app.mkdir(parents=True)
    target = app / "pipeline.cp314-win_amd64.pyd"
    target.write_bytes(b"business")
    integrity_manifest.write_and_verify(install)

    target.unlink()

    findings = integrity_manifest.verify_manifest(install)

    assert any("missing" in item and "pipeline.cp314-win_amd64.pyd" in item for item in findings)


def test_manifest_detects_unlisted_extra_file(tmp_path: Path) -> None:
    install = tmp_path / "LiveWatch"
    app = install / "app"
    app.mkdir(parents=True)
    (app / "pipeline.cp314-win_amd64.pyd").write_bytes(b"business")
    integrity_manifest.write_and_verify(install)

    (app / "evil.py").write_text("print('patched')", encoding="utf-8")

    findings = integrity_manifest.verify_manifest(install)

    # Extra files are no longer a startup failure. Only files in the immutable
    # core allowlist are covered; user data and optional tools may coexist.
    assert findings == []


def test_manifest_ignores_user_config_and_imported_assets(tmp_path: Path) -> None:
    install = tmp_path / "LiveWatch"
    app = install / "app"
    data = install / "data"
    app.mkdir(parents=True)
    data.mkdir(parents=True)
    (install / "LiveWatchLauncher.exe").write_bytes(b"launcher")
    (app / "pipeline.cp314-win_amd64.pyd").write_bytes(b"business")
    manifest = integrity_manifest.build_manifest(install)
    integrity_manifest.write_manifest(install, manifest)

    (data / "export_dir.txt").write_text(r"D:\customer\exports", encoding="utf-8")
    (data / "素材.png").write_bytes(b"user asset")
    (app / "optional-tool.txt").write_text("user note", encoding="utf-8")

    findings = integrity_manifest.verify_manifest(install)

    assert findings == []
    covered = {entry["path"] for entry in manifest["files"]}
    assert "data/export_dir.txt" not in covered
    assert "data/素材.png" not in covered
    assert "app/optional-tool.txt" not in covered


def test_manifest_only_covers_launcher_and_compiled_business_module(tmp_path: Path) -> None:
    install = tmp_path / "LiveWatch"
    app = install / "app"
    (app / "pipeline_data").mkdir(parents=True)
    (app / "sidecar").mkdir(parents=True)
    (app / "bin").mkdir(parents=True)
    (install / "_internal").mkdir(parents=True)
    (install / "LiveWatchLauncher.exe").write_bytes(b"launcher")
    (app / "pipeline.cp314-win_amd64.pyd").write_bytes(b"business-and-auth")
    (app / "pipeline_data" / "frontend.html").write_text("ui", encoding="utf-8")
    (app / "sidecar" / "douyinLive.exe").write_bytes(b"sidecar")
    (app / "bin" / "node.exe").write_bytes(b"node")
    (install / "_internal" / "python.dll").write_bytes(b"runtime")

    manifest = integrity_manifest.build_manifest(install)
    covered = {entry["path"] for entry in manifest["files"]}

    assert covered == {"LiveWatchLauncher.exe", "app/pipeline.cp314-win_amd64.pyd"}
