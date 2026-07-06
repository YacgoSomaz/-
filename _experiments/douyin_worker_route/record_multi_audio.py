"""并发音频录制测试：N 个直播间各录 M 秒 mp3，观察成功率与质量。

用法：python record_multi_audio.py <id1> <id2> ... --seconds 60 --stagger 2
结果写 UTF-8 文件 _audio_multi.txt。
"""

from __future__ import annotations

import argparse
import io
import threading
import time
from pathlib import Path

from pipeline.audio_capture import record_segment

_HERE = Path(__file__).resolve().parent
OUT_LOG = _HERE / "_audio_multi.txt"


def _rec_room(live_id: str, seconds: int, status: dict[str, str], lock: threading.Lock, normalize: bool) -> None:
    def _set(value: str) -> None:
        with lock:
            status[live_id] = value

    out_mp3 = _HERE / f"sample_audio_{live_id}.mp3"
    result = record_segment(live_id, out_mp3, seconds, normalize=normalize)
    if result.ok:
        dur = f" 时长={result.duration_sec:.1f}s" if result.duration_sec is not None else ""
        vol = f" 均音量={result.mean_volume:.1f}dB" if result.mean_volume is not None else ""
        _set(f"OK 大小={result.size}B{dur}{vol}")
    else:
        _set(result.status)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("live_ids", nargs="+")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--stagger", type=float, default=2.0)
    parser.add_argument("--raw", action="store_true", help="录原始电平，不做响度归一化")
    args = parser.parse_args()

    status: dict[str, str] = {}
    lock = threading.Lock()
    threads: list[threading.Thread] = []

    started = time.time()
    for live_id in args.live_ids:
        thread = threading.Thread(
            target=_rec_room,
            args=(live_id, args.seconds, status, lock, not args.raw),
        )
        thread.start()
        threads.append(thread)
        time.sleep(args.stagger)
    for thread in threads:
        thread.join()

    elapsed = time.time() - started
    ok = sum(1 for value in status.values() if value.startswith("OK"))
    with io.open(OUT_LOG, "w", encoding="utf-8") as log:
        log.write(f"=== {len(args.live_ids)} 房间并发录音 {args.seconds}s (总耗时 {elapsed:.0f}s) ===\n")
        for live_id in args.live_ids:
            log.write(f"  {live_id}: {status.get(live_id, '未知')}\n")
        log.write(f"成功: {ok}/{len(args.live_ids)}\n")

    print(f"done: {ok}/{len(args.live_ids)} OK -> {OUT_LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
