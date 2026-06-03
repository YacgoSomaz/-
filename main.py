"""
抖音直播监听 MVP — 入口

用法：
  set DOUYIN_LIVE_URL=https://live.douyin.com/你的直播间ID
  python main.py

  # 只监听评论（不录音）
  python main.py --comments-only

  # 只录音转写
  python main.py --audio-only
"""

import asyncio
import argparse
import logging
import sys
import re

from config import LIVE_URL
from db import init_db
from comment_monitor import monitor as monitor_comments
from audio_capture import capture_and_transcribe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def _extract_room_id(url: str) -> str:
    """从直播间 URL 提取 room_id，找不到就用 URL 末尾路径段"""
    m = re.search(r"live\.douyin\.com/(\d+)", url)
    if m:
        return m.group(1)
    return url.rstrip("/").split("/")[-1]


async def run(live_url: str, comments_only: bool, audio_only: bool):
    await init_db()

    room_id = _extract_room_id(live_url)
    log.info("直播间 ID: %s", room_id)

    tasks = []

    if not audio_only:
        tasks.append(asyncio.create_task(
            monitor_comments(live_url, room_id),
            name="comments",
        ))

    if not comments_only:
        tasks.append(asyncio.create_task(
            capture_and_transcribe(live_url, room_id),
            name="audio",
        ))

    if not tasks:
        log.error("至少需要启用一个模块")
        return

    log.info("启动 %d 个监听任务，Ctrl+C 停止", len(tasks))

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        log.info("已停止，数据保存在 live_watch.db")


def main():
    parser = argparse.ArgumentParser(description="抖音直播监听 MVP")
    parser.add_argument("--url", default=LIVE_URL, help="直播间 URL")
    parser.add_argument("--comments-only", action="store_true", help="只监听评论")
    parser.add_argument("--audio-only", action="store_true", help="只录音转写")
    args = parser.parse_args()

    if not args.url:
        log.error("请设置环境变量 DOUYIN_LIVE_URL 或用 --url 传入直播间地址")
        sys.exit(1)

    try:
        asyncio.run(run(args.url, args.comments_only, args.audio_only))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
