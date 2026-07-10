# Commercial License Hardening Plan

Goal: make copied installers less useful, prevent packaged secrets/data leaks, and prepare the app for paid license activation.

Phase 1 - local enforcement foundation:
- Add a client-side LicenseManager that validates a server-signed Ed25519 license.
- Bind license payload to a privacy-friendly device hash.
- Centralize feature checks: unlicensed builds can hide or block export, AI replay, short-video AI, lead radar, and batch features.
- Keep development mode unlocked unless LIVEWATCH_LICENSE_ENFORCE=1 is set.

Phase 2 - release hygiene:
- Add a release scanner that fails packaging when secrets, runtime data, tests, logs, databases, audio/video, browser profiles, or prompt drafts are present.
- Keep package staging whitelist-based: include only pipeline runtime files, static frontend, models, binaries, and notices.

Phase 3 - paid operations:
- Add a small license server: card-key activation, device binding, refresh, freeze, unbind, and admin audit logs.
- Client receives only signed licenses; private keys never ship with the installer.

Phase 4 - stronger packaging:
- Move from PyInstaller-only packaging to Nuitka where practical.
- Remove source maps and tests from release output.
- Add Windows code signing and signed update manifests.
