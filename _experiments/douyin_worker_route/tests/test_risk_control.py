import unittest
from unittest.mock import Mock, patch

from pipeline.audio_capture import RiskControlChallenge, fetch_candidates
from pipeline.runtime_health import GlobalCooldown, classify_room_page
from run_worker import WorkerFetcher


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

        class _Session:
            def get(self, *_args, **_kwargs):
                return _Response()

        class _Fetcher:
            live_url = "https://live.douyin.com/"
            user_agent = "test"
            session = _Session()

            def __init__(self, _live_id):
                pass

        with (
            patch("liveMan.DouyinLiveWebFetcher", _Fetcher),
            patch("pipeline.browser_cookies.cached_cookie_header", return_value="ttwid=test"),
        ):
            with self.assertRaises(RiskControlChallenge):
                fetch_candidates("123")


class WorkerCookieTests(unittest.TestCase):
    def test_worker_without_cached_cookie_stays_quiet(self) -> None:
        with patch("pipeline.browser_cookies.cached_jar", return_value={}):
            worker = WorkerFetcher("123", Mock())

        self.assertEqual(worker.ttwid, "")


if __name__ == "__main__":
    unittest.main()
