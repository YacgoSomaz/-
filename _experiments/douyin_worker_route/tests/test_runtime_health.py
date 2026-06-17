import unittest
from unittest.mock import patch

from pipeline.runtime_health import ErrorRegistry


class ErrorRegistryTests(unittest.TestCase):
    def test_keeps_latest_error_per_component_without_unbounded_growth(self) -> None:
        registry = ErrorRegistry(limit=2)
        with patch("pipeline.runtime_health.time.time", side_effect=[1, 2, 3]):
            registry.record("audio:1", RuntimeError("first"))
            registry.record("transcription", ValueError("second"))
            registry.record("speaker", OSError("third"))

        rows = registry.snapshot()

        self.assertEqual([row["component"] for row in rows], ["speaker", "transcription"])
        self.assertEqual(rows[0]["message"], "OSError('third')")


if __name__ == "__main__":
    unittest.main()
