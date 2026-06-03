"""
评论监听模块

原理：
  Playwright 打开抖音直播页面，监听其建立的 WebSocket 连接，
  从收到的二进制帧中解析 Protobuf → 提取弹幕/评论。
  这样完全不需要手动处理签名/Cookie，由浏览器代劳。
"""

import asyncio
import gzip
import time
import logging
from typing import Callable, Awaitable

from playwright.async_api import async_playwright, WebSocket, Page
import douyin_pb2  # protoc 生成

from db import save_comment

log = logging.getLogger("comment")

# 感兴趣的消息类型 → 对应 proto Message 类
_HANDLERS = {
    "WebcastChatMessage": douyin_pb2.ChatMessage,
}


def _parse_frame(raw: bytes) -> list[dict]:
    """解析一帧 WebSocket 数据，返回评论列表"""
    results = []
    try:
        frame = douyin_pb2.PushFrame()
        frame.ParseFromString(raw)

        payload = frame.payload
        if frame.payload_encoding == "gzip":
            payload = gzip.decompress(payload)

        resp = douyin_pb2.Response()
        resp.ParseFromString(payload)

        for msg in resp.messages:
            handler_cls = _HANDLERS.get(msg.method)
            if handler_cls is None:
                continue
            obj = handler_cls()
            obj.ParseFromString(msg.payload)

            if msg.method == "WebcastChatMessage":
                results.append({
                    "type": "comment",
                    "user": obj.user.nick_name,
                    "content": obj.content,
                    "ts": int(time.time() * 1000),
                })

    except Exception as e:
        log.debug("frame parse error: %s", e)

    return results


async def monitor(
    live_url: str,
    room_id: str,
    on_comment: Callable[[dict], Awaitable[None]] | None = None,
):
    """
    打开直播页面并持续监听评论，直到协程被取消。
    on_comment: 异步回调，每条评论触发一次
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,  # False 方便观察；稳定后可改 True
            args=["--mute-audio"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        page: Page = await context.new_page()

        def _on_ws(ws: WebSocket):
            if "webcast" not in ws.url:
                return
            log.info("WebSocket 已连接: %s", ws.url[:80])

            async def _on_frame(payload):
                if isinstance(payload, bytes):
                    items = _parse_frame(payload)
                    for item in items:
                        log.info("[评论] %s: %s", item["user"], item["content"])
                        await save_comment(
                            room_id, item["user"], item["content"], item["ts"]
                        )
                        if on_comment:
                            await on_comment(item)

            ws.on("framereceived", lambda p: asyncio.ensure_future(_on_frame(p)))

        page.on("websocket", _on_ws)

        log.info("打开直播间: %s", live_url)
        await page.goto(live_url, timeout=30_000)

        # 等待页面稳定（处理可能的登录弹窗/青少年弹窗）
        await asyncio.sleep(3)
        await _dismiss_popups(page)

        # 持续运行，直到外部取消
        try:
            while True:
                await asyncio.sleep(30)
                log.debug("心跳 — 仍在监听")
        except asyncio.CancelledError:
            log.info("评论监听已停止")
        finally:
            await browser.close()


async def _dismiss_popups(page: Page):
    """尝试关闭常见弹窗（青少年模式、登录引导等）"""
    selectors = [
        'button:has-text("我知道了")',
        'button:has-text("关闭")',
        '[data-e2e="close-button"]',
        '.douyin-modal__close',
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass
