import sqlite3
import unittest

import numpy as np

from pipeline import speaker_worker


def _unit(values: list[float]) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


class SpeakerMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript(speaker_worker._SCHEMA)

    def tearDown(self) -> None:
        self.con.close()

    def _profile(self, label: str, vector: np.ndarray, count: int) -> None:
        self.con.execute(
            "INSERT INTO speaker_profiles VALUES(?,?,?,?,?)",
            ("room", label, vector.tobytes(), count, 1),
        )

    def _label(self, file_name: str, label: str, vector: np.ndarray) -> None:
        self.con.execute(
            "INSERT INTO speaker_labels "
            "(room_id,file_name,speaker_label,similarity,change_status,embedding,"
            "source,error,segment_ts,analyzed_ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "room", file_name, label, 0.8, "change_confirmed_start",
                vector.tobytes(), "incremental", None, 1, 1,
            ),
        )

    def test_merges_similar_profile_without_renumbering_other_labels(self) -> None:
        a = _unit([1.0, 0.0, 0.0])
        d = _unit([0.76, 0.65, 0.0])
        e = _unit([0.0, 1.0, 0.0])
        f = _unit([0.0, 0.0, 1.0])
        self.assertGreaterEqual(float(np.dot(a, d)), 0.70)

        self._profile("speaker_A", a, 13)
        self._profile("speaker_D", d, 50)
        self._profile("speaker_E", e, 56)
        self._profile("speaker_F", f, 60)
        self._label("a.mp3", "speaker_A", a)
        self._label("d1.mp3", "speaker_D", d)
        self._label("d2.mp3", "speaker_D", d)

        merges = speaker_worker._merge_similar_profiles(self.con, "room", threshold=0.70)

        self.assertEqual(merges, [("speaker_D", "speaker_A")])
        profiles = {
            row["speaker_label"]: row["sample_count"]
            for row in self.con.execute(
                "SELECT speaker_label,sample_count FROM speaker_profiles WHERE room_id='room'"
            )
        }
        self.assertEqual(profiles, {"speaker_A": 63, "speaker_E": 56, "speaker_F": 60})
        moved = self.con.execute(
            "SELECT speaker_label,change_status FROM speaker_labels "
            "WHERE room_id='room' AND file_name='d1.mp3'"
        ).fetchone()
        self.assertEqual(moved["speaker_label"], "speaker_A")
        self.assertEqual(moved["change_status"], "")


if __name__ == "__main__":
    unittest.main()
