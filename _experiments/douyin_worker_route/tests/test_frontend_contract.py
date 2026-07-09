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
    assert "aiReportHistory" in html
    assert "openAiReportHistory" in html
    assert "livewatch_ai_report_history" in html


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


def test_short_video_center_has_profile_and_recent_selection() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "短视频中心" in html
    assert "shortVideo.profileUrl" in html
    assert "shortVideo.targetCount" in html
    assert "加 5 条" in html
    assert "加 10 条" in html
    assert "customAppendCount" in html
    assert "short-custom-append" in html
    assert "appendShortProfileVideos" in html
    assert "resolveShortProfile,appendShortProfileVideos" in html
    assert "resolveShortProfile" in html
    assert "analyzeShortVideos" in html
    assert "/api/short-video/analyze" in html
    assert "AI拆解所选作品" in html
    assert "拆解任务" not in html
    assert "shortVideoJobs" not in html
    assert "下载封面与MP3" not in html
    assert "downloadShortVideoAssets" not in html
    assert "/api/short-video/resolve-profile/stream" in html
    assert "resp.body.getReader()" in html
    assert "SHORT_PARSE_CACHE_KEY" in html
    assert "saveShortParseCache" in html
    assert "loadShortParseCache" in html
    assert "/api/short-video/parse-cache" in html
    assert "applyShortParseCache" in html
    assert "shortVideo.profileUrl=''" in html
    assert "已恢复上次解析结果" in html
    assert "selectedKeys" in html
    assert "AI 正在努力获取账号资料" in html
    assert "short-parse-track" in html
    assert "shortParseSteps" in html
    assert "parsePhase" in html
    assert "作品列表" in html
    assert "short-main-layout" in html
    assert "short-cover-wrap" in html
    assert "拆解结果" in html
    assert "账号定位与对标推荐" in html
    assert "对标账号候选方向" in html
    assert "/api/short-video/positioning" in html
    assert "/api/short-video/benchmark-recommendations" in html
    assert "/api/short-video/benchmarks" in html
    assert "analyzeShortPositioning" in html
    assert "analyzeAndRecommendBenchmarks" in html
    assert "recommendShortBenchmarks" in html
    assert "自动分析并推荐对标账号" in html
    assert "addShortBenchmark" in html
    assert "addShortBenchmarkFromInput" in html
    assert "searchShortBenchmark" in html
    assert "searchShortBenchmarkAccounts" in html
    assert "addShortAccountCandidate" in html
    assert "useShortBenchmarkProfile" in html
    assert "shortVideoBenchmarks" in html
    assert "positioningLoading" in html
    assert "benchmarkLoading" in html
    assert "对标账号池" in html
    assert "加入对标池" in html
    assert ">生成搜索线索<" not in html
    assert "重新推荐账号" in html
    assert "候选账号" in html
    assert "打开抖音搜索" in html
    assert "cover_url" in html
    assert "like_count" in html
    assert "AI评分" in html
    assert "作品解析" in html
    assert "AI工作台" in html
    assert "sendShortVideosToWorkspace" in html
    assert "shortVideo.activeTab" in html
    assert "short-work-tabs" in html
    assert "short-workspace-shell" in html
    assert "作品潜力分" in html
    assert "爆款预测" in html
    assert "workReports" in html
    assert "workHistory" in html
    assert "currentShortWork" in html
    assert "currentShortReport" in html
    assert "short-progress-card" in html
    assert "short-report-shell" in html
    assert "openShortHistory" in html
    assert "analyzeSingleShortVideo" in html
    assert "resetShortReportsForSession" in html
    assert "每条作品都有独立报告" in html
    assert "livewatch_short_video_reports" in html
    assert "脚本预测" in html
    assert "对标学习" in html
    assert "发布后复盘" in html
    assert "scoreShortVideoWork" in html
    assert "predictShortScript" in html
    assert "learnFromBenchmark" in html
    assert "retroShortVideoPrediction" in html
    assert "/api/short-video/score" in html
    assert "/api/short-video/predict-script" in html
    assert "/api/short-video/learn-from-benchmark" in html
    assert "/api/short-video/retro" in html
    assert 'placeholder="可选：每行粘贴一个作品链接，加入作品列表后再勾选拆解"></el-input>' in html


def test_short_video_stream_parser_accepts_ndjson_and_sse() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "function parseShortStreamEvent" in html
    assert "raw.startsWith('data:')" in html
    assert "evt.ok===false||evt.type==='error'" in html
    assert "!evt.ok||evt.type==='error'" not in html


def test_settings_exposes_short_video_vision_config() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "短视频封面识别" in html
    assert "aiConfig.vision_base_url" in html
    assert "aiConfig.vision_model" in html
    assert "aiConfig.vision_api_key" in html
    assert "has_vision_api_key" in html
    assert "vision_api_key:aiConfig.vision_api_key" in html


def test_avatar_cache_refreshes_missing_or_broken_images() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "handleAvatarError" in html
    assert "ensureAvatars" in html
    assert "/api/anchors/'+encodeURIComponent(rid)+'/refresh" in html
    assert "refreshingAnchors.has(row.rid)" in html


def test_performance_page_has_recent_history_shortcuts() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "效能分析场次" in html
    assert "performanceSessions.slice(0,10)" in html
    assert "openPerformance(row.session_id)" in html


def test_ai_report_markdown_preview_renders_structured_blocks() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "md-table-wrap" in html
    assert "parseTableLine" in html
    assert "md-step-card" in html
    assert "md-callout" in html
    assert "isTableSep" in html
