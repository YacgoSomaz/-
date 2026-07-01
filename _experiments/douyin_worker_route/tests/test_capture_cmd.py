import unittest
from pathlib import Path

from pipeline import config
from pipeline.audio_capture import _FFMPEG, _build_capture_cmd, rank_m3u8


# 真实房间页观测到的清晰度变体（带签名），用于验证选流逻辑。
_SAMPLE_HTML = " ".join(
    f'"https://pull.example.com/stage/stream-1{tag}/index.m3u8?sign=abc{i}"'
    for i, tag in enumerate(["", "_hd5", "_hd", "_sd", "_md", "_ld", "_or4"])
)


class RankM3u8Tests(unittest.TestCase):
    def test_origin_quality_picks_or4_first(self) -> None:
        ordered, n = rank_m3u8(_SAMPLE_HTML, quality="origin")
        self.assertGreater(n, 0)
        self.assertIn("_or4", ordered[0])  # 原画优先 or4

    def test_hd_quality_picks_hd_not_origin(self) -> None:
        """选高清时取最接近 720p 的流（hd/hd5），不会上原画也不会掉到最低。"""
        ordered, _ = rank_m3u8(_SAMPLE_HTML, quality="hd")
        self.assertTrue(any(t in ordered[0] for t in ("_hd", "_hd5")))
        self.assertNotIn("_or4", ordered[0])

    def test_quality_orders_by_distance(self) -> None:
        ordered, _ = rank_m3u8(_SAMPLE_HTML, quality="origin")
        self.assertLess(
            next(i for i, u in enumerate(ordered) if "_hd5" in u),
            next(i for i, u in enumerate(ordered) if "_ld" in u),
        )

    def test_audio_default_behavior_unchanged(self) -> None:
        """quality=None（纯音频）时不优先原画（保持历史低带宽偏好）。"""
        ordered, _ = rank_m3u8(_SAMPLE_HTML, quality=None)
        self.assertNotIn("_or4", ordered[0])


class BuildCaptureCmdTests(unittest.TestCase):
    def _audio_only_expected(self, url: str, room_dir: Path, seq: int, csv: Path) -> list[str]:
        # 历史音频命令，逐字节锁定：视频开关关闭时绝不能偏离这条。
        return [
            _FFMPEG,
            "-y", "-headers", config.RECORD_REFERER, "-i", url, "-vn",
            "-ar", "16000", "-ac", "1", "-acodec", "libmp3lame",
            "-f", "segment", "-segment_time", str(config.SEGMENT_SEC),
            "-segment_start_number", str(seq), "-reset_timestamps", "1",
            "-segment_list", str(csv), "-segment_list_type", "csv",
            str(room_dir / config.SEGMENT_FILENAME),
        ]

    def test_video_off_is_audio_only(self) -> None:
        room = Path("/tmp/audio/123")
        csv = room / config.SEGMENT_LIST_NAME
        cmd = _build_capture_cmd("http://x/index.m3u8", room, 7, csv, record_video=False)
        self.assertNotIn("copy", cmd)
        # 末尾就是音频段输出，没有任何视频输出
        self.assertTrue(cmd[-1].endswith(config.SEGMENT_FILENAME))
        self.assertEqual(cmd, self._audio_only_expected("http://x/index.m3u8", room, 7, csv))

    def test_video_on_appends_copy_mp4_output(self) -> None:
        room = Path("/tmp/audio/123")
        vdir = Path("/tmp/video/123")
        csv = room / config.SEGMENT_LIST_NAME
        cmd = _build_capture_cmd(
            "http://x/index.m3u8", room, 7, csv, record_video=True, video_dir=vdir
        )
        # 音频段输出仍在（驱动转写的 csv 不变），后面追加了视频 copy 分段输出
        self.assertIn("-segment_list", cmd)
        self.assertIn("copy", cmd)
        # 不再用碎片化 mp4（会导致部分播放器不出声）；每段正常封口写 moov
        self.assertNotIn("movflags=+frag_keyframe+empty_moov", cmd)
        # 视频也是 1 分钟分段 mp4，与音频同节奏、同起号
        self.assertEqual(cmd[-1], str(vdir / config.VIDEO_FILENAME))
        self.assertIn("-segment_format", cmd)
        self.assertEqual(cmd[cmd.index("-segment_format") + 1], "mp4")
        self.assertEqual(cmd.count("-segment_time"), 2)  # 音频段 + 视频段各一
        # 视频用 -map 0 拿全流，音频段输出在视频输出之前
        self.assertLess(cmd.index(str(room / config.SEGMENT_FILENAME)), cmd.index("-map"))

    def test_video_on_without_dir_stays_audio_only(self) -> None:
        room = Path("/tmp/audio/123")
        csv = room / config.SEGMENT_LIST_NAME
        cmd = _build_capture_cmd("http://x/index.m3u8", room, 1, csv, record_video=True, video_dir=None)
        self.assertNotIn("copy", cmd)


if __name__ == "__main__":
    unittest.main()
