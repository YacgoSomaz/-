"""
音频流水线：A + B + C 持续运行

生产者：单个 ffmpeg 进程把直播流持续切成定长 WAV 段（不停）。
消费者：监视切片目录，对已写完的段做 Whisper 转写 → 落库 → 删文件。
流地址失效 / 直播断流时，自动用模块 A 现取新地址并重启录制。

独立运行：
    python audio_pipeline.py "https://live.douyin.com/直播间ID"
"""

import asyncio
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

from stream_url import get_stream_url
from recorder import start_segment_recorder
from transcriber import transcribe_file
from db import init_db, save_transcript

log = logging.getLogger("pipeline")

SEGMENT_SEC = 15          # 每段时长
MODEL_NAME = "base"


def _segment_index(path: Path) -> int:
    # chunk_00007.wav -> 7
    return int(path.stem.split("_")[-1])


async def _consume_segments(out_dir: str, room_id: str, ffmpeg_proc, stop: asyncio.Event):
    """监视目录，转写写完的切片。段 N 在 段 N+1 出现后视为写完。"""
    processed: set[int] = set()
    loop = asyncio.get_event_loop()

    while not stop.is_set():
        wavs = sorted(Path(out_dir).glob("chunk_*.wav"), key=_segment_index)
        ffmpeg_done = ffmpeg_proc.returncode is not None

        # 除最后一个外都算写完；ffmpeg 已退出时最后一个也算
        ready = wavs if ffmpeg_done else wavs[:-1]

        for wav in ready:
            idx = _segment_index(wav)
            if idx in processed:
                continue
            processed.add(idx)

            text = await loop.run_in_executor(None, transcribe_file, str(wav), MODEL_NAME)
            start_sec = idx * SEGMENT_SEC
            if text:
                log.info("[话术 +%ds] %s", start_sec, text)
                await save_transcript(room_id, text, start_sec, int(time.time()))
            wav.unlink(missing_ok=True)

        if ffmpeg_done and len(processed) >= len(wavs):
            break
        await asyncio.sleep(1)


async def run_audio_pipeline(live_url: str, room_id: str):
    await init_db()
    out_dir = tempfile.mkdtemp(prefix="live_watch_seg_")
    log.info("切片目录: %s", out_dir)
    pattern = os.path.join(out_dir, "chunk_%05d.wav")

    try:
        while True:  # 断流自愈循环
            stream_url = await get_stream_url(live_url)
            if not stream_url:
                log.warning("拿不到流地址，10s 后重试（直播可能未开播）")
                await asyncio.sleep(10)
                continue

            log.info("开始持续录制（每段 %ds）", SEGMENT_SEC)
            stderr_log = os.path.join(out_dir, "ffmpeg.err")
            ffmpeg = await start_segment_recorder(
                stream_url, pattern, SEGMENT_SEC, stderr_path=stderr_log
            )

            stop = asyncio.Event()
            consumer = asyncio.create_task(
                _consume_segments(out_dir, room_id, ffmpeg, stop)
            )

            await ffmpeg.wait()  # 正常情况下会一直跑，退出 = 断流/失效
            log.warning("ffmpeg 退出（断流或地址失效），收尾后重连")
            await consumer  # 把剩余切片处理完

            # 清理本轮残留切片，重新取地址
            for f in Path(out_dir).glob("chunk_*.wav"):
                f.unlink(missing_ok=True)
            await asyncio.sleep(2)

    except asyncio.CancelledError:
        log.info("音频流水线停止")
        raise
    finally:
        for f in Path(out_dir).glob("*.wav"):
            f.unlink(missing_ok=True)
        Path(out_dir).rmdir()


def _main():
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    if len(sys.argv) < 2:
        print("用法: python audio_pipeline.py <直播间URL>")
        sys.exit(1)

    room_id = sys.argv[1].rstrip("/").split("/")[-1]
    try:
        asyncio.run(run_audio_pipeline(sys.argv[1], room_id))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    _main()
