from __future__ import annotations

import json

from pipeline import anchor_profiles, config, export


def test_profile_cache_survives_removed_room_list(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ANCHOR_PROFILE_CACHE", tmp_path / "anchor_profiles.json")
    monkeypatch.setattr(config, "AVATAR_CACHE_DIR", tmp_path / "avatar_cache")
    monkeypatch.setattr(config, "ROOMS_JSON", tmp_path / "rooms.json")
    monkeypatch.setattr(export, "ROOMS_JSON", tmp_path / "rooms.json")

    saved = anchor_profiles.save_profile(
        "123456",
        {
            "anchor_name": "测试主播",
            "avatar_url": "/cached/avatar.jpg",
            "source_url": "https://live.douyin.com/123456",
            "sec_user_id": "sec_1",
        },
    )

    assert saved["anchor_name"] == "测试主播"
    assert export.configured_room_profiles()["123456"]["anchor_name"] == "测试主播"

    # 删除/不存在 rooms.json 后，历史效能分析仍可从独立画像缓存读取资料。
    assert not config.ROOMS_JSON.exists()
    profiles = export.configured_room_profiles()
    assert profiles["123456"]["avatar_url"] == "/cached/avatar.jpg"
    assert profiles["123456"]["source_url"] == "https://live.douyin.com/123456"


def test_profile_cache_downloads_existing_remote_avatar_when_missing_local(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ANCHOR_PROFILE_CACHE", tmp_path / "anchor_profiles.json")
    monkeypatch.setattr(config, "AVATAR_CACHE_DIR", tmp_path / "avatar_cache")

    remote = "https://p.example.test/avatar.jpeg"
    monkeypatch.setattr(anchor_profiles, "_download_avatar", lambda _room_id, _avatar_url: None)
    anchor_profiles.save_profile("123456", {"anchor_name": "测试主播", "avatar_url": remote})
    raw = anchor_profiles._load_raw()
    raw["123456"].pop("local_avatar_path", None)
    config.ANCHOR_PROFILE_CACHE.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    def fake_download(room_id, avatar_url):
        assert room_id == "123456"
        assert avatar_url == remote
        path = config.AVATAR_CACHE_DIR / "123456.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake")
        return path

    monkeypatch.setattr(anchor_profiles, "_download_avatar", fake_download)
    saved = anchor_profiles.save_profile("123456", {"anchor_name": "测试主播"})

    assert saved["avatar_url"].startswith("/api/avatars/123456?v=")
