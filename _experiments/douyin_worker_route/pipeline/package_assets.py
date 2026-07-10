"""Locate non-code frontend assets in source and compiled commercial builds."""

from __future__ import annotations

import os
from pathlib import Path


def package_asset_dir(module_file: str | Path) -> Path:
    """Return the external asset directory for the current package runtime."""
    configured = os.environ.get("LIVEWATCH_PIPELINE_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(module_file).resolve().parent
