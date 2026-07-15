"""
一次性批量测试：对多个直播间各录制 1 分钟话术并转写。
    python batch_test.py 730184441361 421527298234 513622918406
"""

import asyncio
import logging
import os
import sys
import time

from stream_url import get_stream_url
from recorder import record_chunk
from transcriber import transcribe_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("batch")

RECORD_SEC = 60


async def capture_one(room_id: str) -> dict:
    """录制单个直播间 60 秒，返回 wav 路径与状态。"""
    live_url = f"https://live.douyin.com/{room_id}"
    result = {"room": room_id, "wav": None, "error": None}

    log.info("[%s] 获取流地址...", room_id)
    stream_url = await get_stream_url(live_url)
    if not stream_url:
        result["error"] = "未开播或拿不到流地址"
        log.warning("[%s] %s", room_id, result["error"])
        return result

    wav = f"room_{room_id}.wav"
    log.info("[%s] 录制 %d 秒...", room_id, RECORD_SEC)
    ok = await record_chunk(stream_url, wav, RECORD_SEC)
    if ok:
        result["wav"] = wav
        log.info("[%s] 录制完成 %.0fKB", room_id, os.path.getsize(wav) / 1024)
    else:
        result["error"] = "录制失败"
    return result


async def main(room_ids: list[str]):
    t0 = time.time()
    # 三路并发录制
    log.info("并发录制 %d 个直播间，各 %d 秒...", len(room_ids), RECORD_SEC)
    captures = await asyncio.gather(*(capture_one(r) for r in room_ids))
    log.info("录制阶段耗时 %.0fs", time.time() - t0)

    # 逐个转写（CPU 串行）
    loop = asyncio.get_event_loop()
    print("\n" + "=" * 60)
    for cap in captures:
        room = cap["room"]
        if cap["error"]:
            print(f"\n【直播间 {room}】 ❌ {cap['error']}")
            continue
        log.info("[%s] 转写中...", room)
        text = await loop.run_in_executor(None, transcribe_file, cap["wav"], "base")
        print(f"\n【直播间 {room}】 1分钟话术：")
        print(text or "（空，可能纯背景音/音乐）")
        os.remove(cap["wav"])
    print("\n" + "=" * 60)
    log.info("全部完成，总耗时 %.0fs", time.time() - t0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    rooms = sys.argv[1:] or ["730184441361", "421527298234", "513622918406"]
    asyncio.run(main(rooms))
