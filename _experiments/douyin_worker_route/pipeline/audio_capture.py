"""取流 + 录段（无浏览器）。

从房间页 HTML 提取带签名的 m3u8 候选，ffmpeg 拉流录音。核心是 `record_room_muxer`：
单房间单 ffmpeg，用 segment muxer 连续封口定长 mp3，**不挂 loudnorm**（loudnorm 的
前瞻会卡住输出 PTS 导致起段填不满甚至 0 字节——已实测坐实，电平归一改到转写时再做）。
封口权威是 ffmpeg 写的 segment_list csv；段一出现在 csv 即已封口。看门狗在 ffmpeg
退出（签名过期/断流）时刷新签名重启，并把残段(partial)、断档(gap)全部记进台账，
做到「一段不丢、时间对得上」。
"""

from __future__ import annotations

import html as _html
import os
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
from pathlib import Path
from typing import Callable

import imageio_ffmpeg

from . import config
from .runtime_health import classify_room_page

# 把 vendored DouyinLiveWebFetcher 加入 import 路径
_VENDOR = config.ROUTE_DIR / "vendor" / "DouyinLiveWebFetcher"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


class RiskControlChallenge(RuntimeError):
    """Room page returned a platform verification wall instead of live data."""


def rank_m3u8(html_raw: str) -> tuple[list[str], int]:
    """提取带签名的 m3u8，按偏好排序去重。返回 (候选列表, 原始命中数)。"""
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
        return 0 if (is_index and is_hdmd) else 1 if is_index else 2 if is_hdmd else 3

    seen: set[str] = set()
    ordered: list[str] = []
    for url in sorted(pool, key=_score):
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered, len(cands)


def fetch_candidates(live_id: str) -> tuple[list[str], int]:
    """取房间页 HTML 并解析出流地址候选。异常上抛。"""
    from liveMan import DouyinLiveWebFetcher

    from . import browser_cookies
    from .fingerprint import PAGE_HEADERS

    f = DouyinLiveWebFetcher(live_id)
    headers = dict(PAGE_HEADERS)
    headers["Referer"] = f.live_url
    headers["cookie"] = browser_cookies.cached_cookie_header()
    resp = f.session.get(
        f.live_url + live_id,
        headers=headers,
        timeout=15,
    )
    if classify_room_page(resp.text) == "challenge":
        raise RiskControlChallenge("抖音房间页要求安全验证")
    return rank_m3u8(resp.text)


def probe_volume(mp3_path: str) -> tuple[float | None, float | None]:
    """读 mp3 的时长(秒)与平均音量(dB)，用于入库与质量观测。"""
    try:
        p = subprocess.run(
            [_FFMPEG, "-i", mp3_path, "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            creationflags=_NO_WINDOW,
        )
        err = p.stderr or ""
        dur_m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", err)
        vol_m = re.search(r"mean_volume: (-?[\d.]+) dB", err)
        dur = (int(dur_m.group(1)) * 3600 + int(dur_m.group(2)) * 60 + float(dur_m.group(3))) if dur_m else None
        vol = float(vol_m.group(1)) if vol_m else None
        return dur, vol
    except Exception:  # noqa: BLE001
        return None, None


@dataclass(frozen=True)
class RecordResult:
    ok: bool
    status: str
    mp3_path: str | None = None
    size: int = 0
    duration_sec: float | None = None
    mean_volume: float | None = None
    tries: int = 0


def record_segment(live_id: str, out_path: Path, seconds: int, normalize: bool = True) -> RecordResult:
    """录一段定长 mp3。取址失败/未开播返回 ok=False，并带可读 status。"""
    try:
        cands, ncand = fetch_candidates(live_id)
    except Exception as e:  # noqa: BLE001
        return RecordResult(False, f"取址异常: {e!r}")
    if not cands:
        return RecordResult(False, f"无流地址(候选{ncand}/疑未开播)")

    out_str = str(out_path)
    # 先写到 .part 临时文件，录完再原子改名为最终 .mp3。
    # 这样并发轮询 pending/*.mp3 的转写线永远看不到半成品（避免 ffmpeg 读到写一半的文件）。
    tmp_path = out_path.with_name(out_path.name + ".part")
    tmp_str = str(tmp_path)
    last = "未尝试"
    tried = 0
    for pick in cands[: config.MAX_STREAM_TRIES]:
        tried += 1
        cmd = [
            _FFMPEG, "-y",
            "-headers", config.RECORD_REFERER,
            "-i", pick,
            "-t", str(seconds),
            "-vn",
        ]
        if normalize:
            cmd += ["-af", config.LOUDNORM_FILTER]
        # 输出扩展名是 .part，ffmpeg 无法据此推断封装，必须 -f mp3 显式指定。
        cmd += ["-ar", "16000", "-ac", "1", "-acodec", "libmp3lame", "-f", "mp3", tmp_str]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=seconds + 45, creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            return RecordResult(False, f"ffmpeg超时(第{tried}次)", tries=tried)
        size = os.path.getsize(tmp_str) if os.path.exists(tmp_str) else 0
        if proc.returncode == 0 and size > 1024:
            dur, vol = probe_volume(tmp_str)
            os.replace(tmp_str, out_str)  # 原子改名：此刻 .mp3 才出现在 pending
            note = f"(换流第{tried}次)" if tried > 1 else ""
            return RecordResult(True, f"OK{note}", out_str, size, dur, vol, tried)
        tail = (proc.stderr or "")[-160:].replace("\n", " ")
        last = f"rc={proc.returncode} size={size} …{tail}"
        if not re.search(r"40[34]|Not Found|Forbidden|Server returned", tail):
            break
    if os.path.exists(tmp_str):
        try:
            os.remove(tmp_str)
        except OSError:
            pass
    return RecordResult(False, f"失败(尝试{tried}条) {last}", tries=tried)


def _parse_csv_seg(line: str) -> tuple[str, float, float] | None:
    """解析 segment_list csv 行：`<路径>,<start>,<end>`（路径无逗号，按右侧两逗号切）。"""
    line = line.strip()
    if not line:
        return None
    parts = line.rsplit(",", 2)
    if len(parts) != 3:
        return None
    name, start_s, end_s = parts
    try:
        return name, float(start_s), float(end_s)
    except ValueError:
        return None


def _read_sealed(csv_path: Path, seen: set[int]) -> list[tuple[int, str, float, float]]:
    """读 csv，返回尚未处理过的封口段 (seq, 文件名, start_pts, end_pts)。"""
    if not csv_path.exists():
        return []
    try:
        rows = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[tuple[int, str, float, float]] = []
    for line in rows:
        parsed = _parse_csv_seg(line)
        if parsed is None:
            continue
        name, start_pts, end_pts = parsed
        seq = config.parse_seq(Path(name).stem)
        if seq is None or seq in seen:
            continue
        out.append((seq, name, start_pts, end_pts))
    return out


def record_room_muxer(
    live_id: str,
    room_dir: Path,
    start_seq: int,
    should_stop: Callable[[], bool],
    on_seal: Callable[..., None],
    on_partial: Callable[..., None],
    on_gap: Callable[..., None],
    on_spawn: Callable[..., None] | None = None,
    can_fetch: Callable[[], bool] | None = None,
    on_risk_control: Callable[[str], None] | None = None,
) -> RecordResult:
    """单房间「零丢失」连续录音：一条常驻 ffmpeg + segment muxer，看门狗负责重启。

    关键设计（均已实测/讨论坐实）：
      * 单 ffmpeg 连续拉流，segment muxer 每 SEGMENT_SEC 封口一段，全程恒有 1 个进程在
        消费流——除重启缝隙外不丢数据。**不挂 loudnorm**（其前瞻会卡住输出 PTS）。
      * 文件名只放连续序号 seqNNNNN.mp3；时间全进台账。`-segment_start_number` 保证跨重启
        序号连续不覆盖。
      * 封口权威 = ffmpeg 写的 segment_list csv：段出现在 csv 即已封口（→on_seal）。当前正在
        写、尚未入 csv 的最大序号文件 = 残段(partial)，ffmpeg 退出时探测后记账，**绝不删**。
      * 看门狗：ffmpeg 退出→刷新签名重启；覆盖断档记 gap（capture 末→重启首段）。
      * 禁止同房间双拉：任一时刻只有一条 ffmpeg。

    回调约定（manager 转调 TranscriptStore）：
      on_seal(seq, file_path, capture_start, capture_end, duration_sec, file_size)
      on_partial(seq, file_path, capture_start, capture_end, duration_sec, file_size)
      on_gap(capture_start, capture_end, reason)
      on_spawn(seq, attempt, capture_start)   # 可选，供状态/心跳

    返回：should_stop 触发即正常退出 ok=True；本函数自带退避重试，仅在被要求停止时返回。
    """
    room_dir.mkdir(parents=True, exist_ok=True)
    csv_path = room_dir / config.SEGMENT_LIST_NAME

    next_seq = start_seq
    produced = 0
    attempt = 0
    backoff = config.MUXER_RESPAWN_BACKOFF_SEC
    last_coverage_end: float | None = None  # 最近一段 capture_end（墙钟），用于算 gap

    while not should_stop():
        if can_fetch is not None and not can_fetch():
            stop_wait(should_stop, config.MUXER_NO_CANDIDATES_BACKOFF_SEC)
            continue
        attempt += 1
        try:
            cands, ncand = fetch_candidates(live_id)
        except RiskControlChallenge as exc:
            if on_risk_control is not None:
                try:
                    on_risk_control(str(exc))
                except Exception:  # noqa: BLE001
                    pass
            stop_wait(should_stop, config.MUXER_NO_CANDIDATES_BACKOFF_SEC)
            continue
        except Exception as e:  # noqa: BLE001
            if should_stop():
                break
            stop_wait(should_stop, config.MUXER_NO_CANDIDATES_BACKOFF_SEC)
            continue
        if not cands:
            if should_stop():
                break
            # 多半下播/风控，长退避，别高频打房间页。期间 gap 持续累积，待恢复后一次性记账。
            stop_wait(should_stop, config.MUXER_NO_CANDIDATES_BACKOFF_SEC)
            continue

        url = cands[0]
        spawn_seq = next_seq
        spawn_wall = time.time()

        # 覆盖断档：上一段 capture 末到本次重启之间的空窗（电梯失联等），记 gap。
        if last_coverage_end is not None and (spawn_wall - last_coverage_end) >= config.GAP_MIN_SEC:
            try:
                on_gap(capture_start=last_coverage_end, capture_end=spawn_wall,
                       reason=f"录制中断重连(attempt={attempt})")
            except Exception:  # noqa: BLE001
                pass

        cmd = [
            _FFMPEG, "-y",
            "-headers", config.RECORD_REFERER,
            "-i", url,
            "-vn",
            "-ar", "16000", "-ac", "1", "-acodec", "libmp3lame",
            "-f", "segment",
            "-segment_time", str(config.SEGMENT_SEC),
            "-segment_start_number", str(spawn_seq),
            "-reset_timestamps", "1",
            "-segment_list", str(csv_path),
            "-segment_list_type", "csv",
            str(room_dir / config.SEGMENT_FILENAME),
        ]
        try:
            csv_path.unlink(missing_ok=True)  # 每次 spawn 用全新 csv，避免读到上一轮残留
        except OSError:
            pass

        if on_spawn is not None:
            try:
                on_spawn(seq=spawn_seq, attempt=attempt, capture_start=spawn_wall)
            except Exception:  # noqa: BLE001
                pass

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )
        except Exception:  # noqa: BLE001
            if should_stop():
                break
            stop_wait(should_stop, backoff)
            backoff = min(backoff * 2, config.MUXER_MAX_BACKOFF_SEC)
            continue

        seen: set[int] = set()
        last_seal_end_pts = 0.0       # 本 spawn 最近封口段的 end_pts（残段起点）
        last_progress_wall = spawn_wall
        last_partial_size = -1
        stopped_requested = False

        # ---- 进程存活期：轮询 csv 封口段 + 看门狗 ----
        while True:
            if should_stop():
                stopped_requested = True
                break
            rc = proc.poll()
            for seq, name, start_pts, end_pts in _read_sealed(csv_path, seen):
                seen.add(seq)
                cap_start = spawn_wall + start_pts
                cap_end = spawn_wall + end_pts
                last_seal_end_pts = max(last_seal_end_pts, end_pts)
                last_coverage_end = cap_end
                next_seq = max(next_seq, seq + 1)
                produced += 1
                last_progress_wall = time.time()
                fp = room_dir / (config.SEGMENT_FILENAME % seq)
                size = fp.stat().st_size if fp.exists() else 0
                try:
                    on_seal(seq=seq, file_path=str(fp), capture_start=cap_start,
                            capture_end=cap_end, duration_sec=end_pts - start_pts, file_size=size)
                except Exception:  # noqa: BLE001
                    pass
            if rc is not None:
                break
            # 看门狗：当前段（spawn_seq + 已封口数）是否还在增长？长时间不增长=签名失效，杀掉重启。
            cur_seq = spawn_seq + len(seen)
            cur_fp = room_dir / (config.SEGMENT_FILENAME % cur_seq)
            cur_size = cur_fp.stat().st_size if cur_fp.exists() else 0
            if cur_size != last_partial_size:
                last_partial_size = cur_size
                last_progress_wall = time.time()
            if (time.time() - last_progress_wall) >= config.MUXER_NO_DATA_TIMEOUT_SEC:
                _terminate(proc)
                break
            stop_wait(should_stop, config.MUXER_POLL_SEC)

        if stopped_requested:
            _terminate(proc)
        else:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _terminate(proc)

        # ---- 退出收尾：补读最后封口段 + 残段记账 ----
        ran_sec = time.time() - spawn_wall
        for seq, name, start_pts, end_pts in _read_sealed(csv_path, seen):
            seen.add(seq)
            cap_start = spawn_wall + start_pts
            cap_end = spawn_wall + end_pts
            last_seal_end_pts = max(last_seal_end_pts, end_pts)
            last_coverage_end = cap_end
            next_seq = max(next_seq, seq + 1)
            produced += 1
            fp = room_dir / (config.SEGMENT_FILENAME % seq)
            size = fp.stat().st_size if fp.exists() else 0
            try:
                on_seal(seq=seq, file_path=str(fp), capture_start=cap_start,
                        capture_end=cap_end, duration_sec=end_pts - start_pts, file_size=size)
            except Exception:  # noqa: BLE001
                pass

        # 残段：当前未入 csv 的最大序号文件。ffmpeg 被杀时正在写的那一段，绝不删。
        partial_seq = spawn_seq + len(seen)
        partial_fp = room_dir / (config.SEGMENT_FILENAME % partial_seq)
        if partial_fp.exists():
            size = partial_fp.stat().st_size
            dur, _vol = probe_volume(str(partial_fp)) if size > 0 else (None, None)
            cap_start = spawn_wall + last_seal_end_pts
            cap_end = cap_start + dur if dur else time.time()
            last_coverage_end = cap_end
            next_seq = max(next_seq, partial_seq + 1)
            try:
                on_partial(seq=partial_seq, file_path=str(partial_fp), capture_start=cap_start,
                           capture_end=cap_end, duration_sec=dur,
                           file_size=size)
            except Exception:  # noqa: BLE001
                pass

        if should_stop():
            break

        # 退避：本 spawn 几乎没产出且存活极短 → 瞬时失败，升级退避；否则回到基准。
        if len(seen) == 0 and ran_sec < config.MUXER_INSTANT_FAIL_SEC:
            stop_wait(should_stop, backoff)
            backoff = min(backoff * 2, config.MUXER_MAX_BACKOFF_SEC)
        else:
            backoff = config.MUXER_RESPAWN_BACKOFF_SEC
            stop_wait(should_stop, config.MUXER_RESPAWN_BACKOFF_SEC
                      + random.uniform(0, config.MUXER_RESPAWN_JITTER_SEC))

    return RecordResult(True, f"已停止(本轮{produced}段)")


def _terminate(proc: subprocess.Popen) -> None:
    """优雅终止 ffmpeg：terminate→等 5s→kill。"""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


def stop_wait(should_stop: Callable[[], bool], seconds: float) -> None:
    """可被 should_stop 提前打断的分片 sleep（每 0.5s 检查一次）。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if should_stop():
            return
        time.sleep(min(0.5, deadline - time.time()))
