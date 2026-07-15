"""
模块 A：抖音直播流地址获取

策略：用 Playwright 打开直播页面，拦截网络请求里出现的
      .flv / .m3u8 流地址（由浏览器自然加载，无需逆向）。
      优先返回 HLS(.m3u8)，因为 ffmpeg 对它兼容性最好。

独立测试：
    python stream_url.py "https://live.douyin.com/你的直播间ID"
"""

import asyncio
import logging
import sys

from playwright.async_api import async_playwright, Response

log = logging.getLogger("stream_url")

# 命中即认为是直播流的 URL 特征
_HLS_HINTS = (".m3u8",)
_FLV_HINTS = (".flv", "pull-flv", "/stream-")


async def get_stream_url(live_url: str, timeout_sec: int = 8) -> str | None:
    """
    打开直播间，抓到第一个可用的流地址就返回。
    返回 None 表示没抓到（直播未开播 / 页面结构变化）。
    """
    found: asyncio.Future[str] = asyncio.get_event_loop().create_future()
    captured = {"hls": None, "flv": None}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        page = await context.new_page()

        def _on_response(resp: Response):
            url = resp.url
            low = url.lower()
            if any(h in low for h in _HLS_HINTS) and captured["hls"] is None:
                captured["hls"] = url
                log.info("发现 HLS 流: %s", url[:90])
                if not found.done():
                    found.set_result(url)  # HLS 优先，直接收
            elif any(h in low for h in _FLV_HINTS) and captured["flv"] is None:
                captured["flv"] = url
                log.info("发现 FLV 流: %s", url[:90])

        page.on("response", _on_response)

        log.info("打开直播间: %s", live_url)
        try:
            await page.goto(live_url, timeout=30_000, wait_until="domcontentloaded")
        except Exception as e:
            log.warning("页面加载异常（可继续等流）: %s", e)

        # 等 HLS 出现；超时则退而求其次用已抓到的 FLV
        try:
            await asyncio.wait_for(found, timeout=timeout_sec)
        except asyncio.TimeoutError:
            pass

        await browser.close()

    result = captured["hls"] or captured["flv"]
    if result:
        log.info("最终选用流地址: %s", result[:90])
    else:
        log.error("未抓到任何流地址（确认直播间正在开播？）")
    return result


def _main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    if len(sys.argv) < 2:
        print("用法: python stream_url.py <直播间URL>")
        sys.exit(1)

    url = asyncio.run(get_stream_url(sys.argv[1]))
    print("\n=== 结果 ===")
    print(url or "（未获取到，见上方日志）")
    sys.exit(0 if url else 2)


if __name__ == "__main__":
    _main()
