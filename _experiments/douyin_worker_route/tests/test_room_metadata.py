import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.manager import RoomManager, merge_live_anchor_metadata


def test_live_connection_metadata_cannot_replace_resolved_anchor_with_cookie_owner() -> None:
    """登录账号只提供访问 Cookie，绝不能覆盖已解析的目标主播身份。"""
    name, avatar = merge_live_anchor_metadata(
        current_name="昆明大华锦绣慧城",
        current_avatar="",
        live_name="慕蓉蓉",
        live_avatar="https://p.example.test/viewer.jpg",
    )

    assert name == "昆明大华锦绣慧城"
    assert avatar == ""


def test_live_connection_metadata_can_fill_missing_profile() -> None:
    name, avatar = merge_live_anchor_metadata(
        current_name="",
        current_avatar="",
        live_name="目标主播",
        live_avatar="https://p.example.test/anchor.jpg",
    )

    assert name == "目标主播"
    assert avatar == "https://p.example.test/anchor.jpg"


class RoomMetadataTests(unittest.TestCase):
    def test_loads_legacy_room_list_and_persists_anchor_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rooms_path = Path(tmp) / "rooms.json"
            profile_path = Path(tmp) / "anchor_profiles.json"
            avatar_dir = Path(tmp) / "avatar_cache"
            rooms_path.write_text(json.dumps(["123"]), encoding="utf-8")
            with (
                patch("pipeline.manager.ROOMS_JSON", rooms_path),
                patch("pipeline.anchor_profiles.config.ANCHOR_PROFILE_CACHE", profile_path),
                patch("pipeline.anchor_profiles.config.AVATAR_CACHE_DIR", avatar_dir),
                patch("pipeline.manager.config.ensure_dirs"),
                patch("pipeline.manager.SqliteSink"),
                patch("pipeline.manager.TranscriptStore"),
            ):
                manager = RoomManager()
                changed = manager.add_room(
                    "123",
                    {
                        "anchor_name": "测试主播",
                        "avatar_url": "https://example.com/avatar.jpg",
                    },
                )

            self.assertTrue(changed)
            saved = json.loads(rooms_path.read_text(encoding="utf-8"))
            self.assertEqual(saved[0]["rid"], "123")
            self.assertEqual(saved[0]["anchor_name"], "测试主播")
            self.assertEqual(saved[0]["avatar_url"], "https://example.com/avatar.jpg")
            profiles = json.loads((Path(tmp) / "anchor_profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(profiles["123"]["anchor_name"], "测试主播")


if __name__ == "__main__":
    unittest.main()
