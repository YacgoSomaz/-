"""统一编排：同一批房间，同时跑「弹幕线 + 音频线 + 转写线」，互相解耦。

三条线在一个进程里各跑各的线程，Ctrl+C 一键全停：

  弹幕线  每房间一个 WorkerFetcher 长连（并发 WSS，握手后静默，风控面小），
          断线自动重连，落 multi_events.db（chat=评论区 / stat=直播数据 …）。
  音频线  recorder_rotate 串行轮转录段（低并发，规避音频并发风控），
          mp3 攒进 audio/pending/。
  转写线  transcribe_batch 常驻轮询，把 pending 里的 mp3 用 SenseVoice 转写入库。

设计取舍：音频必须低并发（串行轮转），弹幕可并发（握手后几乎不碰风控）。
两条采集线只共享房间列表，数据各写各库，导出时再按房间号关联（见 export.py）。

用法：
  python -m pipeline.orchestrator 123 456 789 [--seconds 60] [--stagger 3]
  Ctrl+C 优雅停止。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import threading
import time

from run_worker import WorkerFetcher, SqliteSink  # noqa: E402

from . import config
from . import recorder_rotate
from .sensevoice_engine import SenseVoiceEngine
from .transcribe_batch import process_once
from .transcript_store import TranscriptStore

RECONNECT_BACKOFF_SEC = 5
TRANSCRIBE_POLL_SEC = 10


def _danmu_room_loop(live_id: str, sink: SqliteSink, stop: threading.Event) -> None:
    """单房间弹幕长连，断线自动重连，直到 stop 置位。"""
    while not stop.is_set():
        try:
            fetcher = WorkerFetcher(live_id, sink)
            if not fetcher.ttwid or not fetcher.room_id:
                print(f"[弹幕] {live_id} 无 ttwid/room_id（未开播或风控），{RECONNECT_BACKOFF_SEC}s 后重试", flush=True)
                stop.wait(RECONNECT_BACKOFF_SEC)
                continue

            # 用看门狗线程在 stop 时主动断开阻塞的 start()
            def _watch() -> None:
                stop.wait()
                try:
                    fetcher.stop()
                except Exception:  # noqa: BLE001
                    pass

            threading.Thread(target=_watch, daemon=True).start()
            print(f"[弹幕] {live_id} room_id={fetcher.room_id} 已连接", flush=True)
            fetcher.start()  # 阻塞直到 WS 关闭
        except Exception as e:  # noqa: BLE001
            print(f"[弹幕] {live_id} 连接异常: {e!r}", flush=True)
        if not stop.is_set():
            stop.wait(RECONNECT_BACKOFF_SEC)


def _audio_line(live_ids: list[str], seconds: int, stop: threading.Event) -> None:
    """音频线：串行轮转录段，无限轮直到 stop。"""
    config.ensure_dirs()
    while not stop.is_set():
        for lid in live_ids:
            if stop.is_set():
                return
            try:
                out = config.next_segment_path(lid)
                from .audio_capture import record_segment
                r = record_segment(lid, out, seconds)
                tag = "OK" if r.ok else "--"
                print(f"[音频] [{tag}] {lid} {r.status}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[音频] {lid} 异常: {e!r}", flush=True)


def _transcribe_line(stop: threading.Event) -> None:
    """转写线：常驻轮询 pending，转写入库。"""
    print("[转写] 加载 SenseVoice 模型…", flush=True)
    engine = SenseVoiceEngine()
    store = TranscriptStore()
    print("[转写] 就绪。", flush=True)
    try:
        while not stop.is_set():
            try:
                n = process_once(engine, store)
                if n:
                    print(f"[转写] 本轮入库 {n} 条", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[转写] 异常: {e!r}", flush=True)
            stop.wait(TRANSCRIBE_POLL_SEC)
    finally:
        store.close()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("live_ids", nargs="+", help="抖音直播号 (web_rid)")
    ap.add_argument("--seconds", type=int, default=config.SEGMENT_SEC, help="每段录音时长")
    ap.add_argument("--stagger", type=float, default=3.0, help="弹幕房间错开启动秒数")
    args = ap.parse_args()

    config.ensure_dirs()
    sink = SqliteSink(str(config.EVENTS_DB))
    stop = threading.Event()
    threads: list[threading.Thread] = []

    print(f"[编排] {len(args.live_ids)} 房间 | 弹幕并发 + 音频串行({args.seconds}s/段) + 转写常驻", flush=True)

    # 弹幕线：每房间一个长连线程，错开启动
    for lid in args.live_ids:
        t = threading.Thread(target=_danmu_room_loop, args=(lid, sink, stop), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(args.stagger)

    # 音频线 + 转写线
    ta = threading.Thread(target=_audio_line, args=(args.live_ids, args.seconds, stop), daemon=True)
    tt = threading.Thread(target=_transcribe_line, args=(stop,), daemon=True)
    ta.start(); tt.start()
    threads += [ta, tt]

    try:
        while not stop.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[编排] 收到中断，正在停止各线…", flush=True)
        stop.set()

    for t in threads:
        t.join(timeout=10)

    conn = sqlite3.connect(str(config.EVENTS_DB))
    per_room = dict(conn.execute("SELECT live_id, COUNT(*) FROM events GROUP BY live_id").fetchall())
    conn.close()
    print("[编排] ==== 弹幕落库汇总 ====", flush=True)
    for lid in args.live_ids:
        print(f"  {lid}: events={per_room.get(lid, 0)}", flush=True)
    sink.close()
    print("[编排] 已停止。导出请跑: python -m pipeline.export", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
