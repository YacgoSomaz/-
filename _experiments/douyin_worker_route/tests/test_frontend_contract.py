from __future__ import annotations

from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "pipeline" / "frontend.html"


def test_ai_report_metrics_use_task_snapshot_not_all_rooms() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "selData.length || dataRooms.length" not in html
    assert "aiTaskTotals.rooms" in html
    assert "aiTaskTotals.transcripts" in html
    assert "aiTaskTotals.events" in html


def test_ai_report_has_long_running_pipeline_animation() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "ai-canvas" in html
    assert "aiCanvasNodes" in html
    assert "aiCanvasMergeLinks" in html
    assert "aiPulse" in html
    assert "startAiPulse" in html
    assert "ai-processing-stage" in html
    assert ":class=\"{processing:aiReporting}\"" in html
    assert 'v-if="!aiReporting" class="ai-agent"' in html
    assert "AI处理进度" in html
    assert "复盘分析画布" in html
    assert "综合判断区" in html
    assert "形成复盘结论" in html
    assert "分析内容重点" in html
    assert "aiCanvasAllLinks" in html
    assert "vector-effect:non-scaling-stroke" in html
    assert "electricFlow" in html


def test_ai_followup_panel_is_emphasized() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "AI复盘顾问" in html
    assert "把复盘报告继续问深一点" in html
    assert "常用追问" in html
    assert "可继续提问" in html


def test_ai_followup_context_is_scoped_to_selected_replay() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "aiChatStore" in html
    assert "aiChatContextKey" in html
    assert "aiChatRowKey" in html
    assert "watch(aiChatKey,activateAiChatContext" in html
    assert "const contextMessages=aiChatStore[key]||aiMessages.value" in html


def test_ai_picker_uses_anchor_chips_and_duration_filters() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "aiDateFilter" in html
    assert "aiSessionFilter" in html
    assert "filteredAiDataRooms" in html
    assert "anchor-chip" in html
    assert "录制时长" in html
    assert "displayRecordDuration" in html


def test_avatar_cache_refreshes_missing_or_broken_images() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "handleAvatarError" in html
    assert "ensureAvatars" in html
    assert "/api/anchors/'+encodeURIComponent(rid)+'/refresh" in html
    assert "refreshingAnchors.has(row.rid)" in html


def test_ai_report_markdown_preview_renders_structured_blocks() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "md-table-wrap" in html
    assert "parseTableLine" in html
    assert "md-step-card" in html
    assert "md-callout" in html
    assert "isTableSep" in html
