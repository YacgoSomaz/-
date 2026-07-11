"""Background online refresh for commercial installs.

Network problems do not revoke a still-valid signed license by themselves.
However, an explicit server-side denial (expired card, frozen device, disabled
card) invalidates the local cache immediately.
"""

from __future__ import annotations

from . import config, license_client


def refresh_once() -> str:
    if not config.LICENSE_ENFORCE:
        return "skipped"
    try:
        license_client.refresh_license()
    except license_client.LicenseServerDenial as exc:
        return f"revoked: {exc}"
    except license_client.LicenseClientError as exc:
        return str(exc)
    return "refreshed"
