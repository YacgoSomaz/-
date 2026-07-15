from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from pipeline import config, short_video


def test_fetch_next_profile_page_requests_a_full_batch() -> None:
    captured: list[str] = []

    class _Page:
        def evaluate(self, _script: str, url: str):
            captured.append(url)
            return {"aweme_list": []}

    short_video._fetch_aweme_post_page(
        _Page(),
        "https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id=SEC_UID&count=18",
        "123456",
    )

    query = parse_qs(urlparse(captured[0]).query)
    assert query["sec_user_id"] == ["SEC_UID"]
    assert query["max_cursor"] == ["123456"]
    assert query["count"] == ["35"]


def test_short_video_login_requires_a_real_session_cookie() -> None:
    assert short_video._has_douyin_login_cookie(
        {"ttwid": "trust-only", "passport_csrf_token": "csrf-only"}
    ) is False
    assert short_video._has_douyin_login_cookie({"sessionid": "active-session"}) is True
    assert short_video._has_douyin_login_cookie({"passport_auth_mix_state": "1"}) is True


def test_short_video_uses_the_shared_douyin_cookie_store(monkeypatch) -> None:
    monkeypatch.setattr(short_video.browser_cookies, "cached_jar", lambda: {"sessionid": "shared"})
    assert short_video._short_video_cookie_jar() == {"sessionid": "shared"}


def test_parse_profile_url_from_share_text() -> None:
    text = (
        "看看这个主页 https://www.douyin.com/user/"
        "MS4wLjABAAAAznjboVI88f4Vzz63RRoR8QuzRNdJkqthtDtGg8K4IpW46qLKJ6EzvxQwh15h9F8y"
        "?from_tab_name=main"
    )
    parsed = short_video.parse_profile_url(text)
    assert parsed["platform"] == "douyin"
    assert parsed["sec_user_id"].startswith("MS4wLjABAAAA")
    assert "from_tab_name=main" in parsed["source_url"]


def test_parse_profile_url_tolerates_wrapped_url() -> None:
    text = (
        "https://www.douyin.com/user/MS4wLjABAAAAznjboVI88f4Vzz63RRoR8Q\n"
        "uzRNdJkqthtDtGg8K4IpW46qLKJ6EzvxQwh15h9F8y?\n"
        "from_tab_name=main"
    )
    parsed = short_video.parse_profile_url(text)
    assert parsed["sec_user_id"].startswith("MS4wLjABAAAAznjbo")
    assert "from_tab_name=main" in parsed["source_url"]


def test_parse_profile_url_drops_video_context_query() -> None:
    parsed = short_video.parse_profile_url(
        "https://www.douyin.com/user/MS4wLjABAAAAabc?from_tab_name=main&vid=7654923211277140902&source=copy"
    )
    assert parsed["source_url"] == "https://www.douyin.com/user/MS4wLjABAAAAabc?from_tab_name=main"


def test_parse_video_card_text() -> None:
    title, likes, pinned = short_video.parse_video_text(
        "置顶\n55\n\n尊敬的业主们，欢迎收看您的108㎡三房两厅"
    )
    assert pinned is True
    assert likes == 55
    assert title.startswith("尊敬的业主们")


def test_resolve_profile_without_browser_fetch() -> None:
    result = short_video.resolve_profile(
        "https://www.douyin.com/user/MS4wLjABAAAAabc?from_tab_name=main",
        fetch_videos=False,
    )
    assert result["profile"]["sec_user_id"] == "MS4wLjABAAAAabc"
    assert result["videos"] == []


def test_extract_video_urls_deduplicates() -> None:
    text = "\n".join([
        "https://www.douyin.com/video/123",
        "重复 https://www.douyin.com/video/123",
        "https://v.douyin.com/abcDEF/",
    ])
    assert short_video.extract_video_urls(text) == [
        "https://www.douyin.com/video/123",
        "https://v.douyin.com/abcDEF/",
    ]


def test_create_short_video_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_JOBS_JSON", tmp_path / "jobs.json")
    profile = "https://www.douyin.com/user/MS4wLjABAAAAabc?from_tab_name=main"
    job = short_video.create_job(
        profile_url=profile,
        sec_user_id="MS4wLjABAAAAabc",
        recent_count=10,
        videos=[{"title": "爆款样片", "url": "https://www.douyin.com/video/456"}],
    )
    assert job["selection_mode"] == "manual"
    assert job["video_count"] == 1
    assert short_video.list_jobs()[0]["id"] == job["id"]


def test_create_recent_job_without_manual_videos(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_JOBS_JSON", tmp_path / "jobs.json")
    profile = "https://www.douyin.com/user/MS4wLjABAAAAabc"
    job = short_video.create_job(profile_url=profile, sec_user_id="", recent_count=25)
    assert job["selection_mode"] == "recent"
    assert job["video_count"] == 25


def test_resolve_profile_accepts_50_recent_count() -> None:
    result = short_video.resolve_profile(
        "https://www.douyin.com/user/MS4wLjABAAAAabc?from_tab_name=main",
        recent_count=50,
        fetch_videos=False,
    )
    assert result["profile"]["sec_user_id"] == "MS4wLjABAAAAabc"
    assert result["videos"] == []


def test_resolve_profile_accepts_arbitrary_incremental_target() -> None:
    result = short_video.resolve_profile(
        "https://www.douyin.com/user/MS4wLjABAAAAabc?from_tab_name=main",
        recent_count=37,
        fetch_videos=False,
    )
    assert result["profile"]["sec_user_id"] == "MS4wLjABAAAAabc"
    assert result["videos"] == []


def test_short_video_key_dedupes_query_variants() -> None:
    a = {"url": "https://www.douyin.com/video/123456?source=Baiduspider"}
    b = {"url": "https://www.douyin.com/video/123456?from=profile"}
    assert short_video._video_key(a) == short_video._video_key(b) == "123456"
    assert short_video._merge_unique_videos([a], [b]) == [a]


def test_short_video_cache_merge_does_not_shrink() -> None:
    cached = [
        {"id": "1", "url": "https://www.douyin.com/video/1"},
        {"id": "2", "url": "https://www.douyin.com/video/2"},
    ]
    fresh = [{"url": "https://www.douyin.com/video/2?from=refresh"}]
    merged = short_video._merge_unique_videos(fresh, cached)
    assert [short_video._video_key(v) for v in merged] == ["2", "1"]


def test_limited_profile_warning_explains_weak_cookie_limit() -> None:
    msg = short_video._limited_profile_warning(20, 25, {"ttwid": "trust-only"})
    assert "前 20 条作品" in msg
    assert "登录授权" in msg


def test_scroll_until_enough_keeps_scrolling_until_target(monkeypatch) -> None:  # noqa: ANN001
    class _Page:
        def __init__(self) -> None:
            self.calls = 0
            self.wheels = 0
            self.waits = 0

        def eval_on_selector_all(self, selector, script):  # noqa: ANN001
            self.calls += 1
            return 3 if self.calls == 1 else 12

        def wait_for_timeout(self, ms):  # noqa: ANN001
            self.waits += 1

    page = _Page()
    page.mouse = SimpleNamespace(wheel=lambda _x, _y: setattr(page, "wheels", page.wheels + 1))
    monkeypatch.setattr(short_video, "_scroll_profile_page", lambda _page, _target: 12)
    short_video._scroll_until_enough(page, 10)
    assert page.calls == 2
    assert page.waits == 1


def test_clean_rendered_videos_ignores_seo_links_without_cover() -> None:
    items = [
        {
            "url": "https://www.douyin.com/video/7504590418484251963",
            "text": "置顶\n41\n\n尊敬的各位业主，欢迎来到您的户型鉴赏",
            "cover_url": "https://p3-pc-sign.douyinpic.com/cover.jpeg",
            "width": 190,
            "height": 283,
        },
        {
            "url": "https://www.douyin.com/video/7592814761503395078?source=Baiduspider",
            "text": "口子窖或交出上市以来最差年报",
            "cover_url": "",
            "width": 511,
            "height": 16,
        },
    ]
    videos = short_video._clean_rendered_videos(items)
    assert len(videos) == 1
    assert videos[0]["id"] == "7504590418484251963"
    assert videos[0]["cover_url"]


def test_resolve_profile_falls_back_to_cached_videos(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_PROFILE_CACHE_JSON", tmp_path / "short_cache.json")
    profile_url = "https://www.douyin.com/user/MS4wLjABAAAAabc"
    sec_uid = "MS4wLjABAAAAabc"
    short_video._write_profile_cache(
        sec_uid,
        {
            "profile": {
                "source_url": profile_url,
                "sec_user_id": sec_uid,
                "nickname": "缓存主播",
                "avatar_url": "https://example.com/avatar.jpg",
            },
            "videos": [
                {
                    "id": "123",
                    "title": "缓存作品",
                    "url": "https://www.douyin.com/video/123",
                    "cover_url": "https://example.com/cover.jpg",
                    "like_count": 8,
                    "pinned": False,
                    "source": "profile",
                }
            ],
        },
    )

    def _fail_render(*args, **kwargs):
        raise RuntimeError("browser failed")

    monkeypatch.setattr(short_video, "_render_profile", _fail_render)
    result = short_video.resolve_profile(profile_url, 5)
    assert result["profile"]["nickname"] == "缓存主播"
    assert result["videos"][0]["title"] == "缓存作品"
    assert "缓存" in result["warning"]


def test_resolve_profile_uses_fresh_cache_before_browser(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_PROFILE_CACHE_JSON", tmp_path / "short_cache.json")
    profile_url = "https://www.douyin.com/user/MS4wLjABAAAAabc"
    sec_uid = "MS4wLjABAAAAabc"
    short_video._write_profile_cache(
        sec_uid,
        {
            "profile": {"source_url": profile_url, "sec_user_id": sec_uid, "nickname": "秒开主播"},
            "videos": [
                {
                    "id": str(i),
                    "title": f"缓存作品{i}",
                    "url": f"https://www.douyin.com/video/{i}",
                    "cover_url": f"https://example.com/{i}.jpg",
                    "like_count": i,
                    "pinned": False,
                    "source": "profile",
                }
                for i in range(1, 6)
            ],
        },
    )

    def _should_not_render(*args, **kwargs):
        raise AssertionError("fresh cache should avoid browser rendering")

    monkeypatch.setattr(short_video, "_render_profile", _should_not_render)
    result = short_video.resolve_profile(profile_url, 5)
    assert result["profile"]["nickname"] == "秒开主播"
    assert len(result["videos"]) == 5
    assert "缓存" in result["warning"]


def test_iter_resolve_profile_events_streams_cached_videos(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_PROFILE_CACHE_JSON", tmp_path / "short_cache.json")
    profile_url = "https://www.douyin.com/user/MS4wLjABAAAAabc"
    sec_uid = "MS4wLjABAAAAabc"
    short_video._write_profile_cache(
        sec_uid,
        {
            "profile": {"source_url": profile_url, "sec_user_id": sec_uid, "nickname": "流式主播"},
            "videos": [
                {
                    "id": str(i),
                    "title": f"流式作品{i}",
                    "url": f"https://www.douyin.com/video/{i}",
                    "cover_url": f"https://example.com/{i}.jpg",
                    "like_count": i,
                    "pinned": False,
                    "source": "profile",
                }
                for i in range(1, 6)
            ],
        },
    )
    events = list(short_video.iter_resolve_profile_events(profile_url, 5))
    assert any(event["type"] == "status" and "缓存" in event["message"] for event in events)
    data_events = [event for event in events if event["type"] != "status"]
    assert [event["type"] for event in data_events] == ["profile", "video", "video", "video", "video", "video", "warning", "done"]
    assert data_events[1]["video"]["title"] == "流式作品1"


def test_iter_resolve_profile_events_degrades_browser_failure_to_warning(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_PROFILE_CACHE_JSON", tmp_path / "short_cache.json")
    profile_url = "https://www.douyin.com/user/MS4wLjABAAAAabc"

    def _fail_render(*args, **kwargs):
        raise RuntimeError("browser failed")

    monkeypatch.setattr(short_video, "_render_profile_events", _fail_render)
    events = list(short_video.iter_resolve_profile_events(profile_url, 5))
    assert not any(event["type"] == "error" for event in events)
    assert any(event["type"] == "warning" and "浏览器读取作品失败" in event["message"] for event in events)
    assert events[-1] == {"type": "done", "count": 0}


def test_analyze_positioning_outputs_benchmark_direction() -> None:
    result = short_video.analyze_positioning(
        {"nickname": "大华锦绣麓城直播号", "sec_user_id": "MS4w"},
        [
            {
                "title": "尊敬的各位业主，欢迎来到您的户型鉴赏 #大华锦绣麓城 #房地产",
                "like_count": 41,
                "pinned": True,
            },
            {
                "title": "首付18万，入住低密小高层，昆明买房先看区位和户型",
                "like_count": 3,
                "pinned": False,
            },
        ],
    )

    assert result["track"] == "房产置业"
    assert result["confidence"] >= 50
    assert result["benchmark_accounts"]
    assert result["benchmark_keywords"]
    assert result["monitoring_plan"]
    assert result["metrics"]["video_count"] == 2


def test_create_benchmark_direction_and_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_BENCHMARKS_JSON", tmp_path / "benchmarks.json")
    positioning = {
        "track": "房产置业",
        "profile": {"nickname": "本号", "sec_user_id": "source_sec"},
        "benchmark_keywords": ["房产置业", "昆明买房"],
    }
    direction = short_video.create_benchmark(
        source_profile=positioning["profile"],
        positioning=positioning,
        candidate={"name": "昆明买房赛道对标账号", "reason": "用于对比封面和选题"},
    )
    account = short_video.create_benchmark(
        source_profile=positioning["profile"],
        positioning=positioning,
        profile_url="https://www.douyin.com/user/MS4wLjABAAAAabc?from_tab_name=main",
    )

    rows = short_video.list_benchmarks()
    assert rows[0]["id"] == account["id"]
    assert rows[0]["type"] == "account"
    assert rows[0]["status"] == "待监测"
    assert rows[0]["sec_user_id"] == "MS4wLjABAAAAabc"
    assert rows[1]["id"] == direction["id"]
    assert rows[1]["type"] == "direction"
    assert rows[1]["status"] == "待搜索"
    assert rows[1]["keywords"] == ["房产置业", "昆明买房"]


def test_refresh_benchmark_search_generates_search_candidates(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_BENCHMARKS_JSON", tmp_path / "benchmarks.json")
    direction = short_video.create_benchmark(
        source_profile={"nickname": "本号", "sec_user_id": "source_sec"},
        positioning={
            "track": "房产置业",
            "profile": {"nickname": "本号", "sec_user_id": "source_sec"},
            "benchmark_keywords": ["昆明买房", "户型设计"],
        },
        candidate={"name": "昆明买房赛道对标账号"},
    )

    refreshed = short_video.refresh_benchmark_search(direction["id"])

    assert refreshed["status"] == "待筛选"
    assert refreshed["search_candidates"]
    assert refreshed["search_candidates"][0]["kind"] == "search"
    assert refreshed["search_candidates"][0]["search_mode"] == "content"
    assert "douyin.com/search" in refreshed["search_candidates"][0]["search_url"]
    assert "type=general" in refreshed["search_candidates"][0]["search_url"]
    assert "last_checked_ts" in refreshed


def test_search_benchmark_accounts_writes_candidates(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_BENCHMARKS_JSON", tmp_path / "benchmarks.json")
    direction = short_video.create_benchmark(
        source_profile={"nickname": "本号", "sec_user_id": "source_sec"},
        positioning={
            "track": "房产置业",
            "profile": {"nickname": "本号", "sec_user_id": "source_sec"},
            "benchmark_keywords": ["昆明买房"],
        },
        candidate={"name": "昆明买房赛道对标账号"},
    )

    def _fake_render(keyword: str, limit: int = 8):
        return [
            {
                "kind": "account",
                "account_name": "昆明房产样本号",
                "profile_url": "https://www.douyin.com/user/MS4wLjABAAAAbench",
                "sec_user_id": "MS4wLjABAAAAbench",
                "avatar_url": "https://example.com/a.jpg",
                "reason": f"来自 {keyword} 搜索",
                "status": "候选账号",
            }
        ]

    monkeypatch.setattr(short_video, "_render_search_work_accounts", _fake_render)
    refreshed = short_video.search_benchmark_accounts(direction["id"])

    assert refreshed["status"] == "候选待选"
    assert refreshed["account_candidates"][0]["account_name"] == "昆明房产样本号"
    assert refreshed["account_candidates"][0]["profile_url"].endswith("MS4wLjABAAAAbench")


def test_recommend_benchmark_accounts_upserts_direction_and_searches(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_BENCHMARKS_JSON", tmp_path / "benchmarks.json")
    calls: list[tuple[str, int]] = []

    def _fake_render(keyword: str, limit: int = 8):
        calls.append((keyword, limit))
        return [
            {
                "kind": "account",
                "account_name": "昆明改善房样本号",
                "profile_url": "https://www.douyin.com/user/MS4wLjABAAAAbench1",
                "sec_user_id": "MS4wLjABAAAAbench1",
                "avatar_url": "https://example.com/bench.jpg",
                "reason": f"来自 {keyword} 搜索",
                "status": "候选账号",
            }
        ]

    monkeypatch.setattr(short_video, "_render_search_work_accounts", _fake_render)
    row = short_video.recommend_benchmark_accounts(
        source_profile={"nickname": "本号", "sec_user_id": "source_sec"},
        positioning={
            "profile": {"nickname": "本号", "sec_user_id": "source_sec"},
            "track": "房产置业",
            "benchmark_keywords": ["昆明改善房", "大横厅"],
        },
        limit=6,
    )

    assert row["type"] == "direction"
    assert row["status"] == "候选待选"
    assert row["account_name"] == "房产置业 对标账号推荐"
    assert row["keywords"] == ["昆明改善房", "大横厅"]
    assert row["account_candidates"][0]["account_name"] == "昆明改善房样本号"
    assert calls == [("昆明改善房", 6)]

    again = short_video.recommend_benchmark_accounts(
        source_profile={"nickname": "本号", "sec_user_id": "source_sec"},
        positioning={
            "profile": {"nickname": "本号", "sec_user_id": "source_sec"},
            "track": "房产置业",
            "benchmark_keywords": ["昆明改善房", "大横厅"],
        },
        limit=6,
    )
    rows = short_video.list_benchmarks()
    assert again["id"] == row["id"]
    assert len(rows) == 1


def test_read_search_work_accounts_extracts_author_from_general_result() -> None:
    class _Page:
        def eval_on_selector_all(self, selector, script):  # noqa: ANN001
            assert 'a[href*="/video/"]' in selector
            return [
                {
                    "video_url": "https://www.douyin.com/video/7654321?previous_page=search",
                    "profile_url": "https://www.douyin.com/user/MS4wLjABAAAAbench?from_tab_name=main",
                    "author_text": "昆明改善房",
                    "text": "置顶\n1.8万\n昆明改善大横厅真实案例，四代住宅采光好",
                    "cover_url": "https://example.com/cover.jpg",
                    "avatar_url": "https://example.com/avatar.jpg",
                },
                {
                    "video_url": "https://www.douyin.com/video/7654322",
                    "profile_url": "https://www.douyin.com/user/MS4wLjABAAAAbench",
                    "author_text": "昆明改善房",
                    "text": "重复作者应去重",
                },
            ]

    result = short_video._read_search_work_accounts(_Page(), "昆明改善房", limit=8)

    assert len(result) == 1
    assert result[0]["source"] == "content_search"
    assert result[0]["account_name"] == "昆明改善房"
    assert result[0]["profile_url"].endswith("MS4wLjABAAAAbench?from_tab_name=main")
    assert result[0]["representative_work"]["url"] == "https://www.douyin.com/video/7654321"
    assert result[0]["representative_work"]["like_count"] == 18000
    assert "大横厅" in result[0]["representative_work"]["title"]


def test_download_cover_asset_caches_by_account_and_video(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_ASSET_DIR", tmp_path / "assets")

    class _Resp:
        headers = {"Content-Type": "image/jpeg"}
        content = b"\xff\xd8cover-bytes"

        def raise_for_status(self) -> None:
            return None

    calls: list[str] = []

    def _fake_get(url: str, **kwargs):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(short_video.requests, "get", _fake_get)
    result = short_video.download_video_cover_asset(
        {"sec_user_id": "source_sec"},
        {"id": "123", "cover_url": "https://example.com/cover.jpg"},
    )
    again = short_video.download_video_cover_asset(
        {"sec_user_id": "source_sec"},
        {"id": "123", "cover_url": "https://example.com/cover.jpg"},
    )

    assert result["ok"] is True
    assert result["path"].endswith("source_sec\\123\\cover.jpg") or result["path"].endswith("source_sec/123/cover.jpg")
    assert Path(result["path"]).read_bytes() == b"\xff\xd8cover-bytes"
    assert again["cached"] is True
    assert calls == ["https://example.com/cover.jpg"]


def test_download_mp3_asset_extracts_from_resolved_play_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_ASSET_DIR", tmp_path / "assets")
    commands: list[list[str]] = []

    def _fake_resolve(url: str) -> str:
        assert url == "https://www.douyin.com/video/456"
        return "https://play.example.com/video.mp4"

    def _fake_run(cmd, **kwargs):
        commands.append([str(x) for x in cmd])
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"mp3-bytes" * 200)

        class _Proc:
            returncode = 0
            stderr = ""

        return _Proc()

    monkeypatch.setattr(short_video, "resolve_video_play_url", _fake_resolve)
    monkeypatch.setattr(short_video, "_download_video_mp3_with_ytdlp", lambda *args, **kwargs: None)
    monkeypatch.setattr(short_video.subprocess, "run", _fake_run)
    result = short_video.download_video_mp3_asset(
        {"sec_user_id": "source_sec"},
        {"id": "456", "url": "https://www.douyin.com/video/456"},
    )

    assert result["ok"] is True
    assert result["path"].endswith("source_sec\\456\\audio.mp3") or result["path"].endswith("source_sec/456/audio.mp3")
    assert Path(result["path"]).read_bytes().startswith(b"mp3-bytes")
    assert commands
    assert "https://play.example.com/video.mp4" in commands[0]
    assert "-vn" in commands[0]


def test_extract_play_urls_from_aweme_payload() -> None:
    payload = {
        "aweme_detail": {
            "video": {
                "play_addr": {
                    "url_list": [
                        "https://v1.example.com/video.mp4",
                        "https://v2.example.com/video.mp4",
                    ]
                }
            }
        }
    }

    urls = short_video._extract_play_urls_from_aweme_payload(payload)

    assert urls == [
        "https://v1.example.com/video.mp4",
        "https://v2.example.com/video.mp4",
    ]


def test_videos_from_aweme_list_preserves_play_url() -> None:
    videos = short_video._videos_from_aweme_list([
        {
            "aweme_id": "789",
            "desc": "样板间讲解",
            "video": {
                "cover": {"url_list": ["https://example.com/cover.jpg"]},
                "play_addr": {"url_list": ["https://example.com/play.mp4"]},
            },
            "statistics": {"digg_count": 12},
        }
    ])

    assert videos[0]["id"] == "789"
    assert videos[0]["cover_url"] == "https://example.com/cover.jpg"
    assert videos[0]["play_url"] == "https://example.com/play.mp4"


def test_score_short_video_work_normalizes_ai_result(monkeypatch) -> None:
    def fake_ai(task: str, payload: dict, fallback: dict) -> dict:
        assert task == "score"
        assert "房产短视频" in payload["available_templates"]
        assert payload["work"]["title"] == "97平三房两厅户型鉴赏"
        return {
            "overall_score": 82,
            "prediction_bucket": "高潜力",
            "confidence": 0.76,
            "template": "房产短视频",
            "dimensions": [
                {
                    "name": "开头钩子",
                    "score": 4,
                    "max_score": 5,
                    "evidence": "前3秒直给户型和面积",
                    "suggestion": "增加价格冲突",
                }
            ],
            "highlights": ["户型卖点明确"],
            "problems": ["行动引导偏弱"],
            "rewrite_suggestions": ["开头加入本地人群痛点"],
            "compliance_flags": ["限时低价需谨慎表达"],
        }

    monkeypatch.setattr(short_video, "_short_video_ai_json", fake_ai)

    result = short_video.score_short_video_work(
        {
            "title": "97平三房两厅户型鉴赏",
            "cover_description": "封面展示大横厅和女主播",
            "transcript": "这套房适合刚需家庭，三房两厅，南北通透。",
            "like_count": 41,
            "comment_count": 3,
        },
        account_history=[{"title": "108平三房", "like_count": 55}],
        template="房产短视频",
    )

    assert result["overall_score"] == 82
    assert result["prediction_bucket"] == "高潜力"
    assert result["template"] == "房产短视频"
    assert result["dimensions"][0]["name"] == "开头钩子"
    assert result["compliance_flags"] == ["限时低价需谨慎表达"]


def test_predict_short_video_performance_returns_relative_bucket(monkeypatch) -> None:
    def fake_ai(task: str, payload: dict, fallback: dict) -> dict:
        assert task == "predict"
        assert payload["account_history"][0]["like_count"] == 55
        return {
            "prediction_bucket": "中高潜力",
            "confidence": 0.68,
            "reasons": ["比账号历史中位数钩子更强"],
            "similar_samples": [{"title": "108平三房", "reason": "同户型主题"}],
            "may_win": ["标题更具体"],
            "may_lose": ["评论引导不足"],
        }

    monkeypatch.setattr(short_video, "_short_video_ai_json", fake_ai)
    result = short_video.predict_short_video_performance(
        {"title": "121平大横厅", "transcript": "大横厅采光很好"},
        account_history=[{"title": "108平三房", "like_count": 55}],
    )

    assert result["prediction_bucket"] == "中高潜力"
    assert "predicted_views" not in result
    assert result["similar_samples"][0]["title"] == "108平三房"


def test_learn_and_retro_short_video_workflows(monkeypatch) -> None:
    def fake_ai(task: str, payload: dict, fallback: dict) -> dict:
        if task == "learn":
            return {
                "opening_patterns": ["户型面积前置"],
                "title_patterns": ["面积 + 户型 + 区域"],
                "cover_patterns": ["大字标题叠加房源画面"],
                "selling_points": ["本地刚需"],
                "action_guides": ["评论区咨询"],
                "hit_commonalities": ["封面信息密度高"],
                "low_performance_issues": ["没有明确咨询入口"],
                "reusable_script_templates": ["先报户型，再给适合人群"],
            }
        if task == "retro":
            return {
                "accuracy": "基本准确",
                "bias_reason": "实际互动低于预期",
                "overestimated_reasons": ["评论引导弱"],
                "underestimated_reasons": [],
                "dimension_adjustments": ["提高互动引导权重"],
                "next_adjustments": ["下次观察收藏和评论"],
            }
        return fallback

    monkeypatch.setattr(short_video, "_short_video_ai_json", fake_ai)

    learned = short_video.learn_from_benchmark_account(
        {"nickname": "昆明牛肝菌"},
        [{"title": "大横厅", "transcript": "121平大横厅"}],
    )
    retro = short_video.retro_short_video_prediction(
        prediction={"prediction_bucket": "高潜力", "confidence": 0.7},
        actual_metrics={"like_count": 13, "comment_count": 0},
        work={"title": "大横厅"},
    )

    assert learned["opening_patterns"] == ["户型面积前置"]
    assert learned["reusable_script_templates"]
    assert retro["accuracy"] == "基本准确"
    assert retro["next_adjustments"] == ["下次观察收藏和评论"]


def test_score_short_video_work_falls_back_when_ai_json_is_invalid(monkeypatch) -> None:
    monkeypatch.setattr(
        short_video.ai_report,
        "load_config",
        lambda: SimpleNamespace(ready=True, base_url="https://example.com", api_key="k", model="m", timeout_sec=1),
    )
    monkeypatch.setattr(short_video.ai_report, "_chat_completion", lambda *args, **kwargs: "这不是 JSON")

    result = short_video.score_short_video_work(
        {
            "title": "108平三房两厅户型鉴赏",
            "transcript": "这套房南北通透，适合改善家庭。",
        }
    )

    assert result["overall_score"] == 60
    assert result["prediction_bucket"] == "普通潜力"
    assert result.get("_fallback") is True
    assert "AI返回结构异常" in result.get("_fallback_reason", "")
