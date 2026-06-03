import os

# 监听的直播间 URL，例如 https://live.douyin.com/xxxxxxx
LIVE_URL = os.getenv("DOUYIN_LIVE_URL", "")

# Whisper 模型大小：tiny / base / small
# CPU 环境建议 tiny（最快）或 base（精度更好）
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# 音频切片长度（秒），每段送 Whisper 转写
AUDIO_CHUNK_SECONDS = int(os.getenv("AUDIO_CHUNK_SECONDS", "60"))

# SQLite 数据库文件路径
DB_PATH = os.getenv("DB_PATH", "live_watch.db")

# ffmpeg 可执行文件路径（Windows 需要确认 PATH 里有 ffmpeg）
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
