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

# 单房间最多尝试的备用流地址条数（404/403 时换下一条）
MAX_STREAM_TRIES = 4

# 响度归一化（EBU R128）：统一各房间电平，避免有的录音明显偏小。
# I=目标综合响度(LUFS)，TP=真峰值上限(dBTP)，LRA=响度范围。
LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"


def rank_m3u8(html_raw: str) -> tuple[list[str], int]:
    """从房间页 HTML 提取带签名的 m3u8，按偏好排序返回去重候选列表。

    返回 (ordered_urls, raw_count)。ordered_urls[0] 为首选，后续作为
    404/403 时的备用流地址（同一房间通常含数十条等效候选）。
    """
    text = (
        html_raw.replace("\\u002F", "/").replace("\\u002f", "/")
        .replace("\\u0026", "&").replace("\\/", "/")
    )
    cands = [_html.unescape(c) for c in re.findall(r'https?://[^"\\\s]+?\.m3u8[^"\\\s]*', text, re.I)]
    signed = [c for c in cands if ("k=" in c or "sign=" in c)]
    pool = signed or cands

    def _score(url: str) -> int:
        is_index = "/index.m3u8" in url
        is_hdmd = ("_hd" in url) or ("_md" in url)
        if is_index and is_hdmd:
            return 0
        if is_index:
            return 1
        if is_hdmd:
            return 2
        return 3

    seen: set[str] = set()
    ordered: list[str] = []
    for url in sorted(pool, key=_score):
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered, len(cands)


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


def _rec_room(live_id: str, seconds: int, status: dict, lock: threading.Lock, normalize: bool = True) -> None:
    def _set(s: str) -> None:
        with lock:
            status[live_id] = s

    try:
        f = DouyinLiveWebFetcher(live_id)
        headers = dict(f.headers)
        headers["Referer"] = f.live_url
        headers["cookie"] = f"ttwid={f.ttwid}; __ac_nonce=0123407cc00a9e438deb4"
        resp = f.session.get(
            f.live_url + live_id,
            headers=headers,
            timeout=15,
        )
        cands, ncand = rank_m3u8(resp.text)
    except Exception as e:  # noqa: BLE001
        _set(f"取址异常: {e!r}")
        return
    if not cands:
        _set(f"无流地址(候选{ncand}/疑未开播)")
        return

    out_mp3 = str(_HERE / f"sample_audio_{live_id}.mp3")
    # 取址成功但 CDN 可能返回 404/403（流地址过期/节点拒绝）：依次换备用候选重试。
    tried = 0
    last = "未尝试"
    for pick in cands[:MAX_STREAM_TRIES]:
        tried += 1
        cmd = [
            FFMPEG, "-y",
            "-headers", "Referer: https://live.douyin.com/\r\n",
            "-i", pick,
            "-t", str(seconds),
            "-vn",
        ]
        if normalize:
            cmd += ["-af", LOUDNORM_FILTER]
        cmd += ["-ar", "16000", "-ac", "1", "-acodec", "libmp3lame", out_mp3]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=seconds + 45,
            )
        except subprocess.TimeoutExpired:
            _set(f"ffmpeg超时(第{tried}次)")
            return
        size = os.path.getsize(out_mp3) if os.path.exists(out_mp3) else 0
        if proc.returncode == 0 and size > 1024:
            note = f"(换流第{tried}次成功)" if tried > 1 else ""
            _set(f"OK 大小={size}B {_probe(out_mp3)} {note}".rstrip())
            return
        tail = (proc.stderr or "")[-160:].replace("\n", " ")
        last = f"rc={proc.returncode} 大小={size}B …{tail}"
        # 仅在像 404/403 这类拒绝时才换流；其它错误（如无候选）已无意义。
        if not re.search(r"40[34]|Not Found|Forbidden|Server returned", tail):
            break
    _set(f"失败(尝试{tried}/{min(len(cands), MAX_STREAM_TRIES)}条) {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("live_ids", nargs="+")
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--stagger", type=float, default=2.0)
    ap.add_argument("--raw", action="store_true", help="录原始电平，不做响度归一化")
    args = ap.parse_args()
    normalize = not args.raw

    status: dict[str, str] = {}
    lock = threading.Lock()
    threads: list[threading.Thread] = []

    t0 = time.time()
    for lid in args.live_ids:
        t = threading.Thread(target=_rec_room, args=(lid, args.seconds, status, lock, normalize))
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
