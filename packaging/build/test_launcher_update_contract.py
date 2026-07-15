"""Static safety contract for the launcher-side signed update gate."""

from __future__ import annotations

from pathlib import Path
import unittest


LAUNCHER = (Path(__file__).resolve().parent / "livewatch_launcher.py").read_text(encoding="utf-8")


class LauncherUpdateContractTests(unittest.TestCase):
    def test_launcher_checks_the_signed_update_policy_before_webui_starts(self) -> None:
        self.assertIn("def _enforce_startup_update_policy", LAUNCHER)
        self.assertIn("updater.check_update()", LAUNCHER)
        self.assertIn("manifest.mandatory and manifest.has_update", LAUNCHER)
        self.assertIn("_enforce_startup_update_policy()", LAUNCHER)
        self.assertLess(
            LAUNCHER.index("_enforce_startup_update_policy()"),
            LAUNCHER.index("from pipeline.webui import app"),
        )

    def test_launcher_downloads_and_checks_the_verified_manifest_before_launching(self) -> None:
        self.assertIn("updater.download_update(manifest)", LAUNCHER)
        self.assertIn("updater.run_installer(installer, silent=False)", LAUNCHER)
        self.assertIn("签名更新策略校验失败", LAUNCHER)
        self.assertNotIn("https://download.anyq.site/", LAUNCHER)

    def test_launcher_allows_only_one_process_and_wakes_the_existing_window(self) -> None:
        self.assertIn("SINGLE_INSTANCE_MUTEX_NAME", LAUNCHER)
        self.assertIn("CreateMutexW", LAUNCHER)
        self.assertIn("ERROR_ALREADY_EXISTS", LAUNCHER)
        self.assertIn("_focus_existing_window", LAUNCHER)
        self.assertIn("SetForegroundWindow", LAUNCHER)
        self.assertIn("_acquire_single_instance", LAUNCHER)
        self.assertIn("wintypes.HANDLE", LAUNCHER)


if __name__ == "__main__":
    unittest.main()
