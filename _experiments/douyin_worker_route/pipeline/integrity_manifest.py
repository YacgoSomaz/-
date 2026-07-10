"""Release integrity manifest helpers.

This is not a DRM silver bullet. It raises the cost of casual repackaging by
making the launcher refuse to start when critical installed program files have
been changed after packaging.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

MANIFEST_NAME = "integrity_manifest.json"
MANIFEST_VERSION = 2
SIGNATURE_ALGORITHM = "Ed25519"
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
    lower_name = path.name.lower()
    if lower_name.startswith("unins") and lower_name.rsplit(".", 1)[-1] in {"dat", "exe", "msg"}:
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


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def generate_keypair() -> tuple[str, str]:
    """Return base64url raw Ed25519 private/public keys for build-time signing."""
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    public_raw = private_key.public_key().public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )
    return b64url_encode(private_raw), b64url_encode(public_raw)


def _canonical_payload(manifest: dict[str, Any]) -> bytes:
    unsigned = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "files": files,
    }


def sign_manifest(manifest: dict[str, Any], private_key_b64: str) -> dict[str, Any]:
    signed = dict(manifest)
    signed.pop("signature", None)
    private_key = Ed25519PrivateKey.from_private_bytes(b64url_decode(private_key_b64))
    signed["signature"] = b64url_encode(private_key.sign(_canonical_payload(signed)))
    return signed


def verify_manifest_signature(manifest: dict[str, Any], public_key_b64: str) -> list[str]:
    signature = manifest.get("signature")
    if not isinstance(signature, str) or not signature:
        return ["missing manifest signature"]
    if manifest.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        return ["unsupported manifest signature algorithm"]
    try:
        public_key = Ed25519PublicKey.from_public_bytes(b64url_decode(public_key_b64))
        public_key.verify(b64url_decode(signature), _canonical_payload(manifest))
    except (ValueError, InvalidSignature) as exc:
        return [f"invalid manifest signature: {exc.__class__.__name__}"]
    return []


def write_manifest(root: Path, manifest: dict[str, Any]) -> Path:
    root = root.resolve()
    target = root / MANIFEST_NAME
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return target


def write_and_verify(
    root: Path,
    *,
    private_key_b64: str | None = None,
    public_key_b64: str | None = None,
) -> Path:
    key = private_key_b64 or os.environ.get("LIVEWATCH_INTEGRITY_PRIVATE_KEY", "")
    manifest = build_manifest(root)
    if key:
        manifest = sign_manifest(manifest, key)
    target = write_manifest(root, manifest)
    verify_key = public_key_b64 or os.environ.get("LIVEWATCH_INTEGRITY_PUBLIC_KEY", "")
    findings = verify_manifest(root, public_key_b64=verify_key, require_signature=bool(verify_key))
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


def verify_manifest(
    root: Path,
    *,
    public_key_b64: str | None = None,
    require_signature: bool = False,
) -> list[str]:
    root = root.resolve()
    manifest = load_manifest(root)
    if not manifest:
        return [f"missing {MANIFEST_NAME}"]
    files = manifest.get("files")
    if not isinstance(files, list):
        return ["invalid integrity manifest"]
    findings: list[str] = []
    if public_key_b64:
        findings.extend(verify_manifest_signature(manifest, public_key_b64))
    elif require_signature:
        findings.append("manifest signature required")

    covered: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            findings.append("invalid manifest entry")
            continue
        rel = str(entry.get("path") or "")
        covered.add(rel.replace("\\", "/"))
        expected = str(entry.get("sha256") or "")
        path = root / rel
        if not path.exists():
            findings.append(f"missing {rel}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            findings.append(f"hash mismatch {rel}")
    for path in iter_manifest_files(root):
        rel = _rel(path, root)
        if rel not in covered:
            findings.append(f"unexpected file {rel}")
    return findings
