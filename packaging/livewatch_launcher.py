from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Imports below are intentionally explicit so PyInstaller bundles runtime deps
# used by the app modules loaded from the external app/ directory.
import fastapi  # noqa: F401
import fastapi.middleware.cors  # noqa: F401
import betterproto  # noqa: F401
import execjs  # noqa: F401
import imageio_ffmpeg  # noqa: F401
import jieba  # noqa: F401
import numpy  # noqa: F401
import openpyxl  # noqa: F401
import playwright.sync_api  # noqa: F401
import reportlab  # noqa: F401
import requests  # noqa: F401
import sherpa_onnx  # noqa: F401
import sqlite3  # noqa: F401
import uvicorn  # noqa: F401
import uvicorn.loops.auto  # noqa: F401
import uvicorn.protocols.http.auto  # noqa: F401
import uvicorn.protocols.websockets.auto  # noqa: F401
import uvicorn.lifespan.on  # noqa: F401
import websocket  # noqa: F401
import websockets  # noqa: F401


APP_NAME = "直播复盘侠"
DEFAULT_PORT = 8848


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _find_app_dir() -> Path:
    base = _base_dir()
    candidates = [
        base / "app",
        base / "_experiments" / "douyin_worker_route",
        base.parent / "_experiments" / "douyin_worker_route",
    ]
    for candidate in candidates:
        if (candidate / "pipeline" / "webui.py").exists():
            return candidate
    raise SystemExit(
        "没有找到 app/pipeline/webui.py。\n"
        "请确认 LiveWatch启动器.exe 和 app 文件夹在同一个目录。"
    )


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _open_browser_later(url: str) -> None:
    time.sleep(2)
    webbrowser.open(url)


def main() -> int:
    os.system(f"title {APP_NAME}")
    port = int(os.environ.get("LIVEWATCH_PORT", DEFAULT_PORT))
    url = f"http://127.0.0.1:{port}"
    app_dir = _find_app_dir()
    os.environ.setdefault("LIVEWATCH_DANMU_BACKEND", "audio_only")
    bundled_bin = app_dir / "bin"
    if bundled_bin.exists():
        os.environ["PATH"] = str(bundled_bin) + os.pathsep + os.environ.get("PATH", "")
    os.chdir(app_dir)
    sys.path.insert(0, str(app_dir))

    print()
    print("  直播复盘侠")
    print("  ----------------------------------------")
    print(f"  安装目录: {app_dir}")
    print(f"  弹幕后端: {os.environ.get('LIVEWATCH_DANMU_BACKEND', 'audio_only')}")
    print(f"  控制台:   {url}")
    print()

    if _port_open(port):
        print("  检测到控制台已经在运行，正在打开浏览器。")
        webbrowser.open(url)
        input("  按回车退出启动器窗口...")
        return 0

    print("  正在启动后端服务。关闭这个窗口会停止监听。")
    print()
    threading.Thread(target=_open_browser_later, args=(url,), daemon=True).start()

    from pipeline.webui import app

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
