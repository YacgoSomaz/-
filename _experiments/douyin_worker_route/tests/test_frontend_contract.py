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


def test_ai_replay_workspace_keeps_the_report_header_readable_at_narrow_widths() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert 'class="ai-report-title"' in html
    assert ".ai-report-title{flex:0 0 auto;white-space:nowrap" in html
    assert ".ai-report-actions{display:flex;flex:1 1 360px;flex-wrap:wrap" in html
    assert "@media(max-width:1180px){.ai-workspace{grid-template-columns:1fr;height:auto;max-height:none;overflow:visible}" in html
    assert "@media(max-width:760px)" in html
    assert ".ai-workspace{gap:8px}" in html


def test_ai_followup_context_is_scoped_to_selected_replay() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "aiChatStore" in html
    assert "aiChatContextKey" in html
    assert "aiChatRowKey" in html
    assert "watch(aiChatKey,activateAiChatContext" in html
    assert "const contextMessages=aiChatStore[key]||aiMessages.value" in html


def test_settings_uses_mobile_account_login_not_card_key_activation() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "手机号登录" in html
    assert "/api/account/send-code" in html
    assert "/api/account/login" in html
    assert "/api/account/recharge-url" in html
    assert "续费/账户中心" in html
    assert "卡密" not in html
    assert "/api/license/" not in html


def test_account_badge_uses_signed_product_membership_not_rbac_role() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "account.membership_status==='active'?'复盘虾会员':'普通用户'" in html
    assert "account.role==='regular'?'普通用户':account.role" not in html


def test_update_ui_only_blocks_when_the_signed_release_requires_an_upgrade() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "updateState.mandatory" in html
    assert "showMandatoryUpdate" in html
    assert "const {ElMessage,ElMessageBox}=ElementPlus;" in html
    assert "closeOnClickModal:false" in html
    assert "closeOnPressEscape:false" in html
    assert "body:JSON.stringify({silent:false})" in html
    assert "安装向导已启动" in html


def test_running_client_receives_release_events_with_periodic_fallback() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "new EventSource(updateEventUrl)" in html
    assert "/api/v1/releases/events?product_id=" in html
    assert "addEventListener('release'" in html
    assert "checkUpdate(true)" in html
    assert "setInterval(()=>checkUpdate(true),60000)" in html
    assert "updateEventSource.close()" in html


def test_visible_version_labels_use_the_runtime_update_state() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "直播复盘侠 v1.0.0" not in html
    assert "updateState.current_version||'1.0.0'" not in html
    assert "updateState.current_version||'—'" in html


def test_account_login_uses_a_dedicated_modal_instead_of_an_inline_settings_form() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert 'class="account-trigger"' in html
    assert '@click="account.login_dialog=true"' in html
    assert '<el-dialog v-model="account.login_dialog"' in html
    assert 'class="account-login-dialog"' in html
    assert ':close-on-click-modal="false"' in html
    assert ':close-on-press-escape="false"' in html
    assert ':show-close="true"' in html
    assert 'autocomplete="one-time-code"' in html
    assert 'inputmode="numeric"' in html
    assert 'class="account-code-button"' in html
    assert '获取验证码' in html
    assert 'placeholder="请输入验证码" @keyup.enter="loginAccount"></el-input><button' in html
    assert "login_dialog:false" in html
    assert "account.login_dialog=false" in html
    assert '验证码仅用于本次登录验证' in html
    assert '<el-input v-model="accountPhone" size="small" style="width:150px"' not in html


def test_logged_out_clicks_are_gated_before_business_validation() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert '@click.capture="account.guard_click"' in html
    assert "account.guard_click=(event)=>" in html
    assert "target?.closest('button,[role=\"button\"]')" in html
    assert "请先登录账号后再使用此功能" in html
    assert "account.login_dialog=true" in html
    assert "data-account-public" in html
    assert "button.closest('.account-login-dialog')" in html
    assert "account.entitlements.includes('livewatch')" in html
    assert "当前账号未开通复盘虾会员权益" in html
    assert "data-membership-public" in html
    assert "body.detail||body.error||message" in html
    assert "r.detail||r.error||'解析失败'" in html
    assert "等待套餐上线" not in html
    assert "套餐上线后" not in html


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


def test_comment_lead_result_keeps_visible_capture_counts() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "最近采集：读取" in html
    assert "平台显示" in html
    assert "r.captured||0" in html


def test_sensitive_word_review_distinguishes_risk_candidates_from_advisories() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "另有 {{sensitiveSummaryValue('advisory_total')||0}} 项提示词" in html
    assert 'label="替换建议"' in html
    assert "row.counts_as_risk?'风险候选':'提示词'" in html


def test_live_console_uses_real_recording_room_selection_with_a_compact_workbench_layout() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "直播工作台" in html
    assert "选择直播场次" in html
    assert ":value=\"room.session_id\"" in html
    assert "room.phase==='recording'?'录制中':'已结束'" in html
    assert "暂无可查看的直播场次" in html
    assert "fmtElapsed(liveConsole.stats.recording_seconds)" in html
    assert "session_start=" in html
    assert "/api/live-workbench" in html
    assert "暂无正在录制的直播间" in html
    assert "live-console-shell" in html
    assert "live-console-grid" in html
    assert "liveConsole.aiEnabled=!liveConsole.aiEnabled" in html
    assert "直播预览" in html
    assert "实时话术" in html
    assert "当前状态" in html
    assert "当前诊断" in html
    assert "实时监控" in html
    assert "话术时间线" in html
    assert "复盘准备" in html


def test_dashboard_batch_controls_are_exposed_and_report_backend_failures() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "proxyTesting,batchControlBusy,account" in html
    assert "startRoom,stopRoom,startAll,stopAll,toggleRoom" in html
    assert "payload.detail||payload.error||'服务未确认执行'" in html
    assert "全部开始' : '全部停止".replace(" ", "") in html.replace(" ", "")


def test_live_console_uses_a_click_to_expand_preview_and_shows_current_local_evidence() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "live-preview-thumb" in html
    assert "live-preview-video" in html
    assert "/api/live-preview/" in html
    assert "最多约 60 秒延迟" in html
    assert "放大查看" in html
    assert 'v-model="liveConsole.previewExpanded"' in html
    assert "已接入本机实时证据" in html
    assert "AI 建议默认关闭" in html
    assert "liveConsole.previewExpanded=!liveConsole.previewExpanded" in html


def test_live_console_preview_is_a_bounded_thumbnail_for_portrait_and_landscape_sources() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "previewOrientation:'unknown'" in html
    assert '@loadedmetadata="updatePreviewOrientation"' in html
    assert "function updatePreviewOrientation(event)" in html
    assert "fetchLiveWorkbench,updatePreviewOrientation,filteredRooms" in html
    assert "竖屏 9:16" in html
    assert "横屏 16:9" in html
    assert ".live-console-grid{grid-template-columns:minmax(320px,360px)" in html
    assert ".live-preview{width:100%;max-width:360px" in html
    assert ".live-preview .live-preview-stage{height:230px" in html
    assert ".live-preview-stage.is-portrait .live-preview-video" in html
    assert ".live-preview-stage.is-landscape .live-preview-video" in html
    assert "object-fit:contain" in html
    assert "max-height:72vh" in html
    assert "不额外打开平台页面" in html
    assert "live-preview-video-expanded" in html


def test_live_workbench_owns_the_efficiency_and_ai_replay_sub_navigation() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert 'liveConsoleMenuOpen' in html
    assert '@click="toggleLiveConsoleMenu"' in html
    assert '@click.stop="selectLiveConsoleView(\'liveConsole\')">实时监控' in html
    assert '@click.stop="selectLiveConsoleView(\'pre\')">直播效能' in html
    assert '@click.stop="selectLiveConsoleView(\'review\')">AI直播复盘' in html
    assert "view.value==='pre'||view.value==='review'?{key:'liveConsole'" in html
    assert "{key:'review',label:'AI复盘'" not in html


def test_comment_lead_table_header_shows_current_row_count() -> None:
    html = FRONTEND.read_text(encoding="utf-8")
    assert "当前显示 {{filteredLeadRows.length}} 条" in html
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
