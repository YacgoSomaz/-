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

    def test_launcher_preflights_mandatory_update_but_leaves_visible_flow_to_the_ui(self) -> None:
        self.assertIn("签名更新策略校验失败", LAUNCHER)
        self.assertNotIn("https://download.anyq.site/", LAUNCHER)
        self.assertIn("软件界面将打开，并显示更新进度", LAUNCHER)

    def test_launcher_does_not_show_a_blocking_windows_message_box_for_mandatory_update(self) -> None:
        policy = LAUNCHER[LAUNCHER.index("def _enforce_startup_update_policy"):LAUNCHER.index("def _tray_image")]
        self.assertNotIn("_show_error(message)", policy)
        self.assertNotIn("raise SystemExit(\"必须更新", policy)

    def test_launcher_allows_only_one_process_and_wakes_the_existing_window(self) -> None:
        self.assertIn("SINGLE_INSTANCE_MUTEX_NAME", LAUNCHER)
        self.assertIn("CreateMutexW", LAUNCHER)
        self.assertIn("ERROR_ALREADY_EXISTS", LAUNCHER)
        self.assertIn("_focus_existing_window", LAUNCHER)
        self.assertIn("SetForegroundWindow", LAUNCHER)
        self.assertIn("_acquire_single_instance", LAUNCHER)
        self.assertIn("wintypes.HANDLE", LAUNCHER)

    def test_launcher_integrity_is_limited_to_immutable_core_allowlist(self) -> None:
        self.assertIn("def _is_integrity_core_path", LAUNCHER)
        self.assertIn("if not _is_integrity_core_path(rel):", LAUNCHER)
        self.assertIn("Older manifests may contain user data", LAUNCHER)

    def test_source_launcher_skips_commercial_manifest_gate(self) -> None:
        integrity_fn = LAUNCHER[LAUNCHER.index("def _verify_integrity_manifest"):LAUNCHER.index("def _is_debugger_attached")]
        self.assertIn("if not _is_frozen():", integrity_fn)
        self.assertIn("return []", integrity_fn)


if __name__ == "__main__":
    unittest.main()
