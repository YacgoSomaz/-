"""并发音频录制测试：N 个直播间各录 M 秒 mp3，观察并发下的成功率与质量。

并发设计：
  - 每房间独立线程：取流地址(HTML) -> ffmpeg 拉流 -> mp3
  - 错开各房间的 HTML 取址（--stagger 秒），避开主站风控面突发
  - ffmpeg 拉的是 CDN，风险低；真实成本在带宽（HLS 段含视频，-vn 只丢输出不省下载）

用法：python record_multi_audio.py <id1> <id2> ... --seconds 60 --stagger 2
结果写 UTF-8 文件 _audio_multi.txt，并对每个 mp3 验时长/音量。
"""

from __future__ import annotations

import argparse
import html as _html
import io
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_VENDOR = _HERE / "vendor" / "DouyinLiveWebFetcher"
sys.path.insert(0, str(_VENDOR))
os.chdir(_VENDOR)

import imageio_ffmpeg  # noqa: E402
from liveMan import DouyinLiveWebFetcher  # noqa: E402

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
OUT_LOG = _HERE / "_audio_multi.txt"


def extract_m3u8(html_raw: str) -> tuple[str | None, int]:
    """从房间页 HTML 提取带签名的完整 m3u8（先还原 unicode 转义避免截断）。"""
    text = (
        html_raw.replace("\\u002F", "/").replace("\\u002f", "/")
        .replace("\\u0026", "&").replace("\\/", "/")
    )
    cands = [_html.unescape(c) for c in re.findall(r'https?://[^"\\\s]+?\.m3u8[^"\\\s]*', text, re.I)]
    signed = [c for c in cands if ("k=" in c or "sign=" in c)]
    pool = signed or cands
    pick = (
        next((c for c in pool if "/index.m3u8" in c and ("_hd" in c or "_md" in c)), None)
        or next((c for c in pool if "/index.m3u8" in c), None)
        or next((c for c in pool if "_hd" in c or "_md" in c), None)
        or (pool[0] if pool else None)
    )
    return pick, len(cands)


def _probe(mp3: str) -> str:
    """用 ffmpeg 读 mp3 的时长与平均音量，确认非静音。"""
    try:
        p = subprocess.run(
            [FFMPEG, "-i", mp3, "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        err = p.stderr or ""
        dur = re.search(r"Duration: (\d+:\d+:\d+\.\d+)", err)
        vol = re.search(r"mean_volume: (-?[\d.]+) dB", err)
        return f"时长={dur.group(1) if dur else '?'} 均音量={vol.group(1)+'dB' if vol else '?'}"
    except Exception as e:  # noqa: BLE001
        return f"probe异常:{e!r}"


def _rec_room(live_id: str, seconds: int, status: dict, lock: threading.Lock) -> None:
    def _set(s: str) -> None:
        with lock:
            status[live_id] = s

    try:
        f = DouyinLiveWebFetcher(live_id)
        resp = f.session.get(
            f.live_url + live_id,
            headers={"User-Agent": f.user_agent, "cookie": f"ttwid={f.ttwid}; __ac_nonce=0123407cc00a9e438deb4"},
            timeout=15,
        )
        pick, ncand = extract_m3u8(resp.text)
    except Exception as e:  # noqa: BLE001
        _set(f"取址异常: {e!r}")
        return
    if not pick:
        _set(f"无流地址(候选{ncand}/疑未开播)")
        return

    out_mp3 = str(_HERE / f"sample_audio_{live_id}.mp3")
    cmd = [
        FFMPEG, "-y",
        "-headers", "Referer: https://live.douyin.com/\r\n",
        "-i", pick,
        "-t", str(seconds),
        "-vn", "-ar", "16000", "-ac", "1", "-acodec", "libmp3lame",
        out_mp3,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=seconds + 45,
        )
    except subprocess.TimeoutExpired:
        _set("ffmpeg超时")
        return
    size = os.path.getsize(out_mp3) if os.path.exists(out_mp3) else 0
    if proc.returncode == 0 and size > 1024:
        _set(f"OK 大小={size}B {_probe(out_mp3)}")
    else:
        tail = (proc.stderr or "")[-200:].replace("\n", " ")
        _set(f"失败 rc={proc.returncode} 大小={size}B …{tail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("live_ids", nargs="+")
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--stagger", type=float, default=2.0)
    args = ap.parse_args()

    status: dict[str, str] = {}
    lock = threading.Lock()
    threads: list[threading.Thread] = []

    t0 = time.time()
    for lid in args.live_ids:
        t = threading.Thread(target=_rec_room, args=(lid, args.seconds, status, lock))
        t.start()
        threads.append(t)
        time.sleep(args.stagger)  # 错开 HTML 取址
    for t in threads:
        t.join()
    elapsed = time.time() - t0

    log = io.open(OUT_LOG, "w", encoding="utf-8")
    log.write(f"=== {len(args.live_ids)} 房间并发录音 {args.seconds}s (总耗时 {elapsed:.0f}s) ===\n")
    ok = 0
    for lid in args.live_ids:
        st = status.get(lid, "未知")
        if st.startswith("OK"):
            ok += 1
        log.write(f"  {lid}: {st}\n")
    log.write(f"成功: {ok}/{len(args.live_ids)}\n")
    log.close()
    print(f"done: {ok}/{len(args.live_ids)} OK -> {OUT_LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
