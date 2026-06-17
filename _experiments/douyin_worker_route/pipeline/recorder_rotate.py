"""轮转录音器：对一批房间串行（或小并发）逐个录段，攒进 audio/pending/。

非实时设计——一次只拉 1~2 路流，录完一段轮到下一个，把瞬时并发压到最低，
规避之前 50 并发触发的风控。转写是另一个进程的事，与此解耦。

用法：
  python -m pipeline.recorder_rotate <id1> <id2> ... [--rounds N] [--concurrency 1]
  --rounds 0 表示无限轮转（24/7）。
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from .audio_capture import record_segment


def _record_one(live_id: str, seconds: int) -> str:
    out = config.next_segment_path(live_id)
    r = record_segment(live_id, out, seconds)
    if r.ok:
        vol = f"{r.mean_volume:.1f}dB" if r.mean_volume is not None else "?"
        return f"[OK] {live_id} -> {out.name} ({r.size}B, {vol}) {r.status}"
    return f"[--] {live_id} {r.status}"


def run(live_ids: list[str], rounds: int, concurrency: int, seconds: int) -> None:
    config.ensure_dirs()
    rnd = 0
    while rounds == 0 or rnd < rounds:
        rnd += 1
        print(f"=== 第 {rnd} 轮（{len(live_ids)} 房间，并发 {concurrency}）===", flush=True)
        t0 = time.time()
        if concurrency <= 1:
            for lid in live_ids:
                print("  " + _record_one(lid, seconds), flush=True)
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as ex:
                for line in ex.map(lambda l: _record_one(l, seconds), live_ids):
                    print("  " + line, flush=True)
        print(f"  本轮耗时 {time.time()-t0:.0f}s", flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("live_ids", nargs="+")
    ap.add_argument("--rounds", type=int, default=1, help="轮转轮数；0=无限")
    ap.add_argument("--concurrency", type=int, default=1, help="同时录制的房间数（建议1~2，控风控）")
    ap.add_argument("--seconds", type=int, default=config.SEGMENT_SEC)
    args = ap.parse_args()
    run(args.live_ids, args.rounds, max(1, args.concurrency), args.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
