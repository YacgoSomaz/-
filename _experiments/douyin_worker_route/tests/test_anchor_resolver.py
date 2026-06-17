"""anchor_resolver 单元测试：全程 mock HTTP，禁止访问真实抖音。

假 session 只实现 .get()，对未登记的 URL 直接 AssertionError——既能断言「跳转链路正确」，
也能在解析器越界请求站外地址时让测试立刻失败（SSRF 防护回归）。
"""

import unittest

from pipeline.anchor_resolver import (
    AnchorResolveError,
    ResolvedAnchor,
    resolve_anchor,
)


class FakeResponse:
    def __init__(self, status_code=200, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text


class FakeSession:
    """按 URL 路由返回预置响应；未登记的 URL 视为「不该被请求」。"""

    def __init__(self, routes):
        self.routes = routes
        self.requested = []
        self.headers = []
        self.closed = False

    def get(self, url, allow_redirects=False, timeout=None, headers=None, **_kw):
        self.requested.append(url)
        self.headers.append(headers or {})
        if url not in self.routes:
            raise AssertionError(f"解析器请求了未登记的 URL（疑似越界）: {url}")
        return self.routes[url]

    def close(self):
        self.closed = True


class ExplodingSession:
    """任何 .get() 都炸——用于验证 fetch_page=False 时绝不发起网络请求。"""

    def get(self, *_a, **_k):
        raise AssertionError("不应发起任何网络请求")

    def close(self):
        pass


def _redirect(location):
    return FakeResponse(status_code=302, headers={"Location": location})


_LIVE_PAGE = (
    '<html><script>{"roomId":"7412345678901234567",'
    '"nickname":"沐庭",'
    '"owner":{"avatar_thumb":{"url_list":["https://p.douyinpic.com/a.jpeg"]}}}'
    "</script></html>"
)


class ExtractionTests(unittest.TestCase):
    def test_share_text_extracts_short_link_then_follows_to_live_room(self):
        text = (
            "8- #在抖音，记录美好生活#【昆明老魏房介所｜沐庭】正在直播... "
            "https://v.douyin.com/EaqezBTIfE8/ 1@9.com :0pm"
        )
        session = FakeSession(
            {
                "https://v.douyin.com/EaqezBTIfE8/": _redirect(
                    "https://live.douyin.com/261378947940"
                ),
                "https://live.douyin.com/261378947940": FakeResponse(text=_LIVE_PAGE),
            }
        )

        result = resolve_anchor(text, session=session)

        self.assertEqual(result.source_url, "https://live.douyin.com/261378947940")
        self.assertEqual(result.web_id, "261378947940")
        self.assertEqual(result.room_id, "7412345678901234567")
        self.assertEqual(result.anchor_name, "沐庭")
        self.assertEqual(result.avatar_url, "https://p.douyinpic.com/a.jpeg")

    def test_noise_after_url_is_not_swallowed(self):
        # 邮箱样噪声 1@9.com 不是抖音域，绝不能被当成 URL 抓走。
        session = FakeSession(
            {"https://live.douyin.com/123456": FakeResponse(text="<html></html>")}
        )
        result = resolve_anchor(
            "看看 https://live.douyin.com/123456 还有 1@9.com", session=session
        )
        self.assertEqual(result.source_url, "https://live.douyin.com/123456")

    def test_name_falls_back_to_bracketed_share_text_when_page_blocked(self):
        text = "【夜话电台】正在直播 https://live.douyin.com/555"
        session = FakeSession(
            {"https://live.douyin.com/555": FakeResponse(text="<html>captcha</html>")}
        )
        result = resolve_anchor(text, session=session)
        self.assertEqual(result.anchor_name, "夜话电台")
        self.assertIsNone(result.room_id)


class DirectLinkTests(unittest.TestCase):
    def test_live_link_yields_web_id(self):
        session = FakeSession(
            {"https://live.douyin.com/261378947940": FakeResponse(text=_LIVE_PAGE)}
        )
        result = resolve_anchor("https://live.douyin.com/261378947940", session=session)
        self.assertEqual(result.web_id, "261378947940")
        self.assertEqual(result.room_id, "7412345678901234567")

    def test_cached_cookie_can_be_reused_for_richer_room_metadata(self):
        session = FakeSession(
            {"https://live.douyin.com/261378947940": FakeResponse(text=_LIVE_PAGE)}
        )
        result = resolve_anchor(
            "https://live.douyin.com/261378947940",
            session=session,
            cookie_header="ttwid=trusted",
        )
        self.assertEqual(result.anchor_name, "沐庭")
        self.assertEqual(session.headers[0]["Cookie"], "ttwid=trusted")

    def test_homepage_link_yields_sec_user_id(self):
        sec = "MS4wLjABAAAAabcdef-123_XYZ"
        url = f"https://www.douyin.com/user/{sec}"
        session = FakeSession({url: FakeResponse(text="<html></html>")})
        result = resolve_anchor(url, session=session)
        self.assertEqual(result.sec_user_id, sec)
        self.assertIsNone(result.web_id)

    def test_legacy_numeric_id_builds_live_url(self):
        session = FakeSession(
            {"https://live.douyin.com/261378947940": FakeResponse(text="<html></html>")}
        )
        result = resolve_anchor("261378947940", session=session)
        self.assertEqual(result.source_url, "https://live.douyin.com/261378947940")
        self.assertEqual(result.web_id, "261378947940")

    def test_reflow_share_url_query_yields_room_and_sec_uid(self):
        sec = "MS4wLjABAAAAqwerty_0099"
        url = (
            "https://webcast.amemv.com/webcast/reflow/7400000000000000000"
            f"?room_id=7400000000000000000&sec_user_id={sec}"
        )
        session = FakeSession({url: FakeResponse(text="<html></html>")})
        result = resolve_anchor(url, session=session)
        self.assertEqual(result.room_id, "7400000000000000000")
        self.assertEqual(result.sec_user_id, sec)


class SsrfGuardTests(unittest.TestCase):
    def test_off_domain_redirect_is_not_followed(self):
        session = FakeSession(
            {
                "https://v.douyin.com/EVIL/": _redirect("https://evil.example.com/x"),
                # evil 地址故意不登记：一旦被请求，FakeSession 会 AssertionError。
            }
        )
        result = resolve_anchor("https://v.douyin.com/EVIL/", session=session)

        self.assertNotIn("https://evil.example.com/x", session.requested)
        self.assertTrue(
            all("evil.example.com" not in u for u in session.requested)
        )
        # 落地停在最后一个合法 URL，结构化字段为空但不抛异常。
        self.assertEqual(result.source_url, "https://v.douyin.com/EVIL/")

    def test_redirect_loop_is_capped(self):
        # 自循环短链：必须在有限跳数内停下，不能无限请求。
        routes = {"https://v.douyin.com/LOOP/": _redirect("https://v.douyin.com/LOOP/")}
        session = FakeSession(routes)
        result = resolve_anchor("https://v.douyin.com/LOOP/", session=session)
        self.assertLessEqual(len(session.requested), 7)
        self.assertIsInstance(result, ResolvedAnchor)


class DegradationTests(unittest.TestCase):
    def test_network_error_keeps_structural_fields(self):
        class BoomSession:
            def get(self, *_a, **_k):
                raise TimeoutError("slow")

            def close(self):
                pass

        result = resolve_anchor(
            "https://live.douyin.com/261378947940", session=BoomSession()
        )
        # 网络挂了也要保住从 URL 直接解析出的 web_id。
        self.assertEqual(result.web_id, "261378947940")
        self.assertIsNone(result.room_id)

    def test_fetch_page_false_does_no_network(self):
        result = resolve_anchor(
            "https://live.douyin.com/261378947940",
            session=ExplodingSession(),
            fetch_page=False,
        )
        self.assertEqual(result.web_id, "261378947940")
        self.assertIsNone(result.room_id)

    def test_challenge_page_yields_no_network_fields(self):
        session = FakeSession(
            {
                "https://live.douyin.com/555": FakeResponse(
                    text="<html>滑块验证 verifycenter</html>"
                )
            }
        )
        result = resolve_anchor("https://live.douyin.com/555", session=session)
        self.assertEqual(result.web_id, "555")
        self.assertIsNone(result.anchor_name)
        self.assertIsNone(result.room_id)

    def test_ended_marker_sets_is_live_false(self):
        session = FakeSession(
            {
                "https://live.douyin.com/555": FakeResponse(
                    text='<html>{"roomId":"7"} 直播已结束</html>'
                )
            }
        )
        result = resolve_anchor("https://live.douyin.com/555", session=session)
        self.assertIs(result.is_live, False)

    def test_room_store_status_two_sets_is_live_true_and_parses_escaped_avatar(self):
        page = (
            r'<script>roomStore\":{\"roomInfo\":{\"room\":{\"status\":2},'
            r'\"anchor\":{\"nickname\":\"开播主播\",'
            r'\"avatar_thumb\":{\"url_list\":[\"https:\\/\\/p.test\\/avatar.jpeg\"]}}}}</script>'
        )
        session = FakeSession({"https://live.douyin.com/555": FakeResponse(text=page)})

        result = resolve_anchor("https://live.douyin.com/555", session=session)

        self.assertIs(result.is_live, True)
        self.assertEqual(result.anchor_name, "开播主播")
        self.assertEqual(result.avatar_url, "https://p.test/avatar.jpeg")

    def test_room_metadata_wins_over_inert_captcha_script_name(self):
        page = (
            '<script src="/captcha/verifycenter.js"></script>'
            '<script>{"roomId":"7412345678901234567","nickname":"正常主播",'
            '"owner":{"avatar_thumb":{"url_list":["https://p.test/a.jpeg"]}}}</script>'
        )
        session = FakeSession({"https://live.douyin.com/555": FakeResponse(text=page)})

        result = resolve_anchor("https://live.douyin.com/555", session=session)

        self.assertEqual(result.anchor_name, "正常主播")
        self.assertEqual(result.avatar_url, "https://p.test/a.jpeg")

    def test_placeholder_nickname_is_skipped_for_real_anchor_nickname(self):
        page = (
            '{"nickname":"$undefined","roomStore":{"roomInfo":{"room":{"status":2},'
            '"anchor":{"nickname":"真实主播"}}}}'
        )
        session = FakeSession({"https://live.douyin.com/555": FakeResponse(text=page)})

        result = resolve_anchor("https://live.douyin.com/555", session=session)

        self.assertEqual(result.anchor_name, "真实主播")


class BadInputTests(unittest.TestCase):
    def test_empty_input_raises(self):
        with self.assertRaises(AnchorResolveError):
            resolve_anchor("   ")

    def test_no_douyin_url_raises(self):
        with self.assertRaises(AnchorResolveError):
            resolve_anchor("随便一段话 https://example.com/foo 没有抖音链接")

    def test_autocreated_session_is_closed(self):
        # 不注入 session 时，解析器须自建并在用完后关闭，绝不外泄。
        captured = {}
        import pipeline.anchor_resolver as mod

        class TrackSession(FakeSession):
            def __init__(self):
                super().__init__(
                    {"https://live.douyin.com/9": FakeResponse(text="<html></html>")}
                )
                captured["session"] = self

        original = mod.requests.Session
        mod.requests.Session = TrackSession
        try:
            resolve_anchor("https://live.douyin.com/9")
        finally:
            mod.requests.Session = original
        self.assertTrue(captured["session"].closed)


if __name__ == "__main__":
    unittest.main()
