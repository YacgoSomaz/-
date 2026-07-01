"""LiveWatch 桌面客户端（PyInstaller 打包入口）。

职责（不碰任何业务监听逻辑，只做"开机三件事"）：
  1. 把【用户数据】与【只读资源】从安装目录里分出去，通过环境变量注入给 pipeline.config：
       LIVEWATCH_DATA_DIR     → %LOCALAPPDATA%\\LiveWatch\\data （cookie / rooms.json / 库 / audio / exports / 日志）
       LIVEWATCH_RESOURCE_DIR → <安装目录>\\models               （SenseVoice / 3D-Speaker 模型）
     必须在 import pipeline.* 之前设置，因为 config 在导入时读取这两个变量。
  2. 把内置 node.exe 所在的 app\\bin 挂到 PATH（vendor 的弹幕签名要调 node）。
  3. 起 uvicorn 跑 pipeline.webui:app，并把日志写到数据目录 logs\\。
  4. 用 WebView2 显示独立客户端窗口；关闭窗口后缩到系统托盘继续监听。

目录布局（安装目录 = 本 exe 所在目录）：
  <install>/LiveWatchLauncher.exe
  <install>/_internal/         PyInstaller 运行时（含 Python、各 wheel、imageio_ffmpeg 的 ffmpeg.exe）
  <install>/app/              程序源码（pipeline / vendor / run_worker.py …）
  <install>/app/bin/node.exe  内置 Node
  <install>/models/          SenseVoice + 3D-Speaker 模型
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

# 显式 import，保证 PyInstaller 把这些运行时依赖打进 _internal（app/ 里的业务模块会用到）。
import fastapi  # noqa: F401
import fastapi.middleware.cors  # noqa: F401
import fastapi.staticfiles  # noqa: F401
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
import uvicorn
import uvicorn.loops.auto  # noqa: F401
import uvicorn.protocols.http.auto  # noqa: F401
import uvicorn.protocols.websockets.auto  # noqa: F401
import uvicorn.lifespan.on  # noqa: F401
import websocket  # noqa: F401
import websockets  # noqa: F401
import webview
import pystray
from PIL import Image, ImageDraw

APP_NAME = "直播复盘侠"
DEFAULT_PORT = 8848


def _base_dir() -> Path:
    """安装目录：冻结态取 exe 所在目录；源码态取本文件上两级（packaging/build → repo 根的占位）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _data_dir() -> Path:
    """用户数据根。优先环境变量覆盖，否则 %LOCALAPPDATA%\\LiveWatch\\data。"""
    override = os.environ.get("LIVEWATCH_DATA_DIR")
    if override:
        return Path(override).expanduser()
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "LiveWatch" / "data"


def _find_app_dir(base: Path) -> Path:
    candidates = [
        base / "app",
        base / "_experiments" / "douyin_worker_route",
        base.parent / "_experiments" / "douyin_worker_route",
        base.parent.parent / "_experiments" / "douyin_worker_route",
    ]
    for candidate in candidates:
        if (candidate / "pipeline" / "webui.py").exists():
            return candidate
    raise SystemExit(
        "没有找到 app/pipeline/webui.py。\n"
        "请确认 LiveWatchLauncher.exe 与 app、models 文件夹在同一个安装目录里。"
    )


def _resource_dir(base: Path) -> Path:
    override = os.environ.get("LIVEWATCH_RESOURCE_DIR")
    if override:
        return Path(override).expanduser()
    return base / "models"


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _available_port(preferred: int) -> int:
    """避免连接到其他安装/开发实例；端口被占时为本客户端选择新的本地端口。"""
    if not _port_open(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout_sec: float = 30) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.25)
    return False


def _tray_image() -> Image.Image:
    """生成简洁的 LiveWatch 托盘图标，避免额外二进制资源依赖。"""
    image = Image.new("RGBA", (64, 64), (14, 17, 23, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=(76, 132, 255, 255))
    draw.ellipse((18, 18, 46, 46), outline=(255, 255, 255, 255), width=5)
    draw.ellipse((27, 27, 37, 37), fill=(255, 255, 255, 255))
    return image


class _Tee:
    """把 stdout/stderr 同时写到控制台与日志文件，便于排障，不改变业务打印。"""

    def __init__(self, stream, log_handle) -> None:
        self._stream = stream
        self._log = log_handle

    def write(self, data: str) -> int:
        if self._stream is not None:
            try:
                self._stream.write(data)
            except Exception:  # noqa: BLE001
                pass
        try:
            self._log.write(data)
            self._log.flush()
        except Exception:  # noqa: BLE001
            pass
        return len(data)

    def flush(self) -> None:
        for target in (self._stream, self._log):
            if target is None:
                continue
            try:
                target.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self) -> bool:
        # uvicorn 的彩色日志格式器会探测 sys.stdout.isatty()；包到文件后按非 TTY 处理。
        if self._stream is None:
            return False
        try:
            return bool(self._stream.isatty())
        except Exception:  # noqa: BLE001
            return False

    def fileno(self) -> int:
        if self._stream is None:
            raise OSError("桌面客户端没有控制台文件描述符")
        return self._stream.fileno()

    def __getattr__(self, name):
        # 其余未知属性（encoding/errors/buffer 等）一律委托给底层真实流。
        if self._stream is None:
            if name == "encoding":
                return "utf-8"
            if name == "errors":
                return "replace"
            raise AttributeError(name)
        return getattr(self._stream, name)


class DesktopClient:
    """管理后端服务、独立窗口和系统托盘的生命周期。"""

    def __init__(self, url: str, data_dir: Path, server: uvicorn.Server | None) -> None:
        self.url = url
        self.data_dir = data_dir
        self.server = server
        self.exiting = False
        self.window = None
        self.tray = None

    def _show(self, *_args) -> None:
        if self.window is not None:
            self.window.show()
            self.window.restore()
            self.window.focus()

    def _open_data_dir(self, *_args) -> None:
        os.startfile(self.data_dir)  # type: ignore[attr-defined]

    def _exit(self, *_args) -> None:
        self.exiting = True
        if self.server is not None:
            self.server.should_exit = True
        if self.tray is not None:
            self.tray.stop()
        if self.window is not None:
            self.window.destroy()

    def _on_closing(self) -> bool:
        if self.exiting:
            return True
        if self.window is not None:
            self.window.hide()
        return False

    def _on_loaded(self) -> None:
        if self.window is not None:
            self.window.set_title(APP_NAME)

    def run(self) -> None:
        self.window = webview.create_window(
            APP_NAME,
            self.url,
            width=1320,
            height=860,
            min_size=(980, 640),
            background_color="#0e1117",
            text_select=True,
        )
        self.window.events.closing += self._on_closing
        self.window.events.loaded += self._on_loaded

        self.tray = pystray.Icon(
            "直播复盘侠",
            _tray_image(),
            APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("打开直播复盘侠", self._show, default=True),
                pystray.MenuItem("打开数据目录", self._open_data_dir),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("彻底退出", self._exit),
            ),
        )
        self.tray.run_detached()
        try:
            webview.start(gui="edgechromium", private_mode=False, storage_path=str(self.data_dir / "webview"))
        finally:
            self._exit()


def main() -> int:
    base = _base_dir()
    app_dir = _find_app_dir(base)
    data_dir = _data_dir()
    resource_dir = _resource_dir(base)

    # 1) 注入环境变量 —— 必须在 import pipeline.* 之前（config 在导入时读取）。
    os.environ["LIVEWATCH_DATA_DIR"] = str(data_dir)
    os.environ["LIVEWATCH_RESOURCE_DIR"] = str(resource_dir)
    bundled_browsers = base / "browsers"
    if bundled_browsers.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled_browsers)

    # 创建数据目录骨架（cookie/库/audio/exports/logs 都落这里）。
    log_dir = data_dir / "logs"
    for sub in ("", "audio", "exports", "logs"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)

    # 控制台日志落盘
    log_handle = None
    try:
        log_handle = (log_dir / f"console_{time.strftime('%Y%m%d')}.log").open(
            "a", encoding="utf-8", errors="replace"
        )
        sys.stdout = _Tee(sys.stdout, log_handle)
        sys.stderr = _Tee(sys.stderr, log_handle)
    except Exception:  # noqa: BLE001
        pass

    # 2) 内置 node.exe 上 PATH
    bundled_bin = app_dir / "bin"
    if bundled_bin.exists():
        os.environ["PATH"] = str(bundled_bin) + os.pathsep + os.environ.get("PATH", "")

    os.chdir(app_dir)
    sys.path.insert(0, str(app_dir))

    requested_port = int(os.environ.get("LIVEWATCH_PORT", DEFAULT_PORT))
    port = _available_port(requested_port)
    url = f"http://127.0.0.1:{port}"

    print()
    print("  直播复盘侠客户端")
    print("  ----------------------------------------")
    print(f"  安装目录: {app_dir}")
    print(f"  数据目录: {data_dir}")
    print(f"  模型目录: {resource_dir}")
    print(f"  控制台:   {url}")
    print()

    if port != requested_port:
        print(f"  端口 {requested_port} 已被其他程序占用，本客户端改用 {port}。")
    print("  正在启动后台服务。")
    from pipeline.webui import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, name="livewatch-server", daemon=True).start()
    if not _wait_for_port(port):
        raise SystemExit("后台服务启动超时，请查看数据目录 logs 下的日志。")

    DesktopClient(url, data_dir, server).run()
    if log_handle is not None:
        try:
            log_handle.close()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
