"""批量转写：按房间扫描 audio/<房间号>/ 下的 mp3，未入库的用 SenseVoice 转写后写库。
转写后录音保留原地不删（方便人工回听、用导出文字反查录音），靠库里 mp3_name 判重去重。

录音命名 audio/<房间号>/<seq>.mp3（seq 为录制顺序号）。房间号取自父目录名；录制起始
时间按「文件修改时间 − 时长」回推。入库 mp3_name 用相对名 <房间号>/<seq>.mp3。

用法：
  python -m pipeline.transcribe_batch              # 单次消化完退出
  python -m pipeline.transcribe_batch --watch 10   # 常驻，每 10s 扫一次
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import config
from .audio_capture import probe_volume
from .sensevoice_engine import SenseVoiceEngine
from .transcript_store import TranscriptStore


def _audio_path(file_path: str) -> Path:
    p = Path(file_path)
    return p if p.is_absolute() else config.DATA_DIR / p


def process_once(engine: SenseVoiceEngine, store: TranscriptStore) -> int:
    """转写台账里已封口、未转写的录音段，返回本次处理条数。"""
    config.ensure_dirs()
    done = 0
    for seg in store.pending_sealed_segments():
        if not seg.file_path:
            continue
        mp3 = _audio_path(seg.file_path)
        mp3_name = seg.file_path.replace("\\", "/")
        if store.has(mp3_name):
            store.mark_transcribed(seg.id)
            continue
        if not mp3.exists():
            print(f"[MISS] {mp3_name}: 台账文件不存在，跳过本段", flush=True)
            store.mark_transcribed(seg.id)
            continue
        try:
            text = engine.transcribe(mp3)
        except Exception as e:  # noqa: BLE001
            # 解码/模型异常可能是临时故障。保留待转写状态，让下一轮自动重试；
            # 绝不能写空结果并永久标记完成，否则音频存在却永远补不回文字。
            print(f"[ERR] {mp3_name}: {e!r} -> 保留待转写，下轮重试", flush=True)
            continue
        dur, vol = probe_volume(str(mp3))
        duration = seg.duration_sec if seg.duration_sec is not None else dur
        segment_ts = int(seg.capture_start or time.time())
        store.add(
            seg.room_id,
            mp3_name,
            segment_ts,
            text,
            duration,
            vol,
            segment_id=seg.id,
            recording_status=seg.status,
            capture_start=seg.capture_start,
            capture_end=seg.capture_end,
        )
        preview = (text[:40] + "…") if len(text) > 40 else text
        print(f"[OK] {mp3_name} [{seg.status}, {len(text)}字] {preview}", flush=True)
        done += 1
    return done


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=float, default=0, help="常驻轮询间隔秒；0=单次")
    args = ap.parse_args()

    print("加载 SenseVoice 模型…", flush=True)
    engine = SenseVoiceEngine()
    store = TranscriptStore()
    print(f"就绪。库: {config.DB_PATH}", flush=True)

    try:
        if args.watch <= 0:
            n = process_once(engine, store)
            print(f"完成，本次转写 {n} 条。", flush=True)
        else:
            while True:
                n = process_once(engine, store)
                if n:
                    print(f"  （本轮 {n} 条，继续监听）", flush=True)
                time.sleep(args.watch)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
