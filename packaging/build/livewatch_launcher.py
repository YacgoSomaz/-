"""LiveWatch 桌面客户端（PyInstaller 打包入口）。

职责（不碰任何业务监听逻辑，只做"开机三件事"）：
  1. 把【用户数据】与【只读资源】从安装目录里分出去，通过环境变量注入给 pipeline.config：
       LIVEWATCH_DATA_DIR     → %LOCALAPPDATA%\\LiveWatch\\data （cookie / rooms.json / 库 / audio / exports / 日志）
       LIVEWATCH_RESOURCE_DIR → <安装目录>\\models               （SenseVoice / 3D-Speaker 模型）
     必须在 import pipeline.* 之前设置，因为 config 在导入时读取这两个变量。
  2. 把内置 node.exe 所在的 app\\bin 挂到 PATH（少量解析/签名兼容逻辑可能用到 node）。
  3. 起 uvicorn 跑 pipeline.webui:app，并把日志写到数据目录 logs\\。
  4. 用 WebView2 显示独立客户端窗口；关闭窗口后缩到系统托盘继续监听。

目录布局（安装目录 = 本 exe 所在目录）：
  <install>/LiveWatchLauncher.exe
  <install>/_internal/         PyInstaller 运行时（含 Python、各 wheel、imageio_ffmpeg 的 ffmpeg.exe）
  <install>/app/              编译后的业务模块与公开前端资产（商业包不含 pipeline 源码）
  <install>/app/bin/node.exe  内置 Node
  <install>/models/          SenseVoice + 3D-Speaker 模型
"""
from __future__ import annotations

import os
import base64
import ctypes
import hashlib
import json
import shutil
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
import cryptography  # noqa: F401
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
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
MANIFEST_NAME = "integrity_manifest.json"
INTEGRITY_PUBLIC_KEY = "__LIVEWATCH_INTEGRITY_PUBLIC_KEY__"


def _show_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    except Exception:  # noqa: BLE001
        pass


def _base_dir() -> Path:
    """安装目录：冻结态取 exe 所在目录；源码态取本文件上两级（packaging/build → repo 根的占位）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _data_dir() -> Path:
    """用户数据根。优先环境变量覆盖，否则 %LOCALAPPDATA%\\LiveWatch\\data。"""
    override = None if _is_frozen() else os.environ.get("LIVEWATCH_DATA_DIR")
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
        has_source_package = (candidate / "pipeline" / "webui.py").exists()
        has_compiled_package = any(candidate.glob("pipeline*.pyd"))
        if has_source_package or has_compiled_package:
            return candidate
    raise SystemExit(
        "没有找到应用运行模块。\n"
        "请确认 LiveWatchLauncher.exe 与 app、models 文件夹在同一个安装目录里。"
    )


def _resource_dir(base: Path) -> Path:
    override = None if _is_frozen() else os.environ.get("LIVEWATCH_RESOURCE_DIR")
    if override:
        return Path(override).expanduser()
    return base / "models"


def _cleanup_legacy_local_install(base: Path, data_dir: Path) -> None:
    """Remove obsolete per-user program files while preserving user data.

    Older test packages installed source files under %LOCALAPPDATA%\\LiveWatch.
    Commercial builds live under Program Files and should not leave those source
    folders around. This cleanup is deliberately narrow: it only touches known
    legacy program paths and never removes the data directory.
    """
    if not _is_frozen():
        return
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    root = (Path(local) / "LiveWatch").resolve()
    current_base = base.resolve()
    if root == current_base or root in current_base.parents:
        return

    data_resolved = data_dir.resolve()
    targets = [
        root / "app",
        root / "_internal",
        root / "models",
        root / "asr_bench",
        root / "LiveWatchLauncher.exe",
        root / "install.bat",
        root / "install_to_desktop.ps1",
        root / "uninstall_livewatch.ps1",
        root / "uninstall_shortcut.bat",
        root / "安装到桌面.bat",
        root / "卸载快捷方式.bat",
        root / "README_使用说明.md",
    ]
    for target in targets:
        try:
            resolved = target.resolve()
        except FileNotFoundError:
            continue
        if resolved == data_resolved or data_resolved in resolved.parents:
            continue
        if resolved.parent != root and root not in resolved.parents:
            continue
        try:
            if resolved.is_dir():
                shutil.rmtree(resolved)
                print(f"  已清理旧版程序目录: {resolved}")
            elif resolved.exists():
                resolved.unlink()
                print(f"  已清理旧版程序文件: {resolved}")
        except Exception as exc:  # noqa: BLE001
            print(f"  旧版残留清理失败，可忽略或手动删除: {resolved} ({exc})")


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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _canonical_manifest_payload(manifest: dict) -> bytes:
    unsigned = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _verify_integrity_manifest(base: Path) -> list[str]:
    manifest_path = base / MANIFEST_NAME
    if not manifest_path.exists():
        return [f"缺少完整性清单：{MANIFEST_NAME}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"完整性清单读取失败：{exc}"]

    findings: list[str] = []
    public_key = INTEGRITY_PUBLIC_KEY.strip()
    if not public_key or public_key.startswith("__LIVEWATCH_"):
        findings.append("缺少完整性清单签名公钥")
    else:
        signature = manifest.get("signature")
        if not isinstance(signature, str) or not signature:
            findings.append("完整性清单缺少签名")
        elif manifest.get("signature_algorithm") != "Ed25519":
            findings.append("完整性清单签名算法不受支持")
        else:
            try:
                Ed25519PublicKey.from_public_bytes(_b64url_decode(public_key)).verify(
                    _b64url_decode(signature),
                    _canonical_manifest_payload(manifest),
                )
            except (ValueError, InvalidSignature) as exc:
                findings.append(f"完整性清单签名无效：{exc.__class__.__name__}")

    covered: set[str] = set()
    for item in manifest.get("files", []):
        rel = str(item.get("path", "")).replace("\\", "/")
        covered.add(rel)
        expected = str(item.get("sha256", ""))
        if not rel or not expected:
            findings.append(f"清单条目无效：{rel or '<empty>'}")
            continue
        target = base / rel
        if not target.exists():
            findings.append(f"缺少文件：{rel}")
            continue
        if _sha256_file(target) != expected:
            findings.append(f"文件被修改：{rel}")
    skipped_dirs = {".git", "__pycache__", "audio", "exports", "logs", "models", "video"}
    skipped_files = {
        MANIFEST_NAME,
        "license.json",
        "license_clock.json",
        "browser_cookies.json",
        "short_video_cookies.json",
        "rooms.json",
        "transcripts.db",
        "multi_events.db",
    }
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(base)
        lower_name = path.name.lower()
        if lower_name.startswith("unins") and lower_name.rsplit(".", 1)[-1] in {"dat", "exe", "msg"}:
            continue
        if set(rel_path.parts) & skipped_dirs or path.name in skipped_files:
            continue
        rel = rel_path.as_posix()
        if rel not in covered:
            findings.append(f"发现未授权文件：{rel}")
    return findings


def _is_debugger_attached() -> bool:
    if sys.gettrace() is not None:
        return True
    if os.name != "nt":
        return False
    try:
        if bool(ctypes.windll.kernel32.IsDebuggerPresent()):
            return True
        attached = ctypes.wintypes.BOOL()
        ok = ctypes.windll.kernel32.CheckRemoteDebuggerPresent(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(attached),
        )
        return bool(ok and attached.value)
    except Exception:  # noqa: BLE001
        return False


def _runtime_security_findings(base: Path, app_dir: Path) -> list[str]:
    """Commercial runtime hardening checks.

    These checks are not meant to be unbreakable DRM. They cheaply block the
    most common repackaging mistakes: shipping source folders, running a
    modified install tree, or attaching a debugger to inspect the activation
    flow. They run only in frozen desktop builds so development stays pleasant.
    """
    if not _is_frozen():
        return []
    findings: list[str] = []
    compiled = list(app_dir.glob("pipeline*.pyd"))
    if not compiled:
        findings.append("缺少商业编译模块：app/pipeline*.pyd")
    forbidden_dirs = ("pipeline", "vendor", "third_party", "tests", "__pycache__")
    for name in forbidden_dirs:
        if (app_dir / name).exists():
            findings.append(f"安装目录包含不应发布的源码目录：app/{name}")
    leaked_sources = sorted(app_dir.rglob("*.py"))
    if leaked_sources:
        sample = leaked_sources[0].relative_to(base).as_posix()
        findings.append(f"安装目录包含 Python 源码文件：{sample}")
    if _is_debugger_attached():
        findings.append("检测到调试器附加，已停止启动")
    return findings


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
            try:
                self.window.maximize()
            except Exception:  # noqa: BLE001
                pass
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
            try:
                self.window.maximize()
            except Exception:  # noqa: BLE001
                pass

    def run(self) -> None:
        self.window = webview.create_window(
            APP_NAME,
            self.url,
            width=1320,
            height=860,
            min_size=(980, 640),
            maximized=True,
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
    packaged_assets = app_dir / "pipeline_data"
    if packaged_assets.exists():
        os.environ["LIVEWATCH_PIPELINE_DATA_DIR"] = str(packaged_assets)
    os.environ.setdefault("LIVEWATCH_DANMU_BACKEND", "audio_only")
    bundled_browsers = base / "browsers"
    if bundled_browsers.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled_browsers)

    # 创建数据目录骨架（cookie/库/audio/exports/logs 都落这里）。
    log_dir = data_dir / "logs"
    for sub in ("", "audio", "exports", "logs"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    _cleanup_legacy_local_install(base, data_dir)

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

    findings = _verify_integrity_manifest(base)
    findings.extend(_runtime_security_findings(base, app_dir))
    if findings:
        message = "程序文件完整性校验失败，可能被篡改或安装不完整，请重新安装官方安装包。"
        print(message)
        for item in findings[:10]:
            print(f"  - {item}")
        _show_error(message)
        raise SystemExit(message)

    requested_port = int(os.environ.get("LIVEWATCH_PORT", DEFAULT_PORT))
    port = _available_port(requested_port)
    url = f"http://127.0.0.1:{port}"

    print()
    print("  直播复盘侠客户端")
    print("  ----------------------------------------")
    print(f"  安装目录: {app_dir}")
    print(f"  数据目录: {data_dir}")
    print(f"  模型目录: {resource_dir}")
    print(f"  弹幕后端: {os.environ.get('LIVEWATCH_DANMU_BACKEND', 'audio_only')}")
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
