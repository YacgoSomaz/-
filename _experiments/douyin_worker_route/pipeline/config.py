"""管线统一配置与路径。

目录约定（都在 worker 路线目录下，便于 .gitignore 整目录忽略真实数据）：
  audio/<房间号>/  每个直播间一个文件夹，录音按录制顺序命名 1.mp3/2.mp3…，
                   转写后保留原地不删，方便人工回听、用导出文字反查录音
  audio/failed/    转写失败隔离（避免每轮反复重试卡队列）
  transcripts.db   转写结果库
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# 录音文件名 seqNNNNN.mp3 的序号解析（segment muxer 用 -segment_start_number 连续编号）
_SEQ_RE = re.compile(r"(?:seq)?0*(\d+)$", re.I)

# douyin_worker_route/（程序代码目录；vendor 的 sign.js/a_bogus.js 等只读资源仍按它定位）
ROUTE_DIR = Path(__file__).resolve().parent.parent

# ---------- 程序文件 / 用户数据 / 只读资源 三分离（打包用，开发态行为不变） ----------
# 打包后由启动器注入两个环境变量，把「会被写入的用户数据」与「只读模型资源」从安装目录里分出去：
#   LIVEWATCH_DATA_DIR     → %LOCALAPPDATA%\LiveWatch\data   （cookie、rooms.json、库、audio、exports、日志）
#   LIVEWATCH_RESOURCE_DIR → <安装目录>\models                （SenseVoice / 3D-Speaker 模型）
# 两个变量都未设置时（开发态），全部回退到原来的相对路径，行为与改动前完全一致。
_DATA_ENV = os.environ.get("LIVEWATCH_DATA_DIR")
_RES_ENV = os.environ.get("LIVEWATCH_RESOURCE_DIR")

# 用户数据根
DATA_DIR = Path(_DATA_ENV).expanduser().resolve() if _DATA_ENV else ROUTE_DIR

# SenseVoice ONNX 模型（开发态复用 asr_bench 下载；打包态用安装目录 models/sensevoice_onnx）
if _RES_ENV:
    RESOURCE_DIR = Path(_RES_ENV).expanduser().resolve()
    MODEL_DIR = RESOURCE_DIR / "sensevoice_onnx"
    SPEAKER_MODEL = RESOURCE_DIR / "speaker" / "3dspeaker_eres2net_zh_16k.onnx"
else:
    RESOURCE_DIR = ROUTE_DIR.parent
    MODEL_DIR = ROUTE_DIR.parent / "asr_bench" / "sensevoice_onnx"
    SPEAKER_MODEL = ROUTE_DIR.parent / "speaker_change_analysis" / "models" / "3dspeaker_eres2net_zh_16k.onnx"
MODEL_ONNX = MODEL_DIR / "model.int8.onnx"
MODEL_TOKENS = MODEL_DIR / "tokens.txt"

# 音频与库（用户数据，落 DATA_DIR）
AUDIO_DIR = DATA_DIR / "audio"
FAILED_DIR = AUDIO_DIR / "failed"
DB_PATH = DATA_DIR / "transcripts.db"

# audio/ 下的保留目录名（非房间号），房间目录扫描时排除
RESERVED_AUDIO_SUBDIRS = {"failed", "pending", "done"}

# 弹幕/评论/直播数据库（由 run_multi.py 的 WorkerFetcher 写入）
EVENTS_DB = DATA_DIR / "multi_events.db"

# 导出目录（用户数据）
EXPORT_DIR = DATA_DIR / "exports"

# 信任 cookie 缓存、房间清单、日志（用户数据）
COOKIE_CACHE = DATA_DIR / "browser_cookies.json"
ROOMS_JSON = DATA_DIR / "rooms.json"
LOG_DIR = DATA_DIR / "logs"

# 离线声纹分析结果（生成型用户数据，落 DATA_DIR）。声纹分析独立运行，导出时只读 CSV，不影响监听/录音线程。
# 开发态保持原 speaker_change_analysis 目录，避免动到既有离线分析产物。
SPEAKER_ANALYSIS_DIR = (DATA_DIR / "speaker_analysis") if _DATA_ENV else (ROUTE_DIR.parent / "speaker_change_analysis")
SPEAKER_LABELS_CSV = SPEAKER_ANALYSIS_DIR / "speaker_labels.csv"
SPEAKER_ANALYSIS_DB = SPEAKER_ANALYSIS_DIR / "speaker_analysis.db"
SPEAKER_DB_PATH = DATA_DIR / "speaker_labels.db"
SPEAKER_DELAY_SEC = 120
SPEAKER_POLL_SEC = 120
SPEAKER_BATCH_SIZE = 3
SPEAKER_MATCH_THRESHOLD = 0.70
SPEAKER_MERGE_THRESHOLD = 0.70
SPEAKER_PROFILE_UPDATE_THRESHOLD = 0.80
SPEAKER_NEW_CONFIRM_SEGMENTS = 3

# 录音参数
SEGMENT_SEC = 60            # 每段录制时长
TRANSCRIBE_MIN_FILE_AGE_SEC = 20  # 跳过刚生成/可能仍在写入的音频文件
TRANSCRIBE_MIN_FILE_SIZE = 1024   # 小于此字节数的视为空/残段，隔离不转写
# 旧的「靠 mtime 静默判封口」机制已弃用：现在封口权威是 segment_list csv，
# 段一旦出现在 csv 即已封口，转写直接读 recording_timeline 的待转写段，无需再靠静默判断。
TRANSCRIBE_SEALED_QUIET_SEC = 90  # 保留常量供旧路径兼容，新链路不依赖
ASR_THREADS = 4            # SenseVoice 推理线程
RECORD_REFERER = "Referer: https://live.douyin.com/\r\n"
LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"
MAX_STREAM_TRIES = 4       # 404/403 时换备用流地址的最大尝试数

# ---------- segment muxer（单房间单 ffmpeg 连续录、零丢失）参数 ----------
# 文件名只放连续序号（seqNNNNN.mp3），时间全部进台账 recording_timeline。
# 注意：-strftime 1 会让 %d 变成「月内日」，与连续序号互斥，故文件名不含时间。
SEGMENT_FILENAME = "seq%05d.mp3"   # ffmpeg -segment 输出模板
SEGMENT_LIST_NAME = "segments.csv"  # 每个房间目录内的封口权威清单（每次 spawn 覆盖重写）
MUXER_POLL_SEC = 2.0               # 轮询 segment_list 探测新封口段的间隔
MUXER_RESPAWN_BACKOFF_SEC = 3.0    # ffmpeg 退出后重启基准退避
MUXER_RESPAWN_JITTER_SEC = 2.0     # 重启退避抖动上限
MUXER_NO_CANDIDATES_BACKOFF_SEC = 30.0   # 取址为空（多半下播/风控）时退避
MUXER_NO_DATA_TIMEOUT_SEC = 120.0  # 必须 > SEGMENT_SEC；segment muxer 当前段常到封口才写入，过早会误杀
MUXER_INSTANT_FAIL_SEC = 8.0       # ffmpeg 启动后存活不足此秒且 0 段→视为瞬时失败，升级退避
MUXER_MAX_BACKOFF_SEC = 60.0       # 退避上限
GAP_MIN_SEC = 2.0                  # 覆盖断档小于此秒数不记 gap（重启缝隙忽略不计）


def ensure_dirs() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SPEAKER_ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def parse_seq(stem: str) -> int | None:
    """从文件名主干解析序号：兼容 `seq00007` 与裸数字 `7`。无法解析返回 None。"""
    m = _SEQ_RE.fullmatch(stem.strip())
    return int(m.group(1)) if m else None


def max_segment_number(rid: str) -> int:
    """房间目录里现存最大录音序号（无文件返回 0）。文件系统侧的 seq 兜底。"""
    room_dir = AUDIO_DIR / str(rid)
    if not room_dir.exists():
        return 0
    max_seq = 0
    for p in room_dir.glob("*.mp3"):
        seq = parse_seq(p.stem)
        if seq is not None:
            max_seq = max(max_seq, seq)
    return max_seq


def next_segment_path(rid: str) -> Path:
    """为房间分配下一个顺序录音路径 audio/<房间号>/seqNNNNN.mp3。

    seq = 现有最大序号 + 1（对空洞稳健：删了中间段也不复用旧号，避免覆盖）。
    一个直播间一个文件夹、录音按录制顺序编号，便于人工回听与按导出文字定位录音。
    """
    room_dir = AUDIO_DIR / str(rid)
    room_dir.mkdir(parents=True, exist_ok=True)
    return room_dir / (SEGMENT_FILENAME % (max_segment_number(rid) + 1))


def next_segment_number(rid: str) -> int:
    """返回房间下一个可用的录音序号（文件系统侧）。连续分片 ffmpeg 的兜底起号。"""
    room_dir = AUDIO_DIR / str(rid)
    room_dir.mkdir(parents=True, exist_ok=True)
    return max_segment_number(rid) + 1


def room_audio_dirs() -> list[Path]:
    """audio/ 下的房间目录（排除 failed/ 等保留目录）。供转写按房间扫描。"""
    if not AUDIO_DIR.exists():
        return []
    return [
        p for p in AUDIO_DIR.iterdir()
        if p.is_dir() and p.name not in RESERVED_AUDIO_SUBDIRS
    ]


def ensure_export_dir() -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
