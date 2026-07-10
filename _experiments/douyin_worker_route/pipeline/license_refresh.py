"""Background online refresh for commercial installs.

Network problems never stop the recorder by themselves. A valid cached license
continues through its signed expiry/grace window; a server-side freeze is
enforced at the next successful refresh.
"""

from __future__ import annotations

from . import config, license_client


def refresh_once() -> str:
    if not config.LICENSE_ENFORCE:
        return "skipped"
    try:
        license_client.refresh_license()
    except license_client.LicenseClientError as exc:
        return str(exc)
    return "refreshed"
