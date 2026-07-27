from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import ai_report, config
from pipeline import export as export_mod


class AIReportTests(unittest.TestCase):
    def test_official_report_evidence_is_bounded_and_does_not_need_local_key(self) -> None:
        transcript = export_mod.TranscriptRow(
            room_id="123", segment_ts=1_786_000_000, duration_sec=60.0,
            text="主播强调价格优惠，观众追问什么时候发货。", char_count=22, mp3_name="123/seq00001.mp3",
        )
        bundle = export_mod.RoomBundle(
            rid="123", nickname="测试主播", transcripts=[transcript], timeline=[],
            chats=[("用户A", "什么时候发货")], stats=[], event_counts={"chat": 1},
        )
        with patch.object(ai_report.export_mod, "load_speaker_labels", return_value={}), \
             patch.object(ai_report.export_mod, "room_display_names", return_value={"123": "测试主播"}), \
             patch.object(ai_report.export_mod, "build_bundle", return_value=bundle):
            evidence = ai_report.build_official_report_evidence(["123"])

        self.assertEqual(evidence["rooms"], 1)
        self.assertLessEqual(len(str(evidence["input_text"])), 18_000)
        self.assertIn("测试主播", str(evidence["input_text"]))
        self.assertIn("价格优惠", str(evidence["input_text"]))

    def test_official_report_is_saved_with_existing_local_viewer_flow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_report_dir = config.AI_REPORT_DIR
            config.AI_REPORT_DIR = Path(td) / "reports"
            bundle = export_mod.RoomBundle(
                rid="123", nickname="测试主播", transcripts=[], timeline=[], chats=[], stats=[], event_counts={},
            )
            try:
                saved = ai_report.save_official_report(
                    {"bundles": [bundle], "overviews": [{"nickname": "测试主播", "online_peak": 0, "platform_pv_latest": 0, "chat_count": 0, "transcript_segments": 0}], "words": []},
                    "## 一页总览\n- 官方模型已生成可执行建议。",
                )
                self.assertTrue(Path(str(saved["path"])).is_file())
                self.assertTrue(Path(str(saved["html_path"])).is_file())
                self.assertEqual(saved["pdf_status"], "deferred")
            finally:
                config.AI_REPORT_DIR = old_report_dir
    def test_config_masks_and_keeps_existing_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_path = config.AI_CONFIG_PATH
            config.AI_CONFIG_PATH = Path(td) / "ai_config.json"
            try:
                saved = ai_report.save_config({
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "secret-key",
                })
                self.assertTrue(saved["has_api_key"])
                self.assertNotIn("api_key", saved)

                saved_again = ai_report.save_config({
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model-2",
                    "api_key": "",
                })
                self.assertTrue(saved_again["has_api_key"])
                cfg = ai_report.load_config()
                self.assertEqual(cfg.api_key, "secret-key")
                self.assertEqual(cfg.model, "demo-model-2")
            finally:
                config.AI_CONFIG_PATH = old_path

    def test_generate_report_without_ai_writes_local_evidence_draft(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_config = config.AI_CONFIG_PATH
            old_report_dir = config.AI_REPORT_DIR
            config.AI_CONFIG_PATH = Path(td) / "missing_ai_config.json"
            config.AI_REPORT_DIR = Path(td) / "reports"
            transcript = export_mod.TranscriptRow(
                room_id="123",
                segment_ts=1_786_000_000,
                duration_sec=60.0,
                text="今天直播间专属优惠，客户最关心的是价格和到访礼。",
                char_count=26,
                mp3_name="123/seq00001.mp3",
                speaker_label="发言人A",
            )
            bundle = export_mod.RoomBundle(
                rid="123",
                nickname="测试主播",
                transcripts=[transcript],
                timeline=[],
                chats=[("用户A", "多少钱")],
                stats=[(1_786_000_000_000, 88, 1200)],
                event_counts={"chat": 1},
            )
            try:
                with patch.object(ai_report.export_mod, "load_speaker_labels", return_value={}), \
                     patch.object(ai_report.export_mod, "room_display_names", return_value={"123": "测试主播"}), \
                     patch.object(ai_report.export_mod, "build_bundle", return_value=bundle):
                    result = ai_report.generate_report(["123"])
                self.assertFalse(result["used_ai"])
                self.assertEqual(result["rooms"], 1)
                path = Path(str(result["path"]))
                self.assertTrue(path.exists())
                text = path.read_text(encoding="utf-8")
                self.assertIn("AI 直播复盘报告", text)
                self.assertIn("测试主播", text)
                pdf_path = Path(str(result["pdf_path"]))
                self.assertTrue(pdf_path.exists())
                self.assertGreater(pdf_path.stat().st_size, 1000)
                self.assertTrue(str(result["pdf_filename"]).endswith(".pdf"))
                html_path = Path(str(result["html_path"]))
                self.assertTrue(html_path.exists())
                html = html_path.read_text(encoding="utf-8")
                self.assertIn("数据看板", html)
                self.assertIn("report-float-panel", html)
                self.assertIn("mini-radar", html)
                self.assertIn("画面线索", html)
                self.assertIn("story-section", html)
                self.assertIn("jumpbar", html)
                self.assertTrue(str(result["brief"]))
            finally:
                config.AI_CONFIG_PATH = old_config
                config.AI_REPORT_DIR = old_report_dir

    def test_legacy_html_report_view_upgrades_tables_and_step_cards(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy.html"
            path.write_text(
                """<!doctype html><html lang="zh-CN"><head></head><body>
<section class="card report"><h1>测试报告</h1>
<h2>二、直播数据看板</h2>
<p>| 指标 | 数值 | 备注 |</p>
<p>|------|------|------|</p>
<p>| 主播昵称 | 测试主播 | 示例 |</p>
<h2>三、核心洞察</h2>
<p>1. <strong>内容吸引力较强</strong>：用户围绕价格持续提问。</p>
<ul><li>- 观众关注价格和优惠。</li></ul>
</section></body></html>""",
                encoding="utf-8",
            )

            upgraded = ai_report.report_view_html(path)

        self.assertIn('data-report-version="2"', upgraded)
        self.assertIn("livewatch-report-upgrade", upgraded)
        self.assertIn("legacy-upgraded", upgraded)
        self.assertIn("legacy-table-wrap", upgraded)
        self.assertIn("<table", upgraded)
        self.assertIn("legacy-step-card", upgraded)
        self.assertNotIn("<p>| 指标", upgraded)
        self.assertNotIn("<li>- 观众", upgraded)

    def test_clean_report_removes_chatty_prefix(self) -> None:
        raw = "好的，老板，以下是基于你提供的数据生成的报告：\n\n---\n\n## 核心结论\n- 价格优惠是重点。"
        cleaned = ai_report._clean_report_markdown(raw)
        self.assertTrue(cleaned.startswith("# AI 直播复盘报告"))
        self.assertNotIn("老板", cleaned)
        self.assertNotIn("以下是", cleaned)

    def test_final_report_uses_consulting_style_template(self) -> None:
        cfg = ai_report.AIConfig(base_url="https://api.example.test/v1", api_key="secret", model="demo")

        def fake_completion(_cfg, messages, **_kwargs):
            payload = messages[-1]["content"]
            self.assertIn("一页总览", payload)
            self.assertIn("直播数据看板", payload)
            self.assertIn("核心洞察", payload)
            self.assertIn("直播优化策略", payload)
            self.assertIn("风险复核", payload)
            self.assertIn("live_operation_knowledge_base", payload)
            return "# 测试报告\n\n## 一页总览\n- 通过"

        with patch.object(ai_report, "_chat_completion", side_effect=fake_completion):
            report = ai_report._final_report(
                cfg,
                [{"nickname": "测试主播", "online_peak": 88, "chat_count": 1}],
                [{"summary": "强调价格与配套", "evidence": [{"time": "10:00", "quote": "价格有优惠"}]}],
                False,
            )

        self.assertIn("一页总览", report)

    def test_summarize_chunk_invalid_json_falls_back_instead_of_crashing(self) -> None:
        cfg = ai_report.AIConfig(base_url="https://api.example.test/v1", api_key="secret", model="demo")
        chunk = {"text": "[测试主播][10:00] 主播介绍学校配套和优惠，观众追问多少钱。"}
        with patch.object(ai_report, "_chat_completion", return_value="不是 JSON，也没有对象字段"):
            summary = ai_report._summarize_chunk(cfg, chunk)
        self.assertIn("summary", summary)
        self.assertTrue(summary.get("_fallback"))
        self.assertTrue(summary.get("evidence"))

    def test_streaming_report_events_emit_structured_preview_and_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_config = config.AI_CONFIG_PATH
            old_report_dir = config.AI_REPORT_DIR
            config.AI_CONFIG_PATH = Path(td) / "missing_ai_config.json"
            config.AI_REPORT_DIR = Path(td) / "reports"
            transcript = export_mod.TranscriptRow(
                room_id="123",
                segment_ts=1_786_000_000,
                duration_sec=60.0,
                text="主播强调学校配套、价格优惠和客户到访礼，观众追问多少钱。",
                char_count=30,
                mp3_name="123/seq00001.mp3",
            )
            bundle = export_mod.RoomBundle(
                rid="123",
                nickname="测试主播",
                transcripts=[transcript],
                timeline=[],
                chats=[("用户A", "多少钱")],
                stats=[(1_786_000_000_000, 88, 1200)],
                event_counts={"chat": 1},
            )
            try:
                with patch.object(ai_report.export_mod, "load_speaker_labels", return_value={}), \
                     patch.object(ai_report.export_mod, "room_display_names", return_value={"123": "测试主播"}), \
                     patch.object(ai_report.export_mod, "build_bundle", return_value=bundle):
                    events = list(ai_report.generate_report_events(["123"]))
            finally:
                config.AI_CONFIG_PATH = old_config
                config.AI_REPORT_DIR = old_report_dir

        previews = [e for e in events if e.get("partial_preview")]
        self.assertTrue(previews)
        self.assertTrue(any(e.get("estimate_sec") for e in events))
        self.assertIn("正在生成", str(previews[0]["partial_preview"]))
        self.assertIn("直播数据看板", str(previews[0]["partial_preview"]))

    def test_streaming_report_defers_pdf_until_download(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_config = config.AI_CONFIG_PATH
            old_report_dir = config.AI_REPORT_DIR
            config.AI_CONFIG_PATH = Path(td) / "missing_ai_config.json"
            config.AI_REPORT_DIR = Path(td) / "reports"
            transcript = export_mod.TranscriptRow(
                room_id="123",
                segment_ts=1_786_000_000,
                duration_sec=60.0,
                text="主播强调学校配套、价格优惠和客户到访礼。",
                char_count=24,
                mp3_name="123/seq00001.mp3",
            )
            bundle = export_mod.RoomBundle(
                rid="123",
                nickname="测试主播",
                transcripts=[transcript],
                timeline=[],
                chats=[],
                stats=[],
                event_counts={},
            )
            try:
                with patch.object(ai_report.export_mod, "load_speaker_labels", return_value={}), \
                     patch.object(ai_report.export_mod, "room_display_names", return_value={"123": "测试主播"}), \
                     patch.object(ai_report.export_mod, "build_bundle", return_value=bundle), \
                     patch.object(ai_report, "_markdown_to_pdf", side_effect=AssertionError("PDF should be lazy")):
                    events = list(ai_report.generate_report_events(["123"]))
                done = [e for e in events if e.get("type") == "done"][-1]
                self.assertEqual(done["pdf_status"], "deferred")
                self.assertTrue(Path(str(done["html_path"])).exists())
                self.assertFalse(Path(str(done["pdf_path"])).exists())
            finally:
                config.AI_CONFIG_PATH = old_config
                config.AI_REPORT_DIR = old_report_dir

    def test_streaming_report_summarizes_ai_chunks_concurrently(self) -> None:
        cfg = ai_report.AIConfig(base_url="https://api.example.test/v1", api_key="secret", model="demo")
        bundle = export_mod.RoomBundle(
            rid="123",
            nickname="测试主播",
            transcripts=[],
            timeline=[],
            chats=[],
            stats=[],
            event_counts={},
        )
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_summary(_cfg, chunk):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.08)
            with lock:
                active -= 1
            return {"summary": str(chunk["text"]), "evidence": [], "themes": [], "selling_points": [], "prices": [], "promotions": [], "audience_questions": [], "risk_claims": []}

        with tempfile.TemporaryDirectory() as td:
            old_report_dir = config.AI_REPORT_DIR
            config.AI_REPORT_DIR = Path(td) / "reports"
            try:
                with patch.object(ai_report, "load_config", return_value=cfg), \
                     patch.object(ai_report, "_load_bundles", return_value=[bundle]), \
                     patch.object(ai_report, "_build_chunks", return_value=([{"text": "a"}, {"text": "b"}, {"text": "c"}], False)), \
                     patch.object(ai_report, "word_cloud", return_value={"words": []}), \
                     patch.object(ai_report, "_summarize_chunk", side_effect=fake_summary), \
                     patch.object(ai_report, "_final_report", return_value="# AI 直播复盘报告\n\n## 一页总览\n- 通过"), \
                     patch.object(ai_report, "_brief_report", side_effect=AssertionError("streaming report must not make a second AI brief call")), \
                     patch.object(ai_report, "_write_html_report", side_effect=lambda _report, path, **_kwargs: Path(path).write_text("<html></html>", encoding="utf-8")):
                    list(ai_report.generate_report_events(["123"]))
            finally:
                config.AI_REPORT_DIR = old_report_dir

        self.assertGreaterEqual(max_active, 2)

    def test_pdf_visual_assets_do_not_create_oversized_flowable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            img = root / "avatar.png"
            from PIL import Image as PILImage

            PILImage.new("RGB", (64, 64), (72, 84, 255)).save(img)
            pdf = root / "report.pdf"
            ai_report._markdown_to_pdf(
                "# 测试报告\n\n## 一页总览\n- 视觉素材应该稳定排版",
                pdf,
                overviews=[{"nickname": "测试主播", "online_peak": 12, "platform_pv_latest": 88, "chat_count": 3, "transcript_segments": 2}],
                words=[{"word": "优惠", "count": 3}],
                visual_assets=[{"nickname": "测试主播", "frames": [img], "avatar": None}],
            )
            self.assertTrue(pdf.exists())
            self.assertGreater(pdf.stat().st_size, 1000)

    def test_word_cloud_ignores_audio_metadata_noise(self) -> None:
        transcript = export_mod.TranscriptRow(
            room_id="123",
            segment_ts=1_786_000_000,
            duration_sec=60.0,
            text="录音 audio seq mp3 未标注 是不是 是不是 房子 改善 学校 学校 优惠 优惠 户型 户型",
            char_count=60,
            mp3_name="123/seq00001.mp3",
        )
        bundle = export_mod.RoomBundle(
            rid="123",
            nickname="测试主播",
            transcripts=[transcript],
            timeline=[],
            chats=[],
            stats=[],
            event_counts={},
        )
        with patch.object(ai_report.export_mod, "load_speaker_labels", return_value={}), \
             patch.object(ai_report.export_mod, "room_display_names", return_value={"123": "测试主播"}), \
             patch.object(ai_report.export_mod, "build_bundle", return_value=bundle):
            words = [item["word"] for item in ai_report.word_cloud(["123"], limit=20)["words"]]
        self.assertIn("学校", words)
        self.assertIn("优惠", words)
        self.assertNotIn("录音", words)
        self.assertNotIn("未标注", words)
        self.assertNotIn("是不是", words)

    def test_answer_question_ignores_frontend_thinking_message(self) -> None:
        transcript = export_mod.TranscriptRow(
            room_id="123",
            segment_ts=1_786_000_000,
            duration_sec=60.0,
            text="主播反复强调首付门槛、学校配套和到访礼。",
            char_count=24,
            mp3_name="123/seq00001.mp3",
        )
        bundle = export_mod.RoomBundle(
            rid="123",
            nickname="测试主播",
            transcripts=[transcript],
            timeline=[],
            chats=[],
            stats=[],
            event_counts={},
        )
        cfg = ai_report.AIConfig(
            base_url="https://api.example.test/v1",
            api_key="secret",
            model="demo",
        )
        messages = [
            {"role": "user", "content": "我后续应该怎么优化？"},
            {"role": "assistant", "content": "AI 正在思考", "thinking": True},
        ]
        with patch.object(ai_report.export_mod, "load_speaker_labels", return_value={}), \
             patch.object(ai_report.export_mod, "room_display_names", return_value={"123": "测试主播"}), \
             patch.object(ai_report.export_mod, "build_bundle", return_value=bundle), \
             patch.object(ai_report, "load_config", return_value=cfg), \
             patch.object(ai_report, "_chat_completion", return_value="建议强化价格与到访礼引导。") as mocked:
            result = ai_report.answer_question(["123"], messages)  # type: ignore[arg-type]
        self.assertTrue(result["ok"])
        sent_messages = mocked.call_args.args[1]
        self.assertEqual(sent_messages[-1]["role"], "user")
        self.assertNotIn("AI 正在思考", str(sent_messages))

    def test_answer_question_events_stream_visible_answer_only(self) -> None:
        transcript = export_mod.TranscriptRow(
            room_id="123",
            segment_ts=1_786_000_000,
            duration_sec=60.0,
            text="主播强调首付门槛、学校配套和到访礼。",
            char_count=24,
            mp3_name="123/seq00001.mp3",
        )
        bundle = export_mod.RoomBundle(
            rid="123",
            nickname="测试主播",
            transcripts=[transcript],
            timeline=[],
            chats=[],
            stats=[],
            event_counts={},
        )
        cfg = ai_report.AIConfig(
            base_url="https://api.example.test/v1",
            api_key="secret",
            model="demo",
        )
        messages = [{"role": "user", "content": "总结亮点"}]

        with patch.object(ai_report.export_mod, "load_speaker_labels", return_value={}), \
             patch.object(ai_report.export_mod, "room_display_names", return_value={"123": "测试主播"}), \
             patch.object(ai_report.export_mod, "build_bundle", return_value=bundle), \
             patch.object(ai_report, "load_config", return_value=cfg), \
             patch.object(ai_report, "_chat_completion_stream", return_value=iter(["亮点是", "学校配套。"])):
            events = list(ai_report.answer_question_events(["123"], messages))

        self.assertTrue(any(e.get("type") == "stage" for e in events))
        self.assertEqual(
            "".join(str(e.get("content") or "") for e in events if e.get("type") == "delta"),
            "亮点是学校配套。",
        )
        self.assertEqual(events[-1]["type"], "done")

    def test_chat_completion_stream_forces_utf8_for_sse_without_charset(self) -> None:
        cfg = ai_report.AIConfig(
            base_url="https://api.example.test/v1",
            api_key="secret",
            model="demo",
        )

        class FakeResponse:
            status_code = 200
            encoding = None

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def iter_lines(self, *, chunk_size, decode_unicode):
                self_seen_encoding = self.encoding
                self.assert_encoding = self_seen_encoding
                payload = '{"choices":[{"delta":{"content":"直播正常"}}]}'
                raw_lines = [f"data: {payload}".encode("utf-8"), b"data: [DONE]"]
                for raw in raw_lines:
                    yield raw.decode(self.encoding or "latin-1") if decode_unicode else raw

        response = FakeResponse()
        with patch("pipeline.ai_report.requests.post", return_value=response):
            content = "".join(ai_report._chat_completion_stream(cfg, [{"role": "user", "content": "测试"}]))

        self.assertEqual(response.assert_encoding, "utf-8")
        self.assertEqual(content, "直播正常")


if __name__ == "__main__":
    unittest.main()
