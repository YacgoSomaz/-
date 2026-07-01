import unittest
from unittest.mock import patch

from pipeline.runtime_health import ErrorRegistry, classify_room_page


class ClassifyRoomPageTests(unittest.TestCase):
    def test_live_room_page_is_room(self) -> None:
        html = 'xxx "roomId":"7412345678901234567" yyy' + "padding" * 100
        self.assertEqual(classify_room_page(html), "room")

    def test_roomstore_evidence_is_room(self) -> None:
        html = '... "roomStore":{...} "roomInfo":{...} ...' + "z" * 100
        self.assertEqual(classify_room_page(html), "room")

    def test_ended_stream_with_inert_captcha_is_not_challenge(self) -> None:
        """正常下播：大页面 + 残留 captcha 脚本 + 「直播已结束」→ ended，绝不是 challenge。"""
        html = ("本场直播已结束，感谢观看" + "正文" * 5000
                + '<script src="/captcha/verifyCenter.js"></script>')
        self.assertEqual(classify_room_page(html), "ended")

    def test_large_page_with_only_inert_captcha_is_unknown_not_challenge(self) -> None:
        """下播后无 roomId、无结束文案，但残留 captcha 脚本的大页面 → unknown，不触发风控冷却。"""
        html = "内容" * 40000 + '<script src="https://lf.../captcha_sdk.js"></script>'  # ~80KB，远超阈值
        self.assertGreater(len(html), 20000)
        self.assertEqual(classify_room_page(html), "unknown")

    def test_small_verify_intermediate_page_is_challenge(self) -> None:
        """真验证页：约 6KB 小中间页 + captcha SDK → challenge。"""
        html = "<html><body>" + "<div></div>" * 50 + 'captcha' + "</body></html>"
        self.assertTrue(len(html) < 20000)
        self.assertEqual(classify_room_page(html), "challenge")

    def test_visible_verify_text_is_challenge(self) -> None:
        """可见「安全验证」文案即使在大页面也判 challenge。"""
        html = "页头" * 6000 + "请完成安全验证后继续"
        self.assertEqual(classify_room_page(html), "challenge")

    def test_empty_is_unknown(self) -> None:
        self.assertEqual(classify_room_page(""), "unknown")


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
