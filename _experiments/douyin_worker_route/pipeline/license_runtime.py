"""Build-time public licensing settings.

The source tree deliberately stays unlocked. `build_release.ps1 -Commercial`
replaces this file in the staging copy with a non-secret public key, HTTPS
license-server URL, and enforcement flag.
"""

LICENSE_ENFORCE = False
LICENSE_SERVER_URL = ""
LICENSE_PUBLIC_KEY = ""
LICENSE_APP_VERSION = ""
