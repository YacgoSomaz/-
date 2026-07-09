from __future__ import annotations

from pathlib import Path

from pipeline import config, short_video_ai


def test_vision_config_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("SHORT_VIDEO_VISION_API_KEY", "secret")
    monkeypatch.setenv("SHORT_VIDEO_VISION_MODEL", "vision-model")
    monkeypatch.setenv("SHORT_VIDEO_VISION_BASE_URL", "https://vision.example/v1")

    cfg = short_video_ai.load_vision_config()

    assert cfg.ready is True
    assert cfg.api_key == "secret"
    assert cfg.model == "vision-model"
    assert cfg.base_url == "https://vision.example/v1"


def test_vision_config_reads_saved_ai_config(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "ai_config.json"
    cfg_path.write_text(
        '{"vision_base_url":"https://ark.example/api/v3","vision_api_key":"saved-key","vision_model":"seed-vision","vision_timeout_sec":90}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "AI_CONFIG_PATH", cfg_path)
    monkeypatch.delenv("SHORT_VIDEO_VISION_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    cfg = short_video_ai.load_vision_config()

    assert cfg.ready is True
    assert cfg.api_key == "saved-key"
    assert cfg.model == "seed-vision"
    assert cfg.base_url == "https://ark.example/api/v3"
    assert cfg.timeout_sec == 90


def test_analyze_selected_videos_uses_transcript_and_cover(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "SHORT_VIDEO_ASSET_DIR", tmp_path / "assets")
    cover_path = tmp_path / "cover.jpg"
    cover_path.write_bytes(b"\xff\xd8fake-cover")
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"mp3" * 800)

    calls: list[str] = []

    monkeypatch.setattr(
        short_video_ai.short_video,
        "download_video_cover_asset",
        lambda profile, video: {"ok": True, "path": str(cover_path)},
    )
    monkeypatch.setattr(
        short_video_ai.short_video,
        "download_video_mp3_asset",
        lambda profile, video: {"ok": True, "path": str(audio_path)},
    )

    class _Engine:
        def transcribe(self, path):
            calls.append(str(path))
            return "主播开场介绍三房户型，强调采光和学区配套，引导评论区咨询。"

    monkeypatch.setattr(short_video_ai, "SenseVoiceEngine", lambda: _Engine())
    monkeypatch.setattr(
        short_video_ai,
        "_analyze_transcript_with_ai",
        lambda transcript, profile, video: {
            "summary": "话术围绕户型价值展开。",
            "strengths": ["卖点清晰"],
            "problems": ["行动指令偏弱"],
            "suggestions": ["补充评论引导"],
        },
    )
    monkeypatch.setattr(
        short_video_ai,
        "_analyze_cover_with_vision",
        lambda cover, profile, video: {
            "summary": "封面展示样板间。",
            "strengths": ["画面明亮"],
            "problems": ["利益点不够突出"],
            "suggestions": ["增加核心卖点大字"],
        },
    )

    result = short_video_ai.analyze_selected_videos(
        {"nickname": "测试账号", "sec_user_id": "sec"},
        [{"id": "v1", "title": "三房户型讲解", "url": "https://www.douyin.com/video/1", "cover_url": "https://x/1.jpg"}],
    )

    assert result["ok"] is True
    assert calls == [str(audio_path)]
    item = result["items"][0]
    assert item["transcript"].startswith("主播开场")
    assert item["text_analysis"]["summary"] == "话术围绕户型价值展开。"
    assert item["cover_analysis"]["summary"] == "封面展示样板间。"
    assert item["score"]["overall_score"] > 0
    assert item["score"]["dimensions"]
    assert item["prediction"]["prediction_bucket"]
