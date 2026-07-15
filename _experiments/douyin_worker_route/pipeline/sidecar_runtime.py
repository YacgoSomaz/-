"""Lifecycle for the packaged local Douyin WebSocket event sidecar.

The executable is a separately distributed MIT-licensed component.  This
module deliberately treats it as a localhost-only process: the main app never
passes cookies across the network and never logs the generated configuration.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


DEFAULT_PORT = 1088
_PROCESS: subprocess.Popen[bytes] | None = None
_COOKIE_DIGEST = ""
_LOCK = threading.Lock()


@dataclass(frozen=True)
class SidecarResult:
    ok: bool
    reason: str
    config_path: Path | None = None


def _validate_cookie_header(cookie_header: str) -> str:
    cookie = str(cookie_header or "").strip()
    if "\r" in cookie or "\n" in cookie or "\x00" in cookie:
        raise ValueError("Cookie 包含非法控制字符")
    if len(cookie) > 32_768:
        raise ValueError("Cookie 长度异常")
    return cookie


def write_config(data_dir: Path, *, port: int, cookie_header: str) -> Path:
    """Write the private local sidecar config without ever printing its Cookie."""
    if not (1 <= int(port) <= 65_535):
        raise ValueError("sidecar 端口无效")
    cookie = _validate_cookie_header(cookie_header)
    runtime_dir = Path(data_dir) / "sidecar"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_dir / "douyinlive.yaml"
    # JSON string syntax is valid YAML and safely quotes semicolons/quotes.
    quoted_cookie = json.dumps(cookie, ensure_ascii=False)
    payload = (
        f'port: "{int(port)}"\n'
        "unknown: false\n"
        "log:\n"
        '  level: "warn"\n'
        "sign:\n"
        '  provider: "local"\n'
        "cookie:\n"
        f"  douyin: {quoted_cookie}\n"
    )
    config_path.write_text(payload, encoding="utf-8")
    return config_path


def safe_status_message(_cookie_header: str, _config_path: Path) -> str:
    """A status string guaranteed not to include credentials or private paths."""
    return "本地互动服务配置已更新"


def _probe_local_port(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
            return True
    except OSError:
        return False


def _start_process(executable: Path, config_path: Path, data_dir: Path, port: int) -> subprocess.Popen[bytes]:
    logs = Path(data_dir) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / "douyinlive.log"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with log_path.open("ab") as log_file:
        return subprocess.Popen(
            [str(executable), "--config", str(config_path), "--port", str(port), "--log-level", "warn"],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            close_fds=False,
        )


def ensure_running(
    executable: Path,
    data_dir: Path,
    *,
    live_id: str,
    cookie_header: str,
    port: int = DEFAULT_PORT,
    probe: Callable[[int], bool] = _probe_local_port,
    starter: Callable[[Path, Path, Path, int], subprocess.Popen[bytes]] = _start_process,
) -> SidecarResult:
    """Ensure the packaged sidecar is serving localhost before room WSS connects.

    A changed Cookie restarts only the child process this runtime owns.  An
    already-running external localhost service is left untouched.
    """
    del live_id  # Reserved for future per-room diagnostics; never put into config.
    executable = Path(executable)
    if not executable.is_file():
        return SidecarResult(False, "sidecar_not_packaged")
    cookie = _validate_cookie_header(cookie_header)
    if not cookie:
        return SidecarResult(False, "cookie_unavailable")
    digest = hashlib.sha256(cookie.encode("utf-8")).hexdigest()

    global _PROCESS, _COOKIE_DIGEST
    with _LOCK:
        if _PROCESS is None and probe(port):
            return SidecarResult(True, "external_sidecar")
        if _PROCESS is not None and _PROCESS.poll() is None and _COOKIE_DIGEST == digest and probe(port):
            return SidecarResult(True, "running")
        if _PROCESS is not None and _PROCESS.poll() is None:
            _PROCESS.terminate()
            try:
                _PROCESS.wait(timeout=3)
            except subprocess.TimeoutExpired:
                _PROCESS.kill()
        config_path = write_config(Path(data_dir), port=port, cookie_header=cookie)
        try:
            _PROCESS = starter(executable, config_path, Path(data_dir), int(port))
        except OSError:
            _PROCESS = None
            return SidecarResult(False, "sidecar_start_failed", config_path)
        _COOKIE_DIGEST = digest
        for _ in range(30):
            if probe(port):
                return SidecarResult(True, "started", config_path)
            if _PROCESS.poll() is not None:
                return SidecarResult(False, "sidecar_exited", config_path)
            time.sleep(0.1)
        return SidecarResult(False, "sidecar_unreachable", config_path)


def shutdown() -> None:
    """Stop only the sidecar process created by this app instance."""
    global _PROCESS, _COOKIE_DIGEST
    with _LOCK:
        process = _PROCESS
        _PROCESS = None
        _COOKIE_DIGEST = ""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
