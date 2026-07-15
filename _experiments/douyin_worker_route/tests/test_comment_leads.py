from pipeline import comment_leads, config
import inspect


def test_extract_aweme_id_from_video_url():
    assert (
        comment_leads.extract_aweme_id("https://www.douyin.com/video/7634508503374255738")
        == "7634508503374255738"
    )


def test_comment_capture_uses_a_visible_browser_by_default():
    assert inspect.signature(comment_leads.capture_video_comments).parameters["headed"].default is True


def test_extract_aweme_id_from_profile_url_vid_param():
    url = (
        "https://www.douyin.com/user/MS4wLjABAAAAAK1e5fp"
        "?from_tab_name=main&vid=7648570637980888686"
    )
    assert comment_leads.extract_aweme_id(url) == "7648570637980888686"
    assert comment_leads.extract_author_sec_uid(url) == "MS4wLjABAAAAAK1e5fp"


def test_extract_first_url_from_share_text():
    text = "来看看这个作品 https://www.douyin.com/video/7634508503374255738 复制口令"
    assert comment_leads.extract_first_url(text) == "https://www.douyin.com/video/7634508503374255738"


def test_normalize_comment_public_fields():
    row = comment_leads.normalize_comment(
        {
            "cid": "comment_1",
            "text": "想了解一下户型",
            "ip_label": "云南",
            "digg_count": 3,
            "user": {
                "nickname": "用户A",
                "sec_uid": "SEC_UID_1",
                "unique_id": "dy123",
                "signature": "关注本地房产",
            },
        },
        aweme_id="7634508503374255738",
        source_url="https://www.douyin.com/video/7634508503374255738",
    )

    assert row["comment_id"] == "comment_1"
    assert row["content"] == "想了解一下户型"
    assert row["comment_ip_location"] == "云南"
    assert row["commenter_profile_url"] == "https://www.douyin.com/user/SEC_UID_1"
    assert row["status"] == "待联系"


def test_normalize_comment_keeps_reply_parent_and_level():
    row = comment_leads.normalize_comment(
        {
            "cid": "reply_1",
            "text": "我也想了解",
            "user": {"nickname": "用户B", "sec_uid": "SEC_UID_2"},
        },
        aweme_id="7634508503374255738",
        source_url="https://www.douyin.com/video/7634508503374255738",
        parent_comment_id="comment_1",
        level=2,
    )

    assert row["parent_comment_id"] == "comment_1"
    assert row["level"] == 2


def test_normalize_comment_tree_keeps_embedded_replies():
    rows = comment_leads.normalize_comment_tree(
        {
            "cid": "parent_1",
            "text": "这个小区怎么样？",
            "user": {"nickname": "用户A", "sec_uid": "SEC_A"},
            "reply_comment": [
                {
                    "cid": "reply_1",
                    "text": "我也想了解",
                    "user": {"nickname": "用户B", "sec_uid": "SEC_B"},
                }
            ],
        },
        aweme_id="7634508503374255738",
        source_url="https://www.douyin.com/video/7634508503374255738",
    )

    assert [row["comment_id"] for row in rows] == ["parent_1", "reply_1"]
    assert rows[1]["parent_comment_id"] == "parent_1"
    assert rows[1]["level"] == 2


def test_reply_statistics_reports_embedded_and_remaining_reply_counts():
    stats = comment_leads.reply_statistics(
        [
            {
                "cid": "parent_1",
                "reply_comment_total": 3,
                "reply_comment": [{"cid": "reply_1"}],
            },
            {
                "cid": "parent_2",
                "reply_comment_total": 2,
                "reply_comment": [{"cid": "reply_2"}, {"cid": "reply_3"}],
            },
        ]
    )

    assert stats == {"reported": 5, "embedded": 3, "remaining": 2, "parent_ids": ["parent_1"]}


def test_reply_expand_label_excludes_the_plain_reply_action():
    assert comment_leads.is_reply_expand_label("展开5条回复") is True
    assert comment_leads.is_reply_expand_label("查看回复") is True
    assert comment_leads.is_reply_expand_label("回复") is False


def test_expand_comment_replies_uses_real_mouse_clicks():
    class Mouse:
        def __init__(self):
            self.clicks = []
            self.moves = []
            self.wheels = []

        def click(self, x, y):
            self.clicks.append((x, y))

        def move(self, x, y):
            self.moves.append((x, y))

        def wheel(self, x, y):
            self.wheels.append((x, y))

    class Page:
        def __init__(self):
            self.mouse = Mouse()
            self.targets = [{"x": 30, "y": 40}, None]

        def evaluate(self, _script):
            return self.targets.pop(0)

        def wait_for_timeout(self, _ms):
            return None

    page = Page()
    assert comment_leads._expand_comment_replies(page) == 1
    assert page.mouse.clicks == [(30, 40)]
    assert page.mouse.moves == [(30, 40)]
    assert page.mouse.wheels == [(0, 420)]


def test_reply_page_summary_keeps_parent_and_pagination_state():
    assert comment_leads.reply_page_summary(
        "parent_1", {"cursor": 30, "has_more": 1, "total": 5}, [{"cid": "reply_1"}, {"cid": "reply_2"}]
    ) == {"parent_comment_id": "parent_1", "rows": 2, "cursor": 30, "has_more": True, "total": 5}


def test_reply_expand_label_can_be_clicked_again_only_when_it_changes():
    assert comment_leads.should_expand_reply_label("展开5条回复", "展开5条回复") is False
    assert comment_leads.should_expand_reply_label("展开5条回复", "展开2条回复") is True


def test_visible_reply_control_labels_keep_only_short_reply_controls():
    class Page:
        def evaluate(self, _script):
            return ["回复", "展开2条回复", "查看全部回复", "很长的评论内容" * 5]

    assert comment_leads.visible_reply_control_labels(Page()) == ["回复", "展开2条回复", "查看全部回复"]


def test_reply_next_page_url_updates_only_cursor():
    url = "https://www.douyin.com/aweme/v1/web/comment/list/reply/?aweme_id=1&comment_id=2&cursor=0&count=3&a_bogus=keep"
    assert comment_leads.reply_next_page_url(url, 3) == (
        "https://www.douyin.com/aweme/v1/web/comment/list/reply/?aweme_id=1&comment_id=2&cursor=3&count=3&a_bogus=keep"
    )


def test_comment_capture_keeps_public_comments_without_profile_link():
    """A missing profile URL must not make a valid public comment disappear."""
    captured = []
    comment_leads._append_unique_rows(
        captured,
        [
            {
                "comment_id": "comment_without_profile",
                "content": "请问这个怎么收费？",
                "commenter_profile_url": "",
            }
        ],
        set(),
        10,
    )

    assert [row["comment_id"] for row in captured] == ["comment_without_profile"]


def test_monitor_and_lead_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMMENT_LEADS_JSON", tmp_path / "comment_leads.json")

    monitor = comment_leads.add_monitor(
        "https://www.douyin.com/video/7634508503374255738",
        owner="客服A",
        max_comments=20,
    )
    assert monitor["aweme_id"] == "7634508503374255738"
    assert comment_leads.list_monitors()[0]["owner"] == "客服A"

    row = comment_leads.normalize_comment(
        {
            "cid": "comment_1",
            "text": "想了解一下",
            "user": {"nickname": "用户A", "sec_uid": "SEC_UID_1"},
        },
        aweme_id=monitor["aweme_id"],
        source_url=monitor["target_url"],
    )
    result = comment_leads.ingest_rows([row, row], monitor_id=monitor["id"])

    assert result["inserted"] == 1
    assert result["total"] == 1
    assert comment_leads.list_leads()[0]["monitor_id"] == monitor["id"]


def test_ingest_keeps_multiple_comments_from_the_same_person(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMMENT_LEADS_JSON", tmp_path / "comment_leads.json")
    base = {"user": {"nickname": "用户A", "sec_uid": "SEC_UID_1"}}
    first = comment_leads.normalize_comment({**base, "cid": "comment_1", "text": "户型怎么选？"}, aweme_id="1", source_url="https://www.douyin.com/video/1")
    second = comment_leads.normalize_comment({**base, "cid": "comment_2", "text": "首付需要多少？"}, aweme_id="1", source_url="https://www.douyin.com/video/1")

    result = comment_leads.ingest_rows([first, second])

    assert result["inserted"] == 2
    assert len(comment_leads.list_leads()) == 2


def test_login_status_requires_a_verified_login_state(tmp_path, monkeypatch):
    profile_dir = tmp_path / "comment_browser_profile"
    profile_dir.mkdir()
    (profile_dir / "Preferences").write_text("{}", encoding="utf-8")
    state_path = tmp_path / "comment_login_state.json"
    monkeypatch.setattr(config, "COMMENT_LEADS_PROFILE_DIR", profile_dir)
    monkeypatch.setattr(config, "COMMENT_LEADS_LOGIN_STATE_JSON", state_path, raising=False)
    monkeypatch.setattr(comment_leads.browser_cookies, "shared_status", lambda: {"has_login": False, "browser": "msedge", "cookie_count": 0})

    assert comment_leads.login_status()["logged_in"] is False

    state_path.write_text('{"authenticated": true, "browser": "msedge"}', encoding="utf-8")
    assert comment_leads.login_status()["logged_in"] is False

    monkeypatch.setattr(comment_leads.browser_cookies, "shared_status", lambda: {"has_login": True, "browser": "msedge", "cookie_count": 12})
    status = comment_leads.login_status()
    assert status["logged_in"] is True
    assert status["browser"] == "msedge"


def test_add_monitor_treats_profile_url_as_profile_monitor_and_uses_profile_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMMENT_LEADS_JSON", tmp_path / "comment_leads.json")
    monkeypatch.setattr(config, "SHORT_VIDEO_PROFILE_CACHE_JSON", tmp_path / "short_video_profiles.json")
    sec_uid = "MS4wLjABAAAAAK1e5fp"
    config.SHORT_VIDEO_PROFILE_CACHE_JSON.write_text(
        '{"MS4wLjABAAAAAK1e5fp":{"profile":{"nickname":"昆明安心选房","avatar_url":"https://example.com/a.jpg"},"videos":[],"updated_ts":9999999999}}',
        encoding="utf-8",
    )

    monitor = comment_leads.add_monitor(
        f"https://www.douyin.com/user/{sec_uid}?from_tab_name=main&vid=7648570637980888686",
        max_videos=8,
    )

    assert monitor["id"] == f"profile_{sec_uid}"
    assert monitor["target_type"] == "profile"
    assert monitor["target_url"] == f"https://www.douyin.com/user/{sec_uid}?from_tab_name=main"
    assert monitor["aweme_id"] == "7648570637980888686"
    assert monitor["author_sec_uid"] == sec_uid
    assert monitor["author_name"] == "昆明安心选房"
    assert monitor["author_avatar"] == "https://example.com/a.jpg"
    assert monitor["max_videos"] == 8


def test_run_profile_monitor_resolves_recent_videos_and_ingests_comments(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMMENT_LEADS_JSON", tmp_path / "comment_leads.json")
    monkeypatch.setattr(config, "SHORT_VIDEO_PROFILE_CACHE_JSON", tmp_path / "short_video_profiles.json")
    sec_uid = "MS4wLjABAAAAAK1e5fp"
    monitor = comment_leads.add_monitor(
        f"https://www.douyin.com/user/{sec_uid}?from_tab_name=main",
        max_videos=2,
        max_comments=3,
    )

    def fake_resolve_profile(url, recent_count):
        assert url == f"https://www.douyin.com/user/{sec_uid}?from_tab_name=main"
        assert recent_count == 2
        return {
            "profile": {
                "sec_user_id": sec_uid,
                "nickname": "昆明安心选房",
                "avatar_url": "https://example.com/avatar.jpg",
            },
            "videos": [
                {"id": "111111111111", "url": "https://www.douyin.com/video/111111111111", "title": "作品一"},
                {"id": "222222222222", "url": "https://www.douyin.com/video/222222222222", "title": "作品二"},
            ],
            "warning": "",
        }

    def fake_capture_video_comments(url, *, max_comments=100, headed=False):
        aweme_id = comment_leads.extract_aweme_id(url)
        row = comment_leads.normalize_comment(
            {
                "cid": f"comment_{aweme_id}",
                "text": f"想了解 {aweme_id}",
                "user": {"nickname": "用户A", "sec_uid": f"SEC_{aweme_id}"},
            },
            aweme_id=aweme_id,
            source_url=url,
        )
        return comment_leads.CaptureResult(
            True,
            [row],
            {"source_url": url, "aweme_id": aweme_id, "video_title": f"视频 {aweme_id}"},
            "",
        )

    monkeypatch.setattr(comment_leads.short_video, "resolve_profile", fake_resolve_profile)
    monkeypatch.setattr(comment_leads, "capture_video_comments", fake_capture_video_comments)

    result = comment_leads.run_monitor(monitor["id"])

    assert result["ok"] is True
    assert result["captured"] == 2
    assert result["inserted"] == 2
    leads = comment_leads.list_leads()
    assert {lead["aweme_id"] for lead in leads} == {"111111111111", "222222222222"}
    saved_monitor = comment_leads.list_monitors()[0]
    assert saved_monitor["title"] == "昆明安心选房"
    assert saved_monitor["last_count"] == 2


def test_resolve_profile_works_only_lists_videos_without_collecting_comments(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMMENT_LEADS_JSON", tmp_path / "comment_leads.json")
    sec_uid = "MS4wLjABAAAAAK1e5fp"

    def fake_resolve_profile(url, recent_count):
        return {
            "profile": {
                "sec_user_id": sec_uid,
                "nickname": "昆明安心选房",
                "avatar_url": "https://example.com/avatar.jpg",
            },
            "videos": [
                {"id": "111111111111", "url": "https://www.douyin.com/video/111111111111", "title": "作品一"},
            ],
            "warning": "",
        }

    monkeypatch.setattr(comment_leads.short_video, "resolve_profile", fake_resolve_profile)

    result = comment_leads.resolve_profile_works(f"https://www.douyin.com/user/{sec_uid}?from_tab_name=main", max_videos=1)

    assert result["ok"] is True
    assert result["monitor"]["id"] == f"profile_{sec_uid}"
    assert result["profile"]["nickname"] == "昆明安心选房"
    assert result["videos"][0]["title"] == "作品一"
    assert comment_leads.list_leads() == []


def test_run_selected_videos_only_collects_selected_video_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMMENT_LEADS_JSON", tmp_path / "comment_leads.json")
    sec_uid = "MS4wLjABAAAAAK1e5fp"
    monitor = comment_leads.add_monitor(f"https://www.douyin.com/user/{sec_uid}?from_tab_name=main")

    def fake_capture_video_comments(url, *, max_comments=100, headed=False):
        aweme_id = comment_leads.extract_aweme_id(url)
        row = comment_leads.normalize_comment(
            {
                "cid": f"comment_{aweme_id}",
                "text": f"选中作品评论 {aweme_id}",
                "user": {"nickname": "用户A", "sec_uid": f"SEC_{aweme_id}"},
            },
            aweme_id=aweme_id,
            source_url=url,
        )
        return comment_leads.CaptureResult(True, [row], {"aweme_id": aweme_id, "source_url": url, "reported_total": 26}, "")

    monkeypatch.setattr(comment_leads, "capture_video_comments", fake_capture_video_comments)

    result = comment_leads.run_selected_videos(
        monitor["id"],
        [{"id": "333333333333", "url": "https://www.douyin.com/video/333333333333", "title": "只采这一条"}],
        max_comments=5,
    )

    assert result["ok"] is True
    assert result["captured"] == 1
    assert result["metadata"]["reported_total"] == 26
    leads = comment_leads.list_leads()
    assert len(leads) == 1
    assert leads[0]["aweme_id"] == "333333333333"
