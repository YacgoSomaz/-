import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.manager import RoomManager


class RoomMetadataTests(unittest.TestCase):
    def test_loads_legacy_room_list_and_persists_anchor_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rooms_path = Path(tmp) / "rooms.json"
            rooms_path.write_text(json.dumps(["123"]), encoding="utf-8")
            with (
                patch("pipeline.manager.ROOMS_JSON", rooms_path),
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


if __name__ == "__main__":
    unittest.main()
