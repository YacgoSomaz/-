from pipeline import comment_leads, config


def test_extract_aweme_id_from_video_url():
    assert (
        comment_leads.extract_aweme_id("https://www.douyin.com/video/7634508503374255738")
        == "7634508503374255738"
    )


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
        return comment_leads.CaptureResult(True, [row], {"aweme_id": aweme_id, "source_url": url}, "")

    monkeypatch.setattr(comment_leads, "capture_video_comments", fake_capture_video_comments)

    result = comment_leads.run_selected_videos(
        monitor["id"],
        [{"id": "333333333333", "url": "https://www.douyin.com/video/333333333333", "title": "只采这一条"}],
        max_comments=5,
    )

    assert result["ok"] is True
    assert result["captured"] == 1
    leads = comment_leads.list_leads()
    assert len(leads) == 1
    assert leads[0]["aweme_id"] == "333333333333"
