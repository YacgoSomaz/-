import tempfile
import time
import unittest
from pathlib import Path

from pipeline import config
from pipeline.transcribe_batch import process_once
from pipeline.transcript_store import TranscriptStore


class _FailingEngine:
    def transcribe(self, _path):
        raise RuntimeError("temporary decode failure")


class TranscriptionRecoveryTests(unittest.TestCase):
    def test_nonempty_partial_segment_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = TranscriptStore(Path(td) / "transcripts.db")
            store.add_partial(
                room_id="room",
                seq=1,
                file_path="audio/room/seq00001.mp3",
                capture_start=time.time() - 5,
                capture_end=time.time(),
                duration_sec=5,
                file_size=2048,
            )
            store.add_partial(
                room_id="room",
                seq=2,
                file_path="audio/room/seq00002.mp3",
                capture_start=None,
                capture_end=None,
                duration_sec=None,
                file_size=0,
            )

            pending = store.pending_sealed_segments()
            store.close()

        self.assertEqual([row.seq for row in pending], [1])

    def test_transcription_error_stays_pending_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / "audio" / "room"
            audio.mkdir(parents=True)
            mp3 = audio / "seq00001.mp3"
            mp3.write_bytes(b"not-real-audio")
            store = TranscriptStore(root / "transcripts.db")
            store.add_segment(
                room_id="room",
                seq=1,
                file_path="audio/room/seq00001.mp3",
                capture_start=time.time() - 60,
                capture_end=time.time(),
                duration_sec=60,
                file_size=mp3.stat().st_size,
            )
            old_data_dir = config.DATA_DIR
            config.DATA_DIR = root
            try:
                processed = process_once(_FailingEngine(), store)
                pending = store.pending_sealed_segments()
            finally:
                config.DATA_DIR = old_data_dir
                store.close()

        self.assertEqual(processed, 0)
        self.assertEqual(len(pending), 1)


if __name__ == "__main__":
    unittest.main()
