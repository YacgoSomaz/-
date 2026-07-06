import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from pipeline import config
from pipeline.audio_capture import _FFMPEG, _terminate


class MuxerStopTests(unittest.TestCase):
    def test_terminate_flushes_current_short_segment(self) -> None:
        """Stopping ffmpeg should seal the active <60s segment instead of leaving 0B junk."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            csv_path = root / config.SEGMENT_LIST_NAME
            out_pattern = root / config.SEGMENT_FILENAME
            proc = subprocess.Popen(
                [
                    _FFMPEG,
                    "-y",
                    "-re",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=1000:sample_rate=16000",
                    "-ac",
                    "1",
                    "-acodec",
                    "libmp3lame",
                    "-f",
                    "segment",
                    "-segment_time",
                    "60",
                    "-segment_start_number",
                    "1",
                    "-reset_timestamps",
                    "1",
                    "-segment_list",
                    str(csv_path),
                    "-segment_list_type",
                    "csv",
                    str(out_pattern),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                time.sleep(2)
                _terminate(proc)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)

            segment = root / "seq00001.mp3"
            self.assertTrue(csv_path.exists())
            self.assertIn("seq00001.mp3", csv_path.read_text(encoding="utf-8"))
            self.assertGreater(segment.stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
