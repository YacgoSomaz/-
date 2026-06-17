import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pipeline import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.audio = root / "audio"
        self.audio.mkdir()
        self.config = SimpleNamespace(
            ROUTE_DIR=root,
            AUDIO_DIR=self.audio,
            DB_PATH=root / "transcripts.db",
            SPEAKER_DB_PATH=root / "speaker_labels.db",
            MODEL_ONNX=root / "sensevoice.onnx",
            MODEL_TOKENS=root / "tokens.txt",
            SPEAKER_MODEL=root / "speaker.onnx",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cookie_status_never_mints_and_reports_expiry(self) -> None:
        cache = self.config.ROUTE_DIR / "browser_cookies.json"
        cache.write_text(
            json.dumps({"jar": {"ttwid": "secret", "odin_tt": "secret"}, "ts": 1000}),
            encoding="utf-8",
        )

        status = diagnostics.cookie_status(cache, now=1000 + 9 * 3600)

        self.assertEqual(status["state"], "expired")
        self.assertTrue(status["has_ttwid"])
        self.assertNotIn("jar", status)
        self.assertNotIn("secret", repr(status))

    def test_snapshot_reports_models_disk_audio_and_queues(self) -> None:
        self.config.MODEL_ONNX.write_bytes(b"model")
        self.config.MODEL_TOKENS.write_text("tokens", encoding="utf-8")
        room = self.audio / "room"
        room.mkdir()
        audio = room / "seq00001.mp3"
        audio.write_bytes(b"x" * 2048)

        con = sqlite3.connect(self.config.DB_PATH)
        con.execute(
            "CREATE TABLE recording_timeline "
            "(id INTEGER, kind TEXT, transcribed_ts INTEGER)"
        )
        con.execute("INSERT INTO recording_timeline VALUES(1,'segment',NULL)")
        con.execute("CREATE TABLE transcripts (room_id TEXT, mp3_name TEXT)")
        con.execute("INSERT INTO transcripts VALUES('room','audio/room/seq00001.mp3')")
        con.commit()
        con.close()

        snapshot = diagnostics.build_snapshot(self.config, now=2000)

        self.assertFalse(snapshot["models"]["ready"])
        self.assertTrue(snapshot["models"]["sensevoice"])
        self.assertFalse(snapshot["models"]["speaker"])
        self.assertEqual(snapshot["queues"]["transcription_pending"], 1)
        self.assertEqual(snapshot["queues"]["speaker_pending"], 1)
        self.assertEqual(snapshot["storage"]["audio_files"], 1)
        self.assertGreater(snapshot["storage"]["free_gb"], 0)


if __name__ == "__main__":
    unittest.main()
