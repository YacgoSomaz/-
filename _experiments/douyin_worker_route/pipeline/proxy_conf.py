"""代理配置：读取用户配置的 HTTP/SOCKS5 代理，供全链路请求复用。

配置来源（按优先级）：
  1. 环境变量 LIVEWATCH_PROXY  （如 http://127.0.0.1:10809）
  2. DATA_DIR/proxy.txt 第一行  （同上格式）
  3. 无代理（直连）

支持格式：
  http://host:port
  http://user:pass@host:port
  socks5://host:port
  socks5://user:pass@host:port

requests 库原生支持以上格式（SOCKS5 需 pip install requests[socks]，即 PySocks）。
websocket-client 仅原生支持 HTTP 代理；SOCKS5 需要 python-socks 或自建隧道。
为简化依赖，建议 Xray 同时暴露 HTTP 代理端口（默认 10809）供 WebSocket 使用。
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

from . import config

log = logging.getLogger(__name__)

_PROXY_CONF_FILE = config.DATA_DIR / "proxy.txt"
_cached: str | None = None
_loaded = False


def _load() -> str:
    """加载一次，返回原始代理 URL 或空串。"""
    global _cached, _loaded
    if _loaded:
        return _cached or ""
    _loaded = True

    env = os.environ.get("LIVEWATCH_PROXY", "").strip()
    if env:
        _cached = env
        log.info("代理(env): %s", _cached)
        return _cached

    if _PROXY_CONF_FILE.is_file():
        line = _PROXY_CONF_FILE.read_text(encoding="utf-8").strip().splitlines()
        if line and line[0].strip():
            _cached = line[0].strip()
            log.info("代理(file): %s", _cached)
            return _cached

    _cached = ""
    return ""


def reload() -> None:
    """强制重新读取（设置页更改代理后调用）。"""
    global _loaded
    _loaded = False
    _load()


def get_proxy_url() -> str:
    """返回代理 URL，空串表示直连。"""
    return _load()


def requests_proxies() -> dict[str, str] | None:
    """给 requests.Session.proxies 用的 dict，无代理返回 None。"""
    url = _load()
    if not url:
        return None
    return {"http": url, "https": url}


def ws_proxy_kwargs() -> dict:
    """给 websocket.WebSocketApp.run_forever() 用的代理参数。

    websocket-client 原生只支持 HTTP 代理，通过 http_proxy_host/port 传入。
    SOCKS5 需额外依赖（python-socks）；如果检测到 socks5:// 协议，会尝试
    使用 socks_proxy_type 参数（需 websocket-client[optional] >= 1.7）。
    """
    url = _load()
    if not url:
        return {}

    p = urlparse(url)
    scheme = (p.scheme or "").lower()
    host = p.hostname or ""
    port = p.port or (1080 if "socks" in scheme else 8080)

    kwargs: dict = {
        "http_proxy_host": host,
        "http_proxy_port": port,
    }
    if p.username:
        kwargs["http_proxy_auth"] = (p.username, p.password or "")

    if "socks5" in scheme:
        kwargs["proxy_type"] = "socks5"
    elif "socks4" in scheme:
        kwargs["proxy_type"] = "socks4"

    return kwargs


def save_proxy(url: str) -> None:
    """持久保存代理配置到 proxy.txt。"""
    _PROXY_CONF_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROXY_CONF_FILE.write_text(url.strip() + "\n", encoding="utf-8")
    reload()
