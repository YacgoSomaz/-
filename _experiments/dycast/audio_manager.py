"""音频托管：按房间启停"录音→转写→落库(话术)"，与弹幕共用同一触发与同一库。

设计：
  - 由 server.py 的 relay_handler 驱动：浏览器检测到开播并接入弹幕时 -> start_room；
    弹幕连接断开(下播/停止托管) -> stop_room。不重复轮询开播状态。
  - 复用项目根目录已验证的音频模块：stream_url(取流) / recorder(ffmpeg切片) /
    transcriber(本地 Whisper)。
  - 无 GPU 现实约束：
      * AUDIO_MAX_ROOMS 限制"同时录制"的房间数(信号量)，超出排队；
      * 全局转写串行(一把锁)，避免 N 段同时占满 CPU；
      * 默认模型 base，兼顾可读性；可用 AUDIO_MODEL=tiny 提速。
  - 强隔离：任一房间音频异常不影响弹幕中继与其它房间。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

# 让本模块能 import 项目根目录的音频模块(stream_url/recorder/transcriber 在根目录)
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("audio-manager")

# 真正延迟导入：测试/弹幕后端启动不应被 Whisper/Torch 的导入成本拖住。
get_stream_url = None
start_segment_recorder = None
get_model = None
transcribe_file = None
_IMPORT_ERR: Exception | None = None


def _import_audio_deps() -> bool:
    global get_stream_url, start_segment_recorder, get_model, transcribe_file, _IMPORT_ERR
    try:
        from stream_url import get_stream_url as _get_stream_url
        from recorder import start_segment_recorder as _start_segment_recorder
        from transcriber import get_model as _get_model
        from transcriber import transcribe_file as _transcribe_file
    except Exception as exc:  # noqa: BLE001
        _IMPORT_ERR = exc
        return False
    get_stream_url = _get_stream_url
    start_segment_recorder = _start_segment_recorder
    get_model = _get_model
    transcribe_file = _transcribe_file
    return True


def _ensure_runtime_deps() -> bool:
    if get_stream_url and start_segment_recorder and transcribe_file:
        return True
    return _import_audio_deps()


def _ensure_warmup_deps() -> bool:
    if get_model:
        return True
    return _import_audio_deps()


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() not in ("0", "false", "no", "")


AUDIO_ENABLED = _env_bool("AUDIO_ENABLED", True)
AUDIO_MAX_ROOMS = int(os.getenv("AUDIO_MAX_ROOMS", "5"))
AUDIO_MODEL = os.getenv("AUDIO_MODEL", "base")
AUDIO_SEGMENT_SEC = int(os.getenv("AUDIO_SEGMENT_SEC", "30"))
_STREAM_RETRY_MAX = 6  # 接入弹幕后仍连续取不到流，放弃并让出并发槽

LIVE_URL_TEMPLATE = "https://live.douyin.com/{room}"

# (room_num, text, start_sec, ts) -> 是否新插入
SaveCallback = Callable[[str, str, int, int], bool]


def _seg_idx(path: Path) -> int:
    return int(path.stem.split("_")[-1])


async def _terminate_proc(proc) -> None:
    """优雅终止 ffmpeg 子进程：先 terminate，超时再 kill。"""
    if proc is None or proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _cleanup_dir(out_dir: str) -> None:
    p = Path(out_dir)
    try:
        for f in p.glob("*"):
            f.unlink(missing_ok=True)
        p.rmdir()
    except OSError:
        pass


class AudioManager:
    def __init__(
        self,
        save_cb: SaveCallback,
        *,
        enabled: bool = AUDIO_ENABLED,
        max_rooms: int = AUDIO_MAX_ROOMS,
        model: str = AUDIO_MODEL,
        segment_sec: int = AUDIO_SEGMENT_SEC,
    ) -> None:
        self._save_cb = save_cb
        self._enabled = enabled
        self._model = model
        self._segment_sec = segment_sec
        self._max_rooms = max_rooms
        self._sem = asyncio.Semaphore(max_rooms)
        self._tasks: dict[str, asyncio.Task] = {}
        self._transcribe_lock = asyncio.Lock()  # 全局串行转写，保护 CPU
        if not enabled:
            logger.info("话术采集已通过 AUDIO_ENABLED=0 关闭")
        else:
            logger.info(
                "话术采集就绪：模型=%s 段长=%ds 同时录制上限=%d",
                model, segment_sec, max_rooms,
            )

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def warmup(self) -> None:
        """预加载 Whisper 模型，避免首段转写卡顿。"""
        if not self._enabled:
            return
        if not _ensure_warmup_deps():
            self._enabled = False
            logger.warning("音频依赖缺失，话术采集已禁用: %r", _IMPORT_ERR)
            return
        loop = asyncio.get_event_loop()
        try:
            assert get_model is not None
            await loop.run_in_executor(None, get_model, self._model)
            logger.info("Whisper 模型预加载完成 => %s", self._model)
        except Exception:  # noqa: BLE001
            logger.exception("Whisper 预加载失败(话术仍会在首段时重试加载)")

    def start_room(self, room_num: str, live_url: str | None = None) -> None:
        if not self._enabled or not room_num:
            return
        existing = self._tasks.get(room_num)
        if existing and not existing.done():
            return  # 已在采集
        url = live_url or LIVE_URL_TEMPLATE.format(room=room_num)
        task = asyncio.create_task(
            self._run_room(room_num, url), name=f"audio-{room_num}"
        )
        self._tasks[room_num] = task
        # 任务自行结束(正常退出/取消)时从登记表移除，避免 stop 提前摘除导致 shutdown 漏等
        task.add_done_callback(
            lambda t, rn=room_num: self._tasks.pop(rn, None)
            if self._tasks.get(rn) is t
            else None
        )

    def stop_room(self, room_num: str) -> None:
        task = self._tasks.get(room_num)
        if task and not task.done():
            task.cancel()  # finally 会终止 ffmpeg、收尾 consumer；done_callback 负责摘除

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    # ------------------------------------------------------------------ #
    async def _run_room(self, room_num: str, live_url: str) -> None:
        async with self._sem:  # 受同时录制上限约束；满了就排队
            logger.info("话术采集启动 => %s", room_num)
            out_dir = tempfile.mkdtemp(prefix=f"lw_{room_num}_")
            pattern = os.path.join(out_dir, "chunk_%05d.wav")
            misses = 0
            ffmpeg = None
            consumer: asyncio.Task | None = None
            stop = asyncio.Event()
            try:
                while True:
                    if not _ensure_runtime_deps():
                        logger.warning("音频依赖缺失，话术[%s] 退出: %r", room_num, _IMPORT_ERR)
                        return
                    assert get_stream_url is not None
                    assert start_segment_recorder is not None
                    stream_url = await get_stream_url(live_url)
                    if not stream_url:
                        misses += 1
                        if misses >= _STREAM_RETRY_MAX:
                            logger.info("话术[%s] 连续取流失败，释放槽位退出", room_num)
                            return
                        await asyncio.sleep(10)
                        continue
                    misses = 0
                    stderr_log = os.path.join(out_dir, "ffmpeg.err")
                    ffmpeg = await start_segment_recorder(
                        stream_url, pattern, self._segment_sec, stderr_path=stderr_log
                    )
                    stop = asyncio.Event()
                    consumer = asyncio.create_task(
                        self._consume(out_dir, room_num, ffmpeg, stop)
                    )
                    await ffmpeg.wait()  # 正常会持续录；退出=断流/失效
                    logger.info("话术[%s] ffmpeg 退出，收尾后重连", room_num)
                    await consumer
                    consumer = None
                    ffmpeg = None
                    for f in Path(out_dir).glob("chunk_*.wav"):
                        f.unlink(missing_ok=True)
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                logger.info("话术采集停止 => %s", room_num)
                raise
            except Exception:  # noqa: BLE001
                logger.exception("话术采集异常 => %s", room_num)
            finally:
                # 关键：停止时确保 ffmpeg 进程与 consumer 任务都被终止，避免泄漏
                stop.set()
                await _terminate_proc(ffmpeg)
                if consumer is not None and not consumer.done():
                    consumer.cancel()
                    await asyncio.gather(consumer, return_exceptions=True)
                _cleanup_dir(out_dir)

    async def _consume(
        self, out_dir: str, room_num: str, ffmpeg_proc, stop: asyncio.Event
    ) -> None:
        processed: set[int] = set()
        loop = asyncio.get_event_loop()
        while not stop.is_set():
            wavs = sorted(Path(out_dir).glob("chunk_*.wav"), key=_seg_idx)
            done = ffmpeg_proc.returncode is not None
            ready = wavs if done else wavs[:-1]  # 段 N 在 N+1 出现后才算写完
            for wav in ready:
                if stop.is_set():
                    break
                idx = _seg_idx(wav)
                if idx in processed:
                    continue
                processed.add(idx)
                try:
                    async with self._transcribe_lock:  # 全局串行，保护 CPU
                        if stop.is_set():
                            break
                        assert transcribe_file is not None
                        text = await loop.run_in_executor(
                            None, transcribe_file, str(wav), self._model
                        )
                except Exception:  # noqa: BLE001 - 单段失败不影响后续
                    logger.exception("话术[%s] 段 %d 转写失败", room_num, idx)
                    text = ""
                start_sec = idx * self._segment_sec
                if text and not stop.is_set():
                    ts = int(time.time())
                    try:
                        self._save_cb(room_num, text, start_sec, ts)
                    except Exception:  # noqa: BLE001
                        logger.exception("话术[%s] 落库失败", room_num)
                    logger.info("话术[%s +%ds] %s", room_num, start_sec, text[:40])
                wav.unlink(missing_ok=True)
            if done and len(processed) >= len(wavs):
                break
            await asyncio.sleep(1)
