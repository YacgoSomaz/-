from __future__ import annotations

import json

from pipeline import export
from pipeline import performance_analysis as pa


def _bundle(*, rid: str = "1001", duration_sec: int = 1_920, start: int = 1_772_000_000) -> export.RoomBundle:
    half = duration_sec // 2
    transcripts = [
        export.TranscriptRow(
            room_id=rid,
            segment_ts=start,
            duration_sec=half,
            text="今天这个产品适合想改善居住体验的朋友，链接在小黄车，价格有优惠。",
            char_count=35,
            mp3_name=f"{rid}/seq00001.mp3",
            capture_start=start,
            capture_end=start + half,
        ),
        export.TranscriptRow(
            room_id=rid,
            segment_ts=start + half,
            duration_sec=duration_sec - half,
            text="欢迎大家提问，多少钱、怎么选、适合我吗这些问题都可以直接打在公屏。",
            char_count=36,
            mp3_name=f"{rid}/seq00002.mp3",
            capture_start=start + half,
            capture_end=start + duration_sec,
        ),
    ]
    timeline = [
        export.RecordingTimelineRow(
            id=1,
            room_id=rid,
            seq=1,
            kind="segment",
            status="ok",
            file_path=f"{rid}/seq00001.mp3",
            capture_start=start,
            capture_end=start + half,
            duration_sec=half,
            file_size=20000,
            error=None,
            transcribed=True,
            transcript_preview="今天这个产品适合",
        ),
        export.RecordingTimelineRow(
            id=2,
            room_id=rid,
            seq=2,
            kind="segment",
            status="ok",
            file_path=f"{rid}/seq00002.mp3",
            capture_start=start + half,
            capture_end=start + duration_sec,
            duration_sec=duration_sec - half,
            file_size=20000,
            error=None,
            transcribed=True,
            transcript_preview="欢迎大家提问",
        ),
    ]
    chats = [
        ("u1", "多少钱"),
        ("u2", "链接在哪"),
        ("u3", "适合我吗"),
        ("u4", "已经拍了"),
    ]
    stats = [
        (start * 1000, 30, 100),
        ((start + half) * 1000, 52, 180),
        ((start + duration_sec) * 1000, 65, 260),
    ]
    return export.RoomBundle(
        rid,
        "测试主播",
        transcripts,
        timeline,
        chats,
        stats,
        {"chat": 4, "like": 30, "social": 2, "member": 40, "fansclub": 1},
    )


def _patch_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(pa.config, "DB_PATH", tmp_path / "transcripts.db")
    monkeypatch.setattr(pa.config, "AUDIO_DIR", tmp_path / "audio")
    pa.config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def test_performance_list_hides_unregistered_history_and_uses_registered_profile(monkeypatch):
    """Old database rooms must not impersonate the currently registered account."""
    pa._SUMMARY_CACHE.clear()
    calls = []
    monkeypatch.setattr(pa.export, "room_display_names", lambda: {"legacy": "旧库昵称", "current": "陈旧昵称"})
    monkeypatch.setattr(
        pa.export,
        "configured_room_profiles",
        lambda: {"current": {"anchor_name": "当前账号", "avatar_url": "/api/avatars/current", "source_url": "https://live.douyin.com/current"}},
    )
    monkeypatch.setattr(pa.export, "export_room_ids", lambda: ["legacy", "current"])

    def fake_bundles(rid, nickname):
        calls.append((rid, nickname))
        return [(rid, nickname)]

    monkeypatch.setattr(pa, "_bundles_for_room", fake_bundles)
    monkeypatch.setattr(
        pa,
        "_build_from_bundle",
        lambda bundle, *, include_detail, profile: {
            "rid": bundle[0],
            "anchor_name": bundle[1],
            "avatar_url": profile.get("avatar_url", ""),
            "analysis_status": "done",
            "overall_score": 80,
            "metrics": {"danmu_count": 0},
        },
    )

    rows = pa.list_session_summaries()

    assert calls == [("current", "当前账号")]
    assert rows == [{"rid": "current", "anchor_name": "当前账号", "avatar_url": "/api/avatars/current", "analysis_status": "done", "overall_score": 80, "metrics": {"danmu_count": 0}}]


def test_performance_list_error_row_keeps_registered_profile_name(monkeypatch):
    pa._SUMMARY_CACHE.clear()
    monkeypatch.setattr(
        pa.export,
        "configured_room_profiles",
        lambda: {"current": {"anchor_name": "当前账号", "source_url": "https://live.douyin.com/current"}},
    )
    monkeypatch.setattr(pa, "_bundles_for_room", lambda *_args: (_ for _ in ()).throw(RuntimeError("坏数据")))

    rows = pa.list_session_summaries()

    assert len(rows) == 1
    assert rows[0]["anchor_name"] == "当前账号"
    assert "坏数据" in rows[0]["analysis_status_text"]


def _metric(
    *,
    peak_online: int = 50,
    avg_online: float = 40.0,
    enter_events: int = 100,
    danmu_count: int = 20,
    like_events: int = 30,
    follow_events: int = 0,
    fansclub_events: int = 0,
) -> pa.MetricSnapshot:
    duration = 1_800.0
    return pa.MetricSnapshot(
        duration_sec=duration,
        recorded_duration=duration,
        transcribed_duration=duration,
        completeness=1.0,
        danmu_count=danmu_count,
        event_total=danmu_count + like_events + enter_events + follow_events + fansclub_events,
        peak_online=peak_online,
        avg_online=avg_online,
        latest_online=peak_online,
        total_viewers=0,
        like_events=like_events,
        follow_events=follow_events,
        enter_events=enter_events,
        fansclub_events=fansclub_events,
        question_count=0,
        intent_count=0,
        negative_count=0,
        transcript_chars=3_000,
        speech_density=100.0,
        danmu_per_min=danmu_count / 30,
        like_per_min=like_events / 30,
        intent_ratio=0.0,
        online_stability=0.9,
        high_value_member_events=0,
        gift_events=0,
        disconnect_count=0,
        short_segment_count=0,
        broken_segment_count=0,
        failed_transcripts=0,
    )


def test_short_live_is_not_scored_or_sent_to_ai(monkeypatch, tmp_path):
    _patch_storage(monkeypatch, tmp_path)
    short = _bundle(duration_sec=600)
    monkeypatch.setattr(pa.export, "build_bundle", lambda rid, nick="", **_kwargs: short)
    monkeypatch.setattr(pa.export, "room_display_names", lambda: {"1001": "测试主播"})

    result = pa.build_session_analysis("1001")

    assert result["score_available"] is False
    assert result["overall_score"] is None
    assert result["rating"] == "数据不足"
    assert result["analysis_status"] == "not_eligible_short"
    assert "15 分钟" in result["analysis_status_text"]


def test_stable_long_live_can_be_analyzed_by_ai_and_saved(monkeypatch, tmp_path):
    _patch_storage(monkeypatch, tmp_path)
    bundle = _bundle()
    monkeypatch.setattr(pa.export, "build_bundle", lambda rid, nick="", **_kwargs: bundle)
    monkeypatch.setattr(pa.export, "room_display_names", lambda: {"1001": "测试主播"})

    def fake_completion(*_args, **_kwargs):
        return json.dumps(
            {
                "track": "带货型直播",
                "template": "带货型直播",
                "positive_score": 99,
                "risk_deduction": 3,
                "data_missing_deduction": 2,
                "final_score": 99,
                "rating": "良好",
                "ai_summary": "测试主播有明确购买咨询和较好互动，适合进入小规模合作测试。",
                "key_positive_reasons": ["用户多次询问价格、链接和适配问题"],
                "key_deduction_reasons": ["存在少量需要人工复核的承诺表达"],
                "dimensions": [
                    {"name": "内容质量/话术转化力", "score": 28, "max_score": 35, "reason": "讲品和承接较清楚"},
                    {"name": "直播热度", "score": 16, "max_score": 25, "reason": "在线和进场中等"},
                    {"name": "互动反馈", "score": 14, "max_score": 20, "reason": "弹幕与进场稳定"},
                    {"name": "购买兴趣", "score": 7, "max_score": 10, "reason": "高意图弹幕集中"},
                    {"name": "数据完整性", "score": 5, "max_score": 10, "reason": "数据可用但覆盖有限"},
                ],
                "risk_review": [],
                "suggestions": ["保留价格和适配问题的标准回应话术"],
                "confidence": "高",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(pa.ai_report, "load_config", lambda: pa.ai_report.AIConfig(base_url="https://example.test/v1", api_key="x", model="deepseek-chat"))
    monkeypatch.setattr(pa.ai_report, "_chat_completion", fake_completion)

    result = pa.analyze_room("1001", force=True)

    assert result["analysis_status"] == "done"
    assert result["score_available"] is True
    assert result["overall_score"] == 68
    assert result["positive_score"] == 70
    assert result["risk_deduction"] == 0
    assert result["score_source"] == "ai"
    assert result["score_template"] == "带货型直播"
    assert "ROI" not in str(result)
    assert "GMV" not in str(result)

    saved = pa.build_session_analysis("1001")
    assert saved["analysis_status"] == "done"
    assert saved["overall_score"] == 68
    assert saved["ai_summary"].startswith("测试主播")


def test_sensitive_risk_review_does_not_change_score():
    result = pa._normalize_ai_result(
        {
            "track": "带货型直播",
            "template": "带货型直播",
            "data_missing_deduction": 1,
            "dimensions": [
                {"name": "内容质量/话术转化力", "score": 30, "max_score": 35},
                {"name": "直播热度", "score": 20, "max_score": 25},
                {"name": "互动反馈", "score": 15, "max_score": 20},
                {"name": "购买兴趣", "score": 8, "max_score": 10},
                {"name": "数据完整性", "score": 9, "max_score": 10},
            ],
            "risk_deduction": 20,
            "risk_review": [
                {
                    "risk_type": "敏感词候选",
                    "level": "严重",
                    "is_real_risk": True,
                    "deduction": 6,
                    "evidence": "全网最低",
                    "reason": "敏感词复核提示",
                }
            ],
        }
    )

    assert result["positive_score"] == 82
    assert result["risk_deduction"] == 0
    assert result["final_score"] == 81
    assert result["risk_review"][0]["deduction"] == 6


def test_waiting_when_latest_audio_is_not_stable(monkeypatch, tmp_path):
    _patch_storage(monkeypatch, tmp_path)
    bundle = _bundle()
    monkeypatch.setattr(pa.export, "build_bundle", lambda rid, nick="", **_kwargs: bundle)
    monkeypatch.setattr(pa.export, "room_display_names", lambda: {"1001": "测试主播"})
    monkeypatch.setattr(pa, "_latest_data_ts", lambda _bundle: pa.time.time())

    result = pa.build_session_analysis("1001")

    assert result["score_available"] is False
    assert result["overall_score"] is None
    assert result["analysis_status"] == "waiting_stable"
    assert "5 分钟" in result["analysis_status_text"]


def test_performance_detail_includes_sensitive_word_review(monkeypatch, tmp_path):
    _patch_storage(monkeypatch, tmp_path)
    bundle = _bundle()
    bundle.transcripts[0] = export.TranscriptRow(
        room_id="1001",
        segment_ts=bundle.transcripts[0].segment_ts,
        duration_sec=bundle.transcripts[0].duration_sec,
        text="我们这个房源是官方认证项目，今天有特价活动，但需要人工复核语境。",
        char_count=32,
        mp3_name="1001/seq00001.mp3",
        capture_start=bundle.transcripts[0].capture_start,
        capture_end=bundle.transcripts[0].capture_end,
        speaker_label="speaker_A",
    )
    monkeypatch.setattr(pa.export, "build_bundle", lambda rid, nick="", **_kwargs: bundle)
    monkeypatch.setattr(pa.export, "room_display_names", lambda: {"1001": "测试主播"})

    result = pa.build_session_analysis("1001")

    assert result["sensitive_total"] >= 2
    assert any(row["term"] == "官方认证" for row in result["sensitive_top_terms"])
    assert result["sensitive_summary"]["samples"][0]["source"] == "主播话术"
    assert "复核" in result["sensitive_summary"]["samples"][0]["context_status"] or result["sensitive_summary"]["samples"][0]["context_status"] == "语境较明确"


def test_high_risk_operational_lexicon_hits_are_included_in_report_risk_evidence(monkeypatch, tmp_path):
    _patch_storage(monkeypatch, tmp_path)
    bundle = _bundle()
    bundle.transcripts[0] = export.TranscriptRow(
        room_id="1001",
        segment_ts=bundle.transcripts[0].segment_ts,
        duration_sec=bundle.transcripts[0].duration_sec,
        text="直播间扫码添加，稳赚不赔。",
        char_count=14,
        mp3_name="1001/seq00001.mp3",
        capture_start=bundle.transcripts[0].capture_start,
        capture_end=bundle.transcripts[0].capture_end,
        speaker_label="speaker_A",
    )
    monkeypatch.setattr(pa.export, "build_bundle", lambda rid, nick="", **_kwargs: bundle)
    monkeypatch.setattr(pa.export, "room_display_names", lambda: {"1001": "测试主播"})

    result = pa.build_session_analysis("1001")

    assert {row["risk_type"] for row in result["risk_segments"]} >= {"导流引流", "金融承诺"}
    assert all("建议" in row["suggestion"] or "删除" in row["suggestion"] for row in result["risk_segments"])


def test_list_summary_does_not_build_reference_metrics(monkeypatch, tmp_path):
    _patch_storage(monkeypatch, tmp_path)
    bundle = _bundle()
    monkeypatch.setattr(pa.export, "export_room_ids", lambda: ["1001"])
    monkeypatch.setattr(pa.export, "build_bundle", lambda rid, nick="", **_kwargs: bundle)
    monkeypatch.setattr(pa.export, "room_display_names", lambda: {"1001": "测试主播"})
    monkeypatch.setattr(
        pa.export,
        "configured_room_profiles",
        lambda: {"1001": {"anchor_name": "测试主播", "source_url": "https://live.douyin.com/1001"}},
    )

    def fail_reference(*_args, **_kwargs):
        raise AssertionError("列表页不应该计算同批参考指标")

    monkeypatch.setattr(pa, "_reference_metrics", fail_reference)

    result = pa.list_session_summaries()

    assert len(result) == 1
    assert result[0]["session_id"] == "1001"


def test_analysis_messages_include_modular_live_replay_skills():
    messages = pa._analysis_messages({"room_id": "1001", "metrics": {}, "score_templates": {}})
    system = messages[0]["content"]

    assert "【直播复盘总控】" in system
    assert "【抖音直播策略】" in system
    assert "【评分裁判】" in system
    assert "【风险复核】" in system


def test_reference_metrics_fallback_to_all_library_heat_when_same_track_is_too_small(monkeypatch):
    current = _metric(peak_online=620, avg_online=570, enter_events=4_900, danmu_count=440, like_events=410, follow_events=15, fansclub_events=13)
    low_peer = _metric(peak_online=30, avg_online=20, enter_events=120, danmu_count=10, like_events=20)
    mid_peer = _metric(peak_online=180, avg_online=120, enter_events=900, danmu_count=90, like_events=100)
    metrics_by_rid = {"current": current, "low": low_peer, "mid": mid_peer}
    bundles = {rid: _bundle(rid=rid) for rid in metrics_by_rid}

    monkeypatch.setattr(pa.export, "export_room_ids", lambda: ["current", "low", "mid"])
    monkeypatch.setattr(pa.export, "room_display_names", lambda: {"current": "光音里", "low": "低热度主播", "mid": "中热度主播"})
    monkeypatch.setattr(pa.export, "build_bundle", lambda rid, nick="", **_kwargs: bundles[rid])
    monkeypatch.setattr(pa, "_metrics", lambda bundle: metrics_by_rid[bundle.rid])
    monkeypatch.setattr(pa, "_track_for_reference_room", lambda _rid, _bundle: "娱乐/聊天型直播" if _rid == "current" else "带货型直播")

    ref = pa._reference_metrics("current", current, current_track="娱乐/聊天型直播")

    assert ref["comparison_strategy"]["scope"] == "全库热度参考"
    assert "同赛道样本不足" in ref["comparison_strategy"]["reason"]
    assert ref["comparison_strategy"]["same_track_sample_size"] == 1
    assert ref["comparison_strategy"]["reference_sample_size"] == 3
    assert "peak_online" in ref["comparison_strategy"]["primary_metric_keys"]
    assert "enter_events" in ref["comparison_strategy"]["primary_metric_keys"]
    assert ref["benchmarks"]["peak_online"]["rank"] == 1
    assert ref["benchmarks"]["peak_online"]["sample_size"] == 3
    assert ref["benchmarks"]["enter_events"]["rank"] == 1


def test_performance_sessions_are_split_by_day(monkeypatch, tmp_path):
    _patch_storage(monkeypatch, tmp_path)
    first = _bundle(start=1_772_000_000)
    second = _bundle(start=1_772_086_400)
    full = export.RoomBundle(
        "1001",
        "测试主播",
        first.transcripts + second.transcripts,
        first.timeline + second.timeline,
        first.chats + second.chats,
        first.stats + second.stats,
        {
            "chat": len(first.chats) + len(second.chats),
            "like": 60,
            "social": 4,
            "member": 80,
            "fansclub": 2,
        },
    )

    def fake_build_bundle(rid, nick="", **kwargs):
        day = kwargs.get("session_day") or ""
        if not day:
            return full
        start_ts = kwargs["start_ts"]
        end_ts = kwargs["end_ts"]
        transcripts = [row for row in full.transcripts if start_ts <= float(row.capture_start or row.segment_ts) < end_ts]
        timeline = [row for row in full.timeline if start_ts <= float(row.capture_start or row.capture_end) < end_ts]
        stats = [row for row in full.stats if start_ts <= row[0] / 1000 < end_ts]
        chats = first.chats if day == pa._day_key(first.transcripts[0].capture_start) else second.chats
        return export.RoomBundle(
            rid,
            nick,
            transcripts,
            timeline,
            chats,
            stats,
            {"chat": len(chats), "like": 30, "social": 2, "member": 40, "fansclub": 1},
            source_rid=rid,
            session_id=kwargs.get("session_id", ""),
            session_day=day,
        )

    monkeypatch.setattr(pa.export, "export_room_ids", lambda: ["1001"])
    monkeypatch.setattr(pa.export, "build_bundle", fake_build_bundle)
    monkeypatch.setattr(pa.export, "room_display_names", lambda: {"1001": "测试主播"})
    monkeypatch.setattr(
        pa.export,
        "configured_room_profiles",
        lambda: {"1001": {"anchor_name": "测试主播", "source_url": "https://live.douyin.com/1001"}},
    )

    rows = pa.list_session_summaries()

    expected_days = {
        pa._day_key(first.transcripts[0].capture_start),
        pa._day_key(second.transcripts[0].capture_start),
    }
    assert len(rows) == 2
    assert {row["session_id"] for row in rows} == {f"1001__{day}" for day in expected_days}
    assert {row["session_day"].replace("-", "") for row in rows} == expected_days
