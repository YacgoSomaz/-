"""无浏览器取流探测：从房间页 HTML / enter 接口里挖出直播拉流地址(flv/m3u8)。

目的：证明新后端路线不靠 Playwright 也能拿到拉流地址，喂给 ffmpeg 出 mp3。
用法：python probe_audio.py <live_id>
结果写入 UTF-8 文件 _audio_probe.txt（绕开 Windows 控制台 GBK）。
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parent / "vendor" / "DouyinLiveWebFetcher"
sys.path.insert(0, str(_VENDOR))
import os
os.chdir(_VENDOR)

from liveMan import DouyinLiveWebFetcher  # noqa: E402

OUT = Path(__file__).resolve().parent / "_audio_probe.txt"


def main() -> int:
    live_id = sys.argv[1] if len(sys.argv) > 1 else ""
    out = io.open(OUT, "w", encoding="utf-8")

    def w(s: str = "") -> None:
        out.write(s + "\n")

    f = DouyinLiveWebFetcher(live_id)
    w(f"live_id={live_id}")
    w(f"ttwid={'有' if f.ttwid else '空'}")

    # 拉房间页 HTML（room_id 属性走的同一个页面）
    url = f.live_url + live_id
    headers = {
        "User-Agent": f.user_agent,
        "cookie": f"ttwid={f.ttwid}; __ac_nonce=0123407cc00a9e438deb4",
    }
    resp = f.session.get(url, headers=headers)
    html = resp.text
    w(f"room页 status={resp.status_code} html长度={len(html)}")

    # 候选拉流地址正则（HTML 里 JSON 转义过，/ = /，需要兼容）
    patterns = {
        "flv": r'(https?:[^"\\]*?\.flv[^"\\]*)',
        "m3u8": r'(https?:[^"\\]*?\.m3u8[^"\\]*)',
        "flv_pull_url键": r'flv_pull_url["\\:{ ]+([^"\\]+\.flv[^"\\]*)',
        "hls_pull_url键": r'hls_pull_url["\\:{ ]+([^"\\]+\.m3u8[^"\\]*)',
    }
    # 处理 unicode 转义后的斜杠
    html_unescaped = html.encode().decode("unicode_escape", errors="ignore") if "\\u002F" in html or "\\u002f" in html else html

    found_any = False
    for name, pat in patterns.items():
        hits = set()
        for src in (html, html_unescaped):
            for m in re.findall(pat, src, flags=re.IGNORECASE):
                hits.add(m[:200])
        w(f"\n[{name}] 命中 {len(hits)} 条:")
        for h in list(hits)[:5]:
            found_any = True
            w(f"  {h}")

    if not found_any:
        # 看看 HTML 里是否提到 stream_url / pull_url 关键字（定位用）
        for kw in ("stream_url", "pull_url", "flv", "m3u8"):
            w(f'关键字 "{kw}" 出现次数: {html.count(kw)}')

    out.close()
    print(f"done -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
