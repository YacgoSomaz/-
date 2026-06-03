"""
模块 B：录音

把直播流录成 16kHz 单声道 WAV 切片（Whisper 的标准输入格式）。
流地址有时效，所以每次录制前由模块 A 现取新地址。

独立测试（录 10 秒并报告文件大小）：
    python recorder.py "https://live.douyin.com/你的直播间ID"
"""

import asyncio
import logging
import os
import sys

import imageio_ffmpeg

from stream_url import get_stream_url

log = logging.getLogger("recorder")

FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()

# 抖音 CDN 拉流建议带 Referer，避免部分节点 403
_HEADERS = "Referer: https://live.douyin.com/\r\n"


async def start_segment_recorder(
    stream_url: str, out_pattern: str, segment_sec: int, stderr_path: str | None = None
):
    """
    启动单个 ffmpeg 进程，把直播流持续切成定长 WAV 段（无重连间隙）。
    out_pattern 形如 'dir/chunk_%05d.wav'。返回 ffmpeg 子进程。
    段 N 写完的标志是段 N+1 出现；进程退出时最后一段才算完。
    stderr_path: ffmpeg 诊断输出落盘路径，便于排查断流原因。
    """
    stderr_dest = open(stderr_path, "w") if stderr_path else asyncio.subprocess.DEVNULL
    return await asyncio.create_subprocess_exec(
        FFMPEG_BIN,
        "-y",
        "-reconnect", "1",            # 断线自动重连
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-headers", _HEADERS,
        "-i", stream_url,
        "-vn",
        "-ar", "16000",
        "-ac", "1",
        "-f", "segment",
        "-segment_time", str(segment_sec),
        "-reset_timestamps", "1",
        out_pattern,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=stderr_dest,
    )


async def record_chunk(stream_url: str, out_path: str, duration_sec: int) -> bool:
    """录制一段定长音频，成功返回 True。"""
    proc = await asyncio.create_subprocess_exec(
        FFMPEG_BIN,
        "-y",
        "-headers", _HEADERS,
        "-i", stream_url,
        "-t", str(duration_sec),
        "-vn",                 # 丢掉视频
        "-ar", "16000",        # 16kHz
        "-ac", "1",            # 单声道
        "-f", "wav",
        out_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    ok = proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1024
    if not ok:
        log.error("录制失败 rc=%s: %s", proc.returncode, stderr.decode(errors="ignore")[-300:])
    return ok


async def _test(live_url: str):
    log.info("现取新流地址...")
    stream_url = await get_stream_url(live_url)
    if not stream_url:
        log.error("没拿到流地址，无法录音")
        return 2

    out = "test_record.wav"
    log.info("开始录制 10 秒 -> %s", out)
    ok = await record_chunk(stream_url, out, duration_sec=10)

    if ok:
        size_kb = os.path.getsize(out) / 1024
        log.info("录制成功！文件大小 %.1f KB（10秒16kHz单声道约 ~320KB 为正常）", size_kb)
        return 0
    return 1


def _main():
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    if len(sys.argv) < 2:
        print("用法: python recorder.py <直播间URL>")
        sys.exit(1)
    sys.exit(asyncio.run(_test(sys.argv[1])))


if __name__ == "__main__":
    _main()
