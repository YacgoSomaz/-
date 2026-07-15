"""
模块 C：Whisper 转写（本地 CPU）

把 WAV 音频转成中文文字。首次运行会下载模型（base 约 140MB）。

独立测试（转写指定 WAV，默认 test_record.wav）：
    python transcriber.py [wav文件] [模型名]
    模型名可选: tiny / base / small（CPU 建议 tiny 或 base）
"""

import logging
import sys
import time
import wave

import numpy as np
import whisper

log = logging.getLogger("transcriber")

_model_cache: dict[str, "whisper.Whisper"] = {}
_simp_converter = None


def _to_simplified(text: str) -> str:
    """Convert Whisper's occasional Traditional Chinese output to Simplified."""
    global _simp_converter
    if not text:
        return text
    try:
        if _simp_converter is None:
            from opencc import OpenCC

            _simp_converter = OpenCC("t2s")
        return _simp_converter.convert(text)
    except Exception:
        return text


def _load_wav_16k_mono(path: str) -> np.ndarray:
    """
    读取 16kHz 单声道 WAV 为 float32 数组（范围 [-1, 1]）。
    直接喂给 Whisper，绕过它内部对 PATH 中 ffmpeg 的依赖。
    """
    with wave.open(path, "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1:
            raise ValueError(
                f"需要 16kHz 单声道 WAV，实际 {w.getframerate()}Hz "
                f"{w.getnchannels()}声道（录音模块已统一为此格式）"
            )
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def get_model(name: str = "base") -> "whisper.Whisper":
    if name not in _model_cache:
        log.info("加载 Whisper 模型 '%s'（首次会下载）...", name)
        t0 = time.time()
        _model_cache[name] = whisper.load_model(name)
        log.info("模型加载完成，耗时 %.1fs", time.time() - t0)
    return _model_cache[name]


def transcribe_file(wav_path: str, model_name: str = "base") -> str:
    """转写单个 WAV，返回中文文本。"""
    model = get_model(model_name)
    audio = _load_wav_16k_mono(wav_path)
    t0 = time.time()
    result = model.transcribe(
        audio,
        language="zh",
        task="transcribe",
        fp16=False,
        temperature=0,
        beam_size=5,
        condition_on_previous_text=False,
        no_speech_threshold=0.65,
        logprob_threshold=-1.0,
        compression_ratio_threshold=2.4,
        initial_prompt=(
            "以下是抖音直播间主播的普通话口播、带货话术或互动话术。"
            "请按听到的内容转写成通顺的简体中文，不要使用繁体字；"
            "如果听不清，不要编造内容。"
        ),
    )
    cost = time.time() - t0
    text = _to_simplified(result["text"].strip())
    log.info("转写完成，耗时 %.1fs", cost)
    return text


def _main():
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    wav = sys.argv[1] if len(sys.argv) > 1 else "test_record.wav"
    model_name = sys.argv[2] if len(sys.argv) > 2 else "base"

    log.info("转写文件: %s（模型: %s）", wav, model_name)
    text = transcribe_file(wav, model_name)

    print("\n=== 转写结果 ===")
    print(text or "（空，可能是纯背景音/音乐）")


if __name__ == "__main__":
    _main()
