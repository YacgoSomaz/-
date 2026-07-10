from pathlib import Path

from pipeline.package_assets import package_asset_dir


def test_package_asset_dir_defaults_to_module_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("LIVEWATCH_PIPELINE_DATA_DIR", raising=False)
    module_file = tmp_path / "pipeline" / "webui.py"

    assert package_asset_dir(module_file) == module_file.parent


def test_package_asset_dir_uses_explicit_data_directory_for_compiled_package(monkeypatch, tmp_path) -> None:
    expected = tmp_path / "pipeline_data"
    monkeypatch.setenv("LIVEWATCH_PIPELINE_DATA_DIR", str(expected))

    assert package_asset_dir(tmp_path / "pipeline.cp314-win_amd64.pyd") == expected

