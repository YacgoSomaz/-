from __future__ import annotations

import json

from pipeline import export
from pipeline import performance_analysis as pa


def _bundle(*, rid: str = "1001", duration_sec: int = 1_920) -> export.RoomBundle:
    start = 1_772_000_000
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


def test_short_live_is_not_scored_or_sent_to_ai(monkeypatch, tmp_path):
    _patch_storage(monkeypatch, tmp_path)
    short = _bundle(duration_sec=600)
    monkeypatch.setattr(pa.export, "build_bundle", lambda rid, nick="": short)
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
    monkeypatch.setattr(pa.export, "build_bundle", lambda rid, nick="": bundle)
    monkeypatch.setattr(pa.export, "room_display_names", lambda: {"1001": "测试主播"})

    def fake_completion(*_args, **_kwargs):
        return json.dumps(
            {
                "track": "带货型直播",
                "template": "带货型直播",
                "positive_score": 82,
                "risk_deduction": 3,
                "data_missing_deduction": 0,
                "final_score": 79,
                "rating": "良好",
                "ai_summary": "测试主播有明确购买咨询和较好互动，适合进入小规模合作测试。",
                "key_positive_reasons": ["用户多次询问价格、链接和适配问题"],
                "key_deduction_reasons": ["存在少量需要人工复核的承诺表达"],
                "dimensions": [
                    {"name": "购买意图", "score": 23, "max_score": 25, "reason": "高意图弹幕集中"},
                    {"name": "互动反馈", "score": 18, "max_score": 20, "reason": "弹幕与进场稳定"},
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
    assert result["overall_score"] == 79
    assert result["positive_score"] == 82
    assert result["risk_deduction"] == 3
    assert result["score_source"] == "ai"
    assert result["score_template"] == "带货型直播"
    assert "ROI" not in str(result)
    assert "GMV" not in str(result)

    saved = pa.build_session_analysis("1001")
    assert saved["analysis_status"] == "done"
    assert saved["overall_score"] == 79
    assert saved["ai_summary"].startswith("测试主播")


def test_waiting_when_latest_audio_is_not_stable(monkeypatch, tmp_path):
    _patch_storage(monkeypatch, tmp_path)
    bundle = _bundle()
    monkeypatch.setattr(pa.export, "build_bundle", lambda rid, nick="": bundle)
    monkeypatch.setattr(pa.export, "room_display_names", lambda: {"1001": "测试主播"})
    monkeypatch.setattr(pa, "_latest_data_ts", lambda _bundle: pa.time.time())

    result = pa.build_session_analysis("1001")

    assert result["score_available"] is False
    assert result["overall_score"] is None
    assert result["analysis_status"] == "waiting_stable"
    assert "5 分钟" in result["analysis_status_text"]
