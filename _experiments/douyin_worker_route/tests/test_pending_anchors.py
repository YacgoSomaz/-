import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.manager import RoomManager


@contextlib.contextmanager
def managed(tmp: str):
    """Yield a RoomManager with all disk/db side effects redirected to tmp and the
    polling thread disabled. Patches stay active for the whole `with` body so
    add_pending/_save_pending hit the tmp paths, never the real data dir."""
    rooms_path = Path(tmp) / "rooms.json"
    pending_path = Path(tmp) / "pending_anchors.json"
    profile_path = Path(tmp) / "anchor_profiles.json"
    avatar_dir = Path(tmp) / "avatar_cache"
    with (
        patch("pipeline.manager.ROOMS_JSON", rooms_path),
        patch("pipeline.manager.PENDING_JSON", pending_path),
        patch("pipeline.anchor_profiles.config.ANCHOR_PROFILE_CACHE", profile_path),
        patch("pipeline.anchor_profiles.config.AVATAR_CACHE_DIR", avatar_dir),
        patch("pipeline.manager.config.ensure_dirs"),
        patch("pipeline.manager.SqliteSink"),
        patch("pipeline.manager.TranscriptStore"),
        patch.object(RoomManager, "_start_pending_watch"),
    ):
        yield RoomManager()


class PendingAnchorTests(unittest.TestCase):
    def test_add_pending_persists_and_lists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, managed(tmp) as mgr:
            res = mgr.add_pending("MS4wSEC1", {"anchor_name": "未开播主播", "source_url": "u"})
            self.assertTrue(res["ok"])

            listed = mgr.pending_status()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["sec_user_id"], "MS4wSEC1")
            self.assertEqual(listed[0]["anchor_name"], "未开播主播")

            saved = json.loads((Path(tmp) / "pending_anchors.json").read_text(encoding="utf-8"))
            self.assertEqual(saved[0]["sec_user_id"], "MS4wSEC1")

    def test_add_pending_rejects_duplicate_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, managed(tmp) as mgr:
            self.assertTrue(mgr.add_pending("MS4wSEC1")["ok"])
            self.assertFalse(mgr.add_pending("MS4wSEC1")["ok"])  # duplicate
            self.assertFalse(mgr.add_pending("")["ok"])          # empty

    def test_cap_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, managed(tmp) as mgr:
            with patch("pipeline.manager.config.MAX_PENDING_ANCHORS", 2):
                self.assertTrue(mgr.add_pending("a")["ok"])
                self.assertTrue(mgr.add_pending("b")["ok"])
                full = mgr.add_pending("c")
                self.assertFalse(full["ok"])
                self.assertIn("上限", full["reason"])

    def test_remove_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, managed(tmp) as mgr:
            mgr.add_pending("MS4wSEC1")
            self.assertTrue(mgr.remove_pending("MS4wSEC1"))
            self.assertEqual(mgr.pending_status(), [])
            self.assertFalse(mgr.remove_pending("MS4wSEC1"))  # already gone

    def test_promotion_on_live_detection(self) -> None:
        """When a pending anchor goes live, it becomes a started room and leaves pending."""
        with tempfile.TemporaryDirectory() as tmp, managed(tmp) as mgr:
            mgr.add_pending("MS4wSEC1", {"anchor_name": "登记名"})

            live_result = {
                "ok": True, "is_live": True, "web_id": "998877",
                "nickname": "开播实名", "avatar_url": "", "state": "live",
            }
            with (
                patch("pipeline.manager.profile_watch.check_profile", return_value=live_result),
                patch("pipeline.manager.browser_cookies.cached_jar", return_value={}),
                patch.object(RoomManager, "start_room", return_value=True) as start,
            ):
                mgr._check_one_pending("MS4wSEC1")

            self.assertEqual(mgr.pending_status(), [])
            self.assertIn("998877", mgr._rooms)
            self.assertEqual(mgr._rooms["998877"].sec_user_id, "MS4wSEC1")
            self.assertEqual(mgr._rooms["998877"].anchor_name, "开播实名")
            start.assert_called_once_with("998877")
            profile_path = Path(tmp) / "anchor_profiles.json"
            self.assertTrue(profile_path.exists())
            self.assertEqual(json.loads(profile_path.read_text(encoding="utf-8"))["998877"]["anchor_name"], "开播实名")

    def test_offline_keeps_pending_and_schedules_recheck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, managed(tmp) as mgr:
            mgr.add_pending("MS4wSEC1")
            offline = {"ok": True, "is_live": False, "web_id": "", "state": "offline"}
            with (
                patch("pipeline.manager.profile_watch.check_profile", return_value=offline),
                patch("pipeline.manager.browser_cookies.cached_jar", return_value={}),
            ):
                mgr._check_one_pending("MS4wSEC1")
            self.assertEqual(len(mgr.pending_status()), 1)
            self.assertGreater(mgr._pending["MS4wSEC1"].next_check_ts, 0)

    def test_challenge_triggers_global_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, managed(tmp) as mgr:
            mgr.add_pending("MS4wSEC1")
            challenge = {"ok": False, "state": "challenge"}
            with (
                patch("pipeline.manager.profile_watch.check_profile", return_value=challenge),
                patch("pipeline.manager.browser_cookies.cached_jar", return_value={}),
            ):
                mgr._check_one_pending("MS4wSEC1")
            self.assertTrue(mgr.risk_control_status()["active"])


if __name__ == "__main__":
    unittest.main()
