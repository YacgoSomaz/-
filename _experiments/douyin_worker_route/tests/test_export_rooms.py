import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import export


class MonitoredRoomIdsTests(unittest.TestCase):
    def test_supports_legacy_string_room_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rooms.json"
            path.write_text(json.dumps(["123", "456"]), encoding="utf-8")
            with patch("pipeline.export.ROOMS_JSON", path):
                self.assertEqual(export.monitored_room_ids(), ["123", "456"])

    def test_extracts_rid_from_metadata_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rooms.json"
            path.write_text(
                json.dumps(
                    [
                        {"rid": "123", "anchor_name": "主播", "avatar_url": "https://example.test/a.jpg"},
                        {"rid": "456", "source_url": "https://live.douyin.com/456?x=1"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch("pipeline.export.ROOMS_JSON", path):
                self.assertEqual(export.monitored_room_ids(), ["123", "456"])

    def test_ignores_invalid_entries_instead_of_using_dict_as_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rooms.json"
            path.write_text(json.dumps([{"anchor_name": "missing"}, None, "not-a-room"]), encoding="utf-8")
            with patch("pipeline.export.ROOMS_JSON", path):
                self.assertEqual(export.monitored_room_ids(), [])

    def test_single_room_export_uses_safe_anchor_nickname(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rooms.json"
            path.write_text(
                json.dumps([{"rid": "123", "anchor_name": "主播:A/B?"}], ensure_ascii=False),
                encoding="utf-8",
            )
            with (
                patch("pipeline.export.ROOMS_JSON", path),
                patch("pipeline.export.load_room_meta", return_value={}),
            ):
                self.assertEqual(export.room_export_filename("123"), "主播_A_B_.xlsx")

    def test_single_room_export_falls_back_to_live_id(self) -> None:
        with (
            patch("pipeline.export.configured_room_meta", return_value={}),
            patch("pipeline.export.load_room_meta", return_value={}),
        ):
            self.assertEqual(export.room_export_filename("123"), "123.xlsx")

    def test_duplicate_nicknames_append_live_id(self) -> None:
        class Bundle:
            def __init__(self, rid, nickname):
                self.rid = rid
                self.nickname = nickname

        stems = export.unique_bundle_stems([Bundle("123", "同名主播"), Bundle("456", "同名主播")])

        self.assertEqual(stems, {"123": "同名主播_123", "456": "同名主播_456"})


if __name__ == "__main__":
    unittest.main()
