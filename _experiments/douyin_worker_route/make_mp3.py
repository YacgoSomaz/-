"""音频跑通验证：无浏览器取流 -> 自带 ffmpeg 拉流 -> 导出 mp3。

链路：房间页HTML 正则出 m3u8 拉流地址 -> imageio_ffmpeg 拉 N 秒 -> 16k 单声道 mp3。
用法：python make_mp3.py <live_id> [秒数]
"""

from __future__ import annotations

import html as _html
import io
import os
import re
import subprocess
import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parent / "vendor" / "DouyinLiveWebFetcher"
sys.path.insert(0, str(_VENDOR))
os.chdir(_VENDOR)

import imageio_ffmpeg  # noqa: E402
from liveMan import DouyinLiveWebFetcher  # noqa: E402

LOG = Path(__file__).resolve().parent / "_mp3_result.txt"


def main() -> int:
    live_id = sys.argv[1] if len(sys.argv) > 1 else ""
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    out_mp3 = str(Path(__file__).resolve().parent / f"sample_{live_id}.mp3")
    log = io.open(LOG, "w", encoding="utf-8")

    def w(s: str = "") -> None:
        log.write(s + "\n")

    f = DouyinLiveWebFetcher(live_id)
    resp = f.session.get(
        f.live_url + live_id,
        headers={"User-Agent": f.user_agent, "cookie": f"ttwid={f.ttwid}; __ac_nonce=0123407cc00a9e438deb4"},
    )
    # 先还原 JSON 里的 unicode 转义(/=/  &=&  \/=/)，否则 URL 会在反斜杠处被截断
    html_text = (
        resp.text
        .replace("\\u002F", "/").replace("\\u002f", "/")
        .replace("\\u0026", "&").replace("\\/", "/")
    )

    # 取 m3u8，还原 HTML 转义。必须带签名参数(k=/sign=)，否则 CDN 返回 403
    cands = re.findall(r'https?://[^"\\\s]+?\.m3u8[^"\\\s]*', html_text, flags=re.IGNORECASE)
    cands = [_html.unescape(c) for c in cands]
    signed = [c for c in cands if ("k=" in c or "sign=" in c)]
    w(f"live_id={live_id} m3u8候选={len(cands)} 带签名={len(signed)}")
    pool = signed or cands
    # 偏好 /index.m3u8（完整播放列表）+ 中高清(hd/md)，回退第一条
    pick = (
        next((c for c in pool if "/index.m3u8" in c and ("_hd" in c or "_md" in c)), None)
        or next((c for c in pool if "/index.m3u8" in c), None)
        or next((c for c in pool if "_hd" in c or "_md" in c), None)
        or (pool[0] if pool else None)
    )
    if not pick:
        w("未取到 m3u8，无法导出音频")
        log.close()
        print("FAIL: no stream url")
        return 2
    w(f"选用流(len={len(pick)}): {pick}")

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y",
        "-headers", "Referer: https://live.douyin.com/\r\n",
        "-i", pick,
        "-t", str(seconds),
        "-vn", "-ar", "16000", "-ac", "1",
        "-acodec", "libmp3lame",
        out_mp3,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    size = os.path.getsize(out_mp3) if os.path.exists(out_mp3) else 0
    ok = proc.returncode == 0 and size > 1024
    w(f"ffmpeg rc={proc.returncode} 文件={out_mp3} 大小={size}字节")
    if not ok:
        w("ffmpeg stderr 末尾:")
        w((proc.stderr or "")[-800:])
    log.close()
    print(f"{'OK' if ok else 'FAIL'}: size={size} bytes -> {out_mp3}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
