"""Release integrity manifest helpers.

This is not a DRM silver bullet. It raises the cost of casual repackaging by
making the launcher refuse to start when critical installed program files have
been changed after packaging.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

MANIFEST_NAME = "integrity_manifest.json"
MANIFEST_VERSION = 1
_SKIP_DIRS = {
    ".git",
    "__pycache__",
    "audio",
    "exports",
    "logs",
    "models",
    "video",
}
_SKIP_FILES = {
    MANIFEST_NAME,
    "license.json",
    "license_clock.json",
    "browser_cookies.json",
    "short_video_cookies.json",
    "rooms.json",
    "transcripts.db",
    "multi_events.db",
}


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    parts = set(rel.parts)
    if parts & _SKIP_DIRS:
        return True
    if path.name in _SKIP_FILES:
        return True
    return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_manifest_files(root: Path) -> list[Path]:
    root = root.resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _should_skip(path, root):
            continue
        files.append(path)
    return sorted(files, key=lambda p: _rel(p, root).lower())


def build_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    files = [
        {
            "path": _rel(path, root),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in iter_manifest_files(root)
    ]
    return {
        "version": MANIFEST_VERSION,
        "algorithm": "sha256",
        "files": files,
    }


def write_manifest(root: Path, manifest: dict[str, Any]) -> Path:
    root = root.resolve()
    target = root / MANIFEST_NAME
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return target


def write_and_verify(root: Path) -> Path:
    target = write_manifest(root, build_manifest(root))
    findings = verify_manifest(root)
    if findings:
        raise RuntimeError("完整性清单生成后校验失败：" + "; ".join(findings[:5]))
    return target


def load_manifest(root: Path) -> dict[str, Any] | None:
    path = root.resolve() / MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def verify_manifest(root: Path) -> list[str]:
    root = root.resolve()
    manifest = load_manifest(root)
    if not manifest:
        return [f"missing {MANIFEST_NAME}"]
    files = manifest.get("files")
    if not isinstance(files, list):
        return ["invalid integrity manifest"]
    findings: list[str] = []
    for entry in files:
        if not isinstance(entry, dict):
            findings.append("invalid manifest entry")
            continue
        rel = str(entry.get("path") or "")
        expected = str(entry.get("sha256") or "")
        path = root / rel
        if not path.exists():
            findings.append(f"missing {rel}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            findings.append(f"hash mismatch {rel}")
    return findings
