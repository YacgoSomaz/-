"""打包 macOS 发行包：只含运行所需文件，排除开发/数据/调试文件。

用法: python pack_macos.py
输出: ../LiveWatch_macOS.zip
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_NAME = "LiveWatch_macOS"
OUT_ZIP = HERE.parent / f"{OUT_NAME}.zip"
STAGE = HERE.parent / f"_pack_stage_{OUT_NAME}"

INCLUDE_DIRS = [
    "pipeline",
    "vendor",
]

INCLUDE_FILES = [
    "LiveWatch.command",
    "requirements.txt",
    "run_worker.py",
    "run_multi.py",
    "record_multi_audio.py",
    "make_mp3.py",
]

EXCLUDE_PATTERNS = {
    "__pycache__",
    ".pyc",
    ".pyo",
    ".db",
    ".db-journal",
    ".log",
    ".bak",
    ".json",
    ".mp3",
    ".wav",
    ".txt",
    "_scratch_",
    ".bat",
}

VENDOR_EXCLUDE_NAMES = {
    "protoc.exe",
    "alipay.jpg",
    "_cookie_test.db",
    "_md5.txt",
    ".gitattributes",
    ".gitignore",
    "main.py",
    "requirements.txt",
    "README.MD",
    "readme.md",
    "LICENSE",
}


def copy_dir(src: Path, dst: Path, *, extra_exclude: set[str] | None = None) -> None:
    skip_names = extra_exclude or set()
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        if any(part == "__pycache__" for part in rel.parts):
            continue
        if item.suffix in {".pyc", ".pyo"}:
            continue
        if item.name in skip_names:
            continue
        dest_file = dst / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest_file)


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    root = STAGE / "LiveWatch"
    root.mkdir(parents=True)

    for d in INCLUDE_DIRS:
        src = HERE / d
        if src.is_dir():
            exc = VENDOR_EXCLUDE_NAMES if d == "vendor" else None
            copy_dir(src, root / d, extra_exclude=exc)

    for f in INCLUDE_FILES:
        src = HERE / f
        if src.is_file():
            shutil.copy2(src, root / f)

    # ASR 模型 → models/ (对应 LIVEWATCH_RESOURCE_DIR)
    models_dir = root / "models"
    sv_src = HERE.parent / "asr_bench" / "sensevoice_onnx"
    sv_dst = models_dir / "sensevoice_onnx"
    if sv_src.is_dir():
        sv_dst.mkdir(parents=True, exist_ok=True)
        for f in ("model.int8.onnx", "tokens.txt"):
            s = sv_src / f
            if s.is_file():
                shutil.copy2(s, sv_dst / f)

    spk_src = HERE.parent / "speaker_change_analysis" / "models" / "3dspeaker_eres2net_zh_16k.onnx"
    spk_dst = models_dir / "speaker"
    if spk_src.is_file():
        spk_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(spk_src, spk_dst / spk_src.name)

    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(root.rglob("*")):
            if item.is_file():
                zf.write(item, item.relative_to(STAGE))

    shutil.rmtree(STAGE)

    size_mb = OUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"已打包: {OUT_ZIP}  ({size_mb:.1f} MB)")
    print(f"包含 {sum(1 for _ in zipfile.ZipFile(OUT_ZIP).namelist())} 个文件")


if __name__ == "__main__":
    main()
