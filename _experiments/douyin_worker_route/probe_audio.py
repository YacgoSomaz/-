"""音频取流探测：使用项目自有房间页取流器输出 m3u8 候选。

用法：python probe_audio.py <live_id>
结果写入 UTF-8 文件 _audio_probe.txt。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from pipeline.audio_capture import RiskControlChallenge, fetch_candidates
from pipeline.browser_cookies import cached_jar

OUT = Path(__file__).resolve().parent / "_audio_probe.txt"


def main() -> int:
    live_id = sys.argv[1] if len(sys.argv) > 1 else ""
    with io.open(OUT, "w", encoding="utf-8") as out:
        out.write(f"live_id={live_id}\n")
        out.write(f"cached_cookie={'有' if cached_jar() else '空'}\n")
        try:
            cands, raw_count = fetch_candidates(live_id)
        except RiskControlChallenge as exc:
            out.write(f"风险验证页: {exc}\n")
            print(f"challenge -> {OUT}")
            return 2
        except Exception as exc:  # noqa: BLE001
            out.write(f"取址异常: {exc!r}\n")
            print(f"error -> {OUT}")
            return 1

        out.write(f"m3u8 原始命中={raw_count} 有效候选={len(cands)}\n")
        for idx, url in enumerate(cands[:10], start=1):
            out.write(f"{idx}. {url}\n")

    print(f"done -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
