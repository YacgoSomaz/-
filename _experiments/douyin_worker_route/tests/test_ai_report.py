from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import ai_report, config
from pipeline import export as export_mod


class AIReportTests(unittest.TestCase):
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
                self.assertTrue(str(result["brief"]))
            finally:
                config.AI_CONFIG_PATH = old_config
                config.AI_REPORT_DIR = old_report_dir

    def test_clean_report_removes_chatty_prefix(self) -> None:
        raw = "好的，老板，以下是基于你提供的数据生成的报告：\n\n---\n\n## 核心结论\n- 价格优惠是重点。"
        cleaned = ai_report._clean_report_markdown(raw)
        self.assertTrue(cleaned.startswith("# AI 直播复盘报告"))
        self.assertNotIn("老板", cleaned)
        self.assertNotIn("以下是", cleaned)

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


if __name__ == "__main__":
    unittest.main()
