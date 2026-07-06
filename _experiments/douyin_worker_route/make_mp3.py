"""音频跑通验证：项目自有取流器 -> ffmpeg 拉流 -> 导出 mp3。

用法：python make_mp3.py <live_id> [秒数]
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from pipeline.audio_capture import record_segment

LOG = Path(__file__).resolve().parent / "_mp3_result.txt"


def main() -> int:
    live_id = sys.argv[1] if len(sys.argv) > 1 else ""
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    out_mp3 = Path(__file__).resolve().parent / f"sample_{live_id}.mp3"

    with io.open(LOG, "w", encoding="utf-8") as log:
        log.write(f"live_id={live_id} seconds={seconds}\n")
        result = record_segment(live_id, out_mp3, seconds, normalize=False)
        log.write(f"ok={result.ok} status={result.status}\n")
        log.write(f"file={result.mp3_path or out_mp3} size={result.size}\n")
        if result.duration_sec is not None:
            log.write(f"duration={result.duration_sec:.3f}s volume={result.mean_volume}\n")

    print(f"{'OK' if result.ok else 'FAIL'}: {result.status} -> {out_mp3}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
