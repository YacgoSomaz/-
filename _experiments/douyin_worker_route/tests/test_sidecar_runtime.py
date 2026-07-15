from __future__ import annotations

from pathlib import Path


def test_sidecar_config_uses_the_shared_cookie_without_leaking_it_to_logs(tmp_path: Path) -> None:
    from pipeline import sidecar_runtime

    cookie = "ttwid=trusted; sessionid=private-session"
    config_path = sidecar_runtime.write_config(tmp_path, port=1088, cookie_header=cookie)

    config = config_path.read_text(encoding="utf-8")
    assert 'port: "1088"' in config
    assert 'douyin: "ttwid=trusted; sessionid=private-session"' in config
    assert sidecar_runtime.safe_status_message(cookie, config_path) == "本地互动服务配置已更新"


def test_sidecar_runtime_rejects_cookie_header_injection(tmp_path: Path) -> None:
    from pipeline import sidecar_runtime

    try:
        sidecar_runtime.write_config(tmp_path, port=1088, cookie_header="ttwid=ok\nlog: debug")
    except ValueError as exc:
        assert "Cookie" in str(exc)
    else:
        raise AssertionError("newline-containing Cookie must be rejected")


def test_packaged_sidecar_path_must_be_an_executable_file(tmp_path: Path) -> None:
    from pipeline import sidecar_runtime

    result = sidecar_runtime.ensure_running(
        tmp_path / "missing.exe",
        tmp_path / "data",
        live_id="123",
        cookie_header="ttwid=trusted",
        probe=lambda _port: False,
    )

    assert result.ok is False
    assert result.reason == "sidecar_not_packaged"
