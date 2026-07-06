import unittest
from unittest.mock import patch

from pipeline.audio_capture import RiskControlChallenge, fetch_candidates
from pipeline.runtime_health import GlobalCooldown, classify_room_page


class RoomPageClassificationTests(unittest.TestCase):
    def test_detects_captcha_wall_instead_of_treating_it_as_offline(self) -> None:
        html = "<html><script>window.location='/captcha/verify'</script>login</html>"

        self.assertEqual(classify_room_page(html), "challenge")

    def test_normal_room_page_is_not_a_challenge(self) -> None:
        html = '<script>roomId\\\\":\\\\"123456\\\\"</script>'

        self.assertEqual(classify_room_page(html), "room")

    def test_normal_room_page_with_captcha_bundle_is_not_a_challenge(self) -> None:
        html = (
            '<script src="/captcha/verifycenter.js"></script>'
            '<script>roomId\\\\":\\\\"123456\\\\";'
            'window.stream="https://example.test/live/index.m3u8?k=signed"</script>'
        )

        self.assertEqual(classify_room_page(html), "room")

    def test_stream_page_with_captcha_bundle_is_not_a_challenge(self) -> None:
        html = (
            '<script src="/captcha/index.js"></script>'
            'https://example.test/live/index.m3u8?sign=trusted'
        )

        self.assertEqual(classify_room_page(html), "room")


class GlobalCooldownTests(unittest.TestCase):
    def test_trigger_blocks_until_deadline_and_manual_clear_releases(self) -> None:
        cooldown = GlobalCooldown()
        with patch("pipeline.runtime_health.time.time", return_value=100):
            cooldown.trigger(900, "检测到抖音验证页")

        with patch("pipeline.runtime_health.time.time", return_value=200):
            self.assertTrue(cooldown.active())
            self.assertEqual(cooldown.remaining_sec(), 800)
            self.assertEqual(cooldown.snapshot()["reason"], "检测到抖音验证页")

        cooldown.clear()
        self.assertFalse(cooldown.active())
        self.assertEqual(cooldown.remaining_sec(), 0)


class AudioRiskControlTests(unittest.TestCase):
    def test_audio_fetch_raises_distinct_challenge_error(self) -> None:
        class _Response:
            text = "<html>captcha verifycenter</html>"

            def raise_for_status(self):
                return None

        class _Session:
            last_url = ""
            last_headers = {}

            def get(self, url, *, headers, timeout):
                self.last_url = url
                self.last_headers = headers
                return _Response()

        session = _Session()

        with patch("pipeline.audio_capture.requests.Session", return_value=session), patch(
            "pipeline.browser_cookies.cached_cookie_header", return_value="ttwid=test"
        ):
            with self.assertRaises(RiskControlChallenge):
                fetch_candidates("123")

        self.assertEqual(session.last_url, "https://live.douyin.com/123")
        self.assertEqual(session.last_headers["cookie"], "ttwid=test")
        self.assertEqual(session.last_headers["Referer"], "https://live.douyin.com/")

    def test_audio_fetch_extracts_m3u8_without_vendor_fetcher(self) -> None:
        class _Response:
            text = 'window.stream="https://pull.example/live/index.m3u8?sign=abc"'

            def raise_for_status(self):
                return None

        class _Session:
            def get(self, *_args, **_kwargs):
                return _Response()

        with patch("pipeline.audio_capture.requests.Session", return_value=_Session()), patch(
            "pipeline.browser_cookies.cached_cookie_header", return_value="ttwid=test"
        ):
            cands, raw_count = fetch_candidates("456")

        self.assertEqual(raw_count, 1)
        self.assertEqual(cands, ["https://pull.example/live/index.m3u8?sign=abc"])


if __name__ == "__main__":
    unittest.main()
