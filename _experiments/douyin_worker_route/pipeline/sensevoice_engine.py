"""SenseVoice 转写引擎（sherpa-onnx，纯 CPU）。

加载一次模型，反复转写。直接接受 mp3/wav 路径——内部用 ffmpeg 解码成
16kHz 单声道 float32，省去手动转 wav 这一步。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

import imageio_ffmpeg
import numpy as np
import sherpa_onnx

from . import config

_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_TARGET_SR = 16000


def _decode_16k_mono(audio_path: str) -> np.ndarray:
    """用 ffmpeg 把任意音频解码为 16kHz 单声道 float32 数组（范围[-1,1]）。"""
    proc = subprocess.run(
        [
            _FFMPEG,
            "-i", audio_path,
            "-af", config.LOUDNORM_FILTER,
            "-f", "s16le",
            "-ac", "1",
            "-ar", str(_TARGET_SR),
            "-",
        ],
        capture_output=True, creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0 or not proc.stdout:
        tail = proc.stderr.decode(errors="ignore")[-200:]
        raise RuntimeError(f"ffmpeg 解码失败 rc={proc.returncode}: {tail}")
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


class SenseVoiceEngine:
    """封装 sherpa-onnx SenseVoice 识别器。线程内顺序使用。"""

    def __init__(self, threads: int = config.ASR_THREADS) -> None:
        if not config.MODEL_ONNX.exists():
            raise FileNotFoundError(f"SenseVoice 模型不存在: {config.MODEL_ONNX}")
        self._rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(config.MODEL_ONNX),
            tokens=str(config.MODEL_TOKENS),
            num_threads=threads,
            use_itn=True,
            language="zh",
            debug=False,
        )

    def transcribe(self, audio_path: str | Path) -> str:
        """转写单个音频文件，返回文本（失败抛异常，由调用方处理）。"""
        samples = _decode_16k_mono(str(audio_path))
        stream = self._rec.create_stream()
        stream.accept_waveform(_TARGET_SR, samples)
        self._rec.decode_stream(stream)
        return (stream.result.text or "").strip()
