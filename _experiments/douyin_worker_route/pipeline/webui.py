"""本地控制台：浏览器一键管理直播间（加/删、启停、看状态）。

只在本机 127.0.0.1 监听，纯个人自用。后端复用 RoomManager 托管弹幕+音频+转写，
前端是 Vue 3 + Element Plus 单页（CDN 加载，无需 node/npm），轮询 /api/status 刷新。

启动：
  python -m pipeline.webui            # 默认 127.0.0.1:8848
  python -m pipeline.webui --port 9000
然后浏览器打开 http://127.0.0.1:8848
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import quote

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import ai_report, anchor_profiles, browser_cookies, comment_leads, config, diagnostics, license_client, license_manager, license_policy, license_refresh, performance_analysis, short_video, short_video_ai
from . import export as export_mod
from .anchor_resolver import AnchorResolveError, resolve_anchor
from .manager import MAX_ACTIVE_ROOMS, RoomManager
from .package_assets import package_asset_dir
from .web_security import LOCAL_UI_ORIGIN_REGEX

app = FastAPI(title="直播复盘侠")

# ---------- 可选 HTTP Basic 登录（公网穿透用，本地默认无密码）----------
# 设了环境变量 LIVEWATCH_AUTH="用户名:密码" 才启用；不设则行为与从前完全一致（本地直连无门槛）。
# 内网穿透/映射公网时务必设置，否则任何人拿到地址即可操作面板、触发本机弹浏览器、读写数据。
_AUTH_RAW = (os.environ.get("LIVEWATCH_AUTH") or "").strip()
_AUTH_USER, _, _AUTH_PASS = _AUTH_RAW.partition(":")


@app.middleware("http")
async def _basic_auth(request: Request, call_next):
    if not _AUTH_RAW:  # 未配置 → 不拦截，本地自用零门槛
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            user, _, pwd = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        except Exception:  # noqa: BLE001  畸形头按未授权处理
            user = pwd = ""
        # 常量时间比较，避免时序侧信道
        if secrets.compare_digest(user, _AUTH_USER) and secrets.compare_digest(pwd, _AUTH_PASS):
            return await call_next(request)
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="直播复盘侠"'},
        content="需要登录",
    )


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=LOCAL_UI_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
)
_mgr = RoomManager()


def _run_blocking(fn, *args, **kwargs):
    """Run browser-heavy sync work in a clean worker thread."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn, *args, **kwargs).result()
_PACKAGE_ASSETS = package_asset_dir(__file__)
_FRONTEND = _PACKAGE_ASSETS / "frontend.html"
_STATIC = _PACKAGE_ASSETS / "static"
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


def _performance_ai_loop() -> None:
    """Analyze finished/stable sessions in the background without blocking pages."""
    if os.environ.get("LIVEWATCH_DISABLE_PERF_AI_LOOP"):
        return
    while True:
        try:
            performance_analysis.analyze_ready_sessions(limit=1)
        except Exception:
            # Background analysis must never take down recording/control APIs.
            pass
        time.sleep(60)


threading.Thread(target=_performance_ai_loop, name="performance-ai-loop", daemon=True).start()
threading.Thread(target=short_video.prewarm_browser, name="short-video-browser-prewarm", daemon=True).start()


def _license_refresh_loop() -> None:
    """Refresh signed entitlement periodically without disturbing local work."""
    while True:
        try:
            license_refresh.refresh_once()
        except Exception:
            pass
        time.sleep(config.LICENSE_REFRESH_INTERVAL_SEC)


threading.Thread(target=_license_refresh_loop, name="license-refresh-loop", daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _FRONTEND.read_text(encoding="utf-8")


@app.get("/api/status")
def api_status() -> JSONResponse:
    return JSONResponse({
        "rooms": _mgr.status(),
        "pending": _mgr.pending_status(),
        "risk_control": _mgr.risk_control_status(),
        "limits": {"max_active_rooms": MAX_ACTIVE_ROOMS},
    })


@app.get("/api/diagnostics")
def api_diagnostics() -> JSONResponse:
    """Read-only local health snapshot. Never performs network requests."""
    snapshot = diagnostics.build_snapshot(config)
    snapshot["recent_errors"] = _mgr.recent_errors()
    return JSONResponse(snapshot)


@app.post("/api/cookie/remint")
def api_cookie_remint(rid: str | None = Query(default=None)) -> JSONResponse:
    """Open the user's browser for an explicit trust-cookie refresh."""
    if not rid:
        rooms = _mgr.status()
        rid = rooms[0]["rid"] if rooms else None
    result = browser_cookies.remint(rid)
    if result["ok"]:
        _mgr.clear_risk_cooldown()
    return JSONResponse(result, status_code=200 if result["ok"] else 503)


@app.get("/api/short-video/cookie/status")
def api_short_video_cookie_status() -> JSONResponse:
    """短视频主页读取使用独立登录态；本接口只读状态。"""
    return JSONResponse({"ok": True, **short_video.short_video_cookie_status()})


@app.post("/api/short-video/cookie/remint")
def api_short_video_cookie_remint(payload: dict[str, object] = Body(default={})) -> JSONResponse:
    """用户手动打开抖音窗口，给短视频深度读取授权。"""
    start_url = str(payload.get("start_url") or "").strip()
    result = short_video.remint_short_video_cookie(start_url or None)
    return JSONResponse(result, status_code=200 if result.get("ok") else 503)


@app.post("/api/rooms/batch")
def api_batch(ids: list[str] = Body(..., embed=True)) -> JSONResponse:
    """批量导入房间号；返回新增数（已存在的自动跳过）。

    注意：本路由必须声明在 /api/rooms/{rid} 之前，否则 'batch' 会被当成 rid。
    """
    added = sum(_mgr.add_room(str(i)) for i in ids)
    return JSONResponse({"added": added, "total": len(ids)})


@app.post("/api/rooms/{rid}")
def api_add(rid: str) -> JSONResponse:
    return JSONResponse({"ok": _mgr.add_room(rid)})


@app.post("/api/anchors")
def api_add_anchor(anchor: dict[str, object] = Body(...)) -> JSONResponse:
    """Add or update a resolved anchor while preserving its display metadata."""
    rid = str(anchor.get("web_id") or anchor.get("room_id") or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="未解析到有效的直播号或房间 ID")
    cached = anchor_profiles.save_profile(rid, anchor)
    changed = _mgr.add_room(
        rid,
        {
            "anchor_name": cached.get("anchor_name") or anchor.get("anchor_name"),
            "avatar_url": cached.get("avatar_url") or anchor.get("avatar_url"),
            "source_url": cached.get("source_url") or anchor.get("source_url"),
            "sec_user_id": cached.get("sec_user_id") or anchor.get("sec_user_id"),
        },
    )
    return JSONResponse({"ok": True, "changed": changed, "rid": rid})


@app.middleware("http")
async def _license_gate(request: Request, call_next):
    feature = license_policy.feature_for_request(request.method, request.url.path)
    if feature:
        try:
            license_manager.require_feature(feature)
        except license_manager.LicenseFeatureError as exc:
            return JSONResponse(
                status_code=403,
                content={"detail": f"此功能需要有效商业授权：{exc}"},
            )
    return await call_next(request)


@app.get("/api/avatars/{rid}")
def api_avatar(rid: str) -> FileResponse:
    path = anchor_profiles.avatar_file(rid)
    if path is None:
        raise HTTPException(status_code=404, detail="头像缓存不存在")
    return FileResponse(path)


@app.post("/api/anchors/{rid}/refresh")
def api_anchor_refresh(rid: str) -> JSONResponse:
    """Refresh one anchor profile and cache its avatar for historical views."""
    rid = str(rid or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="缺少直播号")
    try:
        result = resolve_anchor(
            f"https://live.douyin.com/{rid}",
            cookie_header=browser_cookies.cached_cookie_header(),
        )
    except AnchorResolveError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    anchor = {
        "source_url": result.source_url or f"https://live.douyin.com/{rid}",
        "anchor_name": result.anchor_name,
        "avatar_url": result.avatar_url,
        "sec_user_id": result.sec_user_id,
        "web_id": result.web_id or rid,
        "room_id": result.room_id,
        "is_live": result.is_live,
    }
    cached = anchor_profiles.save_profile(rid, anchor)
    _mgr.update_room_profile(rid, cached)
    anchor.update({k: v for k, v in cached.items() if v})
    return JSONResponse({"ok": True, "anchor": anchor})


@app.post("/api/pending")
def api_add_pending(anchor: dict[str, object] = Body(...)) -> JSONResponse:
    """登记一个未开播主播（只有 sec_user_id）。后台定期探测，开播后自动转为监听房间。"""
    sec_user_id = str(anchor.get("sec_user_id") or "").strip()
    if not sec_user_id:
        raise HTTPException(status_code=400, detail="未解析到主播身份（缺少 sec_user_id）")
    result = _mgr.add_pending(
        sec_user_id,
        {
            "anchor_name": anchor.get("anchor_name"),
            "avatar_url": anchor.get("avatar_url"),
            "source_url": anchor.get("source_url"),
        },
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=str(result.get("reason") or "登记失败"))
    return JSONResponse({"ok": True, "sec_user_id": sec_user_id})


@app.delete("/api/pending/{sec_user_id}")
def api_remove_pending(sec_user_id: str) -> JSONResponse:
    return JSONResponse({"ok": _mgr.remove_pending(sec_user_id)})


@app.get("/api/video-quality")
def api_get_video_quality() -> JSONResponse:
    return JSONResponse({
        "quality": config.get_video_quality(),
        "choices": list(config.VIDEO_QUALITY_CHOICES),
    })


@app.put("/api/video-quality")
def api_set_video_quality(quality: str = Body(..., embed=True)) -> JSONResponse:
    if not config.set_video_quality(quality):
        raise HTTPException(status_code=400, detail="无效的画质选项")
    return JSONResponse({"ok": True, "quality": config.get_video_quality()})


@app.delete("/api/rooms/{rid}")
def api_remove(rid: str) -> JSONResponse:
    return JSONResponse({"ok": _mgr.remove_room(rid)})


@app.post("/api/rooms/{rid}/start")
def api_start(rid: str) -> JSONResponse:
    return JSONResponse({"ok": _mgr.start_room(rid)})


@app.post("/api/rooms/{rid}/stop")
def api_stop(rid: str) -> JSONResponse:
    return JSONResponse({"ok": _mgr.stop_room(rid)})


@app.post("/api/rooms/{rid}/video")
def api_set_video(rid: str, enabled: bool = Body(..., embed=True)) -> JSONResponse:
    """切换房间是否同时录制视频（默认仅录音）。下一段 ffmpeg 生效。"""
    return JSONResponse({"ok": True, "changed": _mgr.set_record_video(rid, enabled)})


@app.post("/api/start_all")
def api_start_all() -> JSONResponse:
    return JSONResponse({"started": _mgr.start_all()})


@app.post("/api/stop_all")
def api_stop_all() -> JSONResponse:
    return JSONResponse({"stopped": _mgr.stop_all()})


@app.post("/api/export")
def api_export() -> JSONResponse:
    """跑一次导出：每房间 xlsx + md + summary.csv 落到 exports/。"""
    bundles = export_mod.export_all()
    return JSONResponse({"rooms": len(bundles), "dir": str(export_mod.config.EXPORT_DIR)})


@app.get("/api/license/status")
def api_license_status() -> JSONResponse:
    """Return local license status without exposing full device fingerprint."""
    status = license_manager.public_status()
    status["device_hash_prefix"] = license_manager.current_device_hash()[:12]
    return JSONResponse({"ok": True, "license": status})


@app.get("/api/license/device")
def api_license_device() -> JSONResponse:
    return JSONResponse({"ok": True, "device_hash_prefix": license_manager.current_device_hash()[:12]})


@app.post("/api/license/install")
def api_license_install(payload: dict[str, object] = Body(...)) -> JSONResponse:
    license_doc = payload.get("license")
    if isinstance(license_doc, str):
        try:
            license_doc = json.loads(license_doc)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="授权内容不是合法 JSON") from exc
    if not isinstance(license_doc, dict):
        raise HTTPException(status_code=400, detail="请提交授权包")
    status = license_manager.install_license_doc(license_doc)
    if not status.ok:
        raise HTTPException(status_code=400, detail=status.reason)
    public = license_manager.public_status()
    public["device_hash_prefix"] = license_manager.current_device_hash()[:12]
    return JSONResponse({"ok": True, "license": public})


@app.post("/api/license/activate")
def api_license_activate(payload: dict[str, object] = Body(...)) -> JSONResponse:
    card_key = str(payload.get("card_key") or "").strip()
    try:
        status = license_client.activate_card_key(card_key)
    except license_client.LicenseClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status["device_hash_prefix"] = license_manager.current_device_hash()[:12]
    return JSONResponse({"ok": True, "license": status})


@app.post("/api/license/refresh")
def api_license_refresh() -> JSONResponse:
    try:
        status = license_client.refresh_license()
    except license_client.LicenseClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status["device_hash_prefix"] = license_manager.current_device_hash()[:12]
    return JSONResponse({"ok": True, "license": status})


@app.get("/api/ai/config")
def api_ai_config() -> JSONResponse:
    """Read AI provider settings without exposing the API key."""
    return JSONResponse(ai_report.public_config())


@app.put("/api/ai/config")
def api_ai_save_config(payload: dict[str, object] = Body(...)) -> JSONResponse:
    return JSONResponse(ai_report.save_config(payload))


@app.post("/api/ai/test")
def api_ai_test() -> JSONResponse:
    try:
        return JSONResponse(ai_report.test_config())
    except ai_report.AIReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ai/report")
def api_ai_report(payload: dict[str, object] = Body(...)) -> JSONResponse:
    raw = payload.get("rids") or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="rids 必须是数组")
    try:
        return JSONResponse(ai_report.generate_report([str(x) for x in raw]))
    except ai_report.AIReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ai/report/stream")
def api_ai_report_stream(payload: dict[str, object] = Body(...)) -> StreamingResponse:
    raw = payload.get("rids") or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="rids 必须是数组")

    def events():
        try:
            for event in ai_report.generate_report_events([str(x) for x in raw]):
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        except ai_report.AIReportError as exc:
            yield "data: " + json.dumps(
                {"type": "error", "message": str(exc), "progress": 100},
                ensure_ascii=False,
            ) + "\n\n"
        except Exception as exc:  # noqa: BLE001
            yield "data: " + json.dumps(
                {"type": "error", "message": f"AI复盘异常：{exc}", "progress": 100},
                ensure_ascii=False,
            ) + "\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/ai/chat")
def api_ai_chat(payload: dict[str, object] = Body(...)) -> JSONResponse:
    raw = payload.get("rids") or []
    messages = payload.get("messages") or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="rids 必须是数组")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages 必须是数组")
    try:
        return JSONResponse(ai_report.answer_question([str(x) for x in raw], messages))
    except ai_report.AIReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ai/chat/stream")
def api_ai_chat_stream(payload: dict[str, object] = Body(...)) -> StreamingResponse:
    raw = payload.get("rids") or []
    messages = payload.get("messages") or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="rids 必须是数组")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages 必须是数组")

    def events():
        try:
            for event in ai_report.answer_question_events([str(x) for x in raw], messages):  # type: ignore[arg-type]
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        except ai_report.AIReportError as exc:
            yield "data: " + json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n\n"
        except Exception as exc:  # noqa: BLE001
            yield "data: " + json.dumps({"type": "error", "message": f"追问异常：{exc}"}, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/ai/word-cloud")
def api_ai_word_cloud(payload: dict[str, object] = Body(...)) -> JSONResponse:
    raw = payload.get("rids") or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="rids 必须是数组")
    try:
        return JSONResponse(ai_report.word_cloud([str(x) for x in raw]))
    except ai_report.AIReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/ai/report/download")
def api_ai_report_download(filename: str = Query(...)) -> Response:
    safe_name = Path(filename).name
    path = (config.AI_REPORT_DIR / safe_name).resolve()
    root = config.AI_REPORT_DIR.resolve()
    if root not in path.parents and path != root:
        raise HTTPException(status_code=400, detail="无效文件名")
    if not path.is_file():
        if path.suffix.lower() == ".pdf":
            try:
                path = ai_report.ensure_pdf_report(safe_name)
            except ai_report.AIReportError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        else:
            raise HTTPException(status_code=404, detail="报告不存在")
    media_type = "application/pdf" if path.suffix.lower() == ".pdf" else "text/markdown; charset=utf-8"
    return Response(
        content=path.read_bytes(),
        media_type=media_type,
        headers={"Content-Disposition": _download_disposition(safe_name)},
    )


@app.get("/api/ai/report/view")
def api_ai_report_view(filename: str = Query(...)) -> Response:
    safe_name = Path(filename).name
    path = (config.AI_REPORT_DIR / safe_name).resolve()
    root = config.AI_REPORT_DIR.resolve()
    if root not in path.parents and path != root:
        raise HTTPException(status_code=400, detail="无效文件名")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="报告不存在")
    suffix = path.suffix.lower()
    if suffix == ".html":
        return HTMLResponse(ai_report.report_view_html(path))
    return Response(content=path.read_bytes(), media_type="text/markdown; charset=utf-8")


@app.get("/api/data/rooms")
def api_data_rooms() -> JSONResponse:
    """历史数据清单，与当前监听清单解耦。"""
    return JSONResponse({"rooms": export_mod.data_room_summaries()})


@app.get("/api/performance/sessions")
def api_performance_sessions() -> JSONResponse:
    """效能分析首页：当前版本按直播号聚合为可分析场次。"""
    return JSONResponse({"sessions": performance_analysis.list_session_summaries()})


@app.get("/api/performance/sessions/{session_id}")
def api_performance_session_detail(session_id: str) -> JSONResponse:
    """单场效能详情。当前 session_id 即直播号；后续可替换为真实场次 id。"""
    try:
        detail = performance_analysis.build_session_analysis(session_id, include_detail=True)
    except Exception as exc:  # noqa: BLE001  页面不因单房间脏数据崩溃
        raise HTTPException(status_code=500, detail=f"效能分析失败：{exc}") from exc
    return JSONResponse({"session": detail})


@app.post("/api/performance/sessions/{session_id}/analyze")
def api_performance_session_analyze(session_id: str, force: bool = Body(default=True, embed=True)) -> JSONResponse:
    """手动触发/重跑单场 AI 效能分析。"""
    try:
        detail = performance_analysis.analyze_room(session_id, force=bool(force))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"AI效能分析失败：{exc}") from exc
    return JSONResponse({"session": detail})


@app.post("/api/performance/analyze-ready")
def api_performance_analyze_ready(limit: int = Body(default=1, embed=True)) -> JSONResponse:
    """手动扫描已下播且稳定超过 5 分钟的直播，最多分析 limit 场。"""
    try:
        result = performance_analysis.analyze_ready_sessions(limit=max(1, min(int(limit), 5)))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"扫描AI效能分析失败：{exc}") from exc
    return JSONResponse(result)


@app.post("/api/data/clear-all")
def api_clear_all_data() -> JSONResponse:
    """一键清除所有录制数据（录音/视频/转写/弹幕/导出）。保留主播列表、登录、设置。"""
    return JSONResponse(_mgr.clear_all_data())


@app.delete("/api/data/{rid}")
def api_delete_room_data(rid: str) -> JSONResponse:
    """彻底清除单房间数据；删除前先停止并移出监听清单。"""
    _mgr.remove_room(rid)
    try:
        deleted = export_mod.delete_room_data(rid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "deleted": deleted})


@app.get("/api/export/summary.csv")
def api_export_csv() -> Response:
    """直接下载 summary.csv（Excel 可开），实时根据当前库生成。"""
    bundles = export_mod.export_all()
    data = export_mod.summary_csv_bytes(bundles)
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=summary.csv"},
    )


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/api/export/selection.xlsx")
def api_export_selection_xlsx(rids: str = Query(...)) -> Response:
    """下载用户勾选房间的完整总表。"""
    selected = [rid.strip() for rid in rids.split(",") if rid.strip()]
    if not selected:
        raise HTTPException(status_code=400, detail="至少选择一个房间")
    data = export_mod.selected_xlsx_bytes(selected)
    return Response(
        content=data,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": _download_disposition("所选主播汇总.xlsx")},
    )


@app.get("/api/export/summary.xlsx")
def api_export_summary_xlsx() -> Response:
    """下载全房间总表 Excel：总表 + 发言人汇总 + 分房间话术 + 弹幕 + 直播数据。

    注意：本路由必须在 /api/export/{rid}.xlsx 之前声明，否则 'summary' 会被当成 rid。
    """
    bundles = export_mod.export_all()
    data = export_mod.summary_xlsx_bytes(bundles)
    return Response(
        content=data,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": _download_disposition("直播复盘汇总.xlsx")},
    )


@app.get("/api/export/{rid}.xlsx")
def api_export_xlsx(rid: str) -> Response:
    """下载单房间 Excel：总表、发言人汇总、话术、时间轴、弹幕和直播数据。"""
    data = export_mod.xlsx_bytes(rid)
    return Response(
        content=data,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": _download_disposition(export_mod.room_export_filename(rid))},
    )


_EXPORT_DIR_CONF = config.DATA_DIR / "export_dir.txt"


def _get_export_dir() -> Path:
    if _EXPORT_DIR_CONF.is_file():
        custom = _EXPORT_DIR_CONF.read_text(encoding="utf-8").strip()
        if custom:
            return Path(custom)
    return config.EXPORT_DIR


def _save_xlsx(data: bytes, filename: str) -> Path:
    export_dir = _get_export_dir()
    export_dir.mkdir(parents=True, exist_ok=True)
    dest = export_dir / filename
    dest.write_bytes(data)
    return dest


@app.get("/api/export-dir")
def api_get_export_dir() -> JSONResponse:
    return JSONResponse({"dir": str(_get_export_dir())})


@app.put("/api/export-dir")
def api_set_export_dir(dir: str = Body(..., embed=True)) -> JSONResponse:
    p = Path(dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    _EXPORT_DIR_CONF.write_text(str(p), encoding="utf-8")
    return JSONResponse({"ok": True, "dir": str(p)})


@app.post("/api/pick-folder")
def api_pick_folder() -> JSONResponse:
    """弹出系统文件夹选择对话框，返回用户选中的路径。"""
    import subprocess as _sp, sys as _sys
    if _sys.platform == "darwin":
        scpt = (
            'set f to POSIX path of (choose folder with prompt "选择导出目录")\n'
            'return f'
        )
        r = _sp.run(["osascript", "-e", scpt], capture_output=True, text=True, timeout=120)
        chosen = (r.stdout or "").strip().rstrip("/")
    else:
        ps = (
            'Add-Type -AssemblyName System.Windows.Forms;'
            '$d=New-Object System.Windows.Forms.FolderBrowserDialog;'
            "$d.Description='选择导出目录';"
            "$d.RootFolder='MyComputer';"
            "if($d.ShowDialog()-eq'OK'){$d.SelectedPath}"
        )
        r = _sp.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=120,
            creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
        )
        chosen = (r.stdout or "").strip()
    if not chosen:
        return JSONResponse({"ok": False, "cancelled": True})
    return JSONResponse({"ok": True, "dir": chosen})


@app.get("/api/proxy")
def api_get_proxy() -> JSONResponse:
    from . import proxy_conf
    return JSONResponse({"proxy": proxy_conf.get_proxy_url()})


@app.put("/api/proxy")
def api_set_proxy(url: str = Body("", embed=True)) -> JSONResponse:
    from . import proxy_conf
    proxy_conf.save_proxy(url)
    return JSONResponse({"ok": True, "proxy": proxy_conf.get_proxy_url()})


@app.post("/api/proxy/test")
def api_test_proxy() -> JSONResponse:
    """快速测试当前代理是否能连通抖音。"""
    from . import proxy_conf
    from .fingerprint import PAGE_HEADERS
    import requests as _req
    px = proxy_conf.requests_proxies()
    try:
        r = _req.get(
            "https://live.douyin.com/",
            headers=PAGE_HEADERS,
            proxies=px or {},
            timeout=10,
        )
        return JSONResponse({"ok": True, "status": r.status_code, "proxy": proxy_conf.get_proxy_url() or "直连"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/export/save/summary")
def api_save_summary() -> JSONResponse:
    bundles = export_mod.export_all()
    data = export_mod.summary_xlsx_bytes(bundles)
    dest = _save_xlsx(data, "直播复盘汇总.xlsx")
    return JSONResponse({"ok": True, "path": str(dest), "dir": str(dest.parent)})


@app.post("/api/export/save/selection")
def api_save_selection(rids: list[str] = Body(..., embed=True)) -> JSONResponse:
    if not rids:
        raise HTTPException(status_code=400, detail="至少选择一个房间")
    data = export_mod.selected_xlsx_bytes(rids)
    dest = _save_xlsx(data, "所选主播汇总.xlsx")
    return JSONResponse({"ok": True, "path": str(dest), "dir": str(dest.parent)})


@app.post("/api/export/save/sample")
def api_save_sample() -> JSONResponse:
    """生成一份演示导出文件（内存构造，不读写任何真实数据），让新用户直观看到导出格式。

    路由必须声明在 /api/export/save/{rid} 之前，否则 'sample' 会被当成 rid。
    """
    data = export_mod.sample_xlsx_bytes()
    dest = _save_xlsx(data, "示例导出_演示数据.xlsx")
    return JSONResponse({"ok": True, "path": str(dest), "dir": str(dest.parent)})


@app.post("/api/export/save/{rid}")
def api_save_room(rid: str) -> JSONResponse:
    data = export_mod.xlsx_bytes(rid)
    dest = _save_xlsx(data, export_mod.room_export_filename(rid))
    return JSONResponse({"ok": True, "path": str(dest), "dir": str(dest.parent)})


def _open_path(p: Path) -> None:
    import subprocess as _sp, sys as _sys
    if _sys.platform == "darwin":
        _sp.Popen(["open", str(p)])
    elif _sys.platform == "win32":
        import os; os.startfile(p)  # type: ignore[attr-defined]
    else:
        _sp.Popen(["xdg-open", str(p)])


@app.post("/api/open-folder")
def api_open_folder(path: str = Body(..., embed=True)) -> JSONResponse:
    target = Path(path).resolve()
    if target.is_file():
        _open_path(target.parent)
    elif target.is_dir():
        _open_path(target)
    return JSONResponse({"ok": True})


def _download_disposition(filename: str) -> str:
    """Standards-compatible UTF-8 download name for browsers and WebView2."""
    return f"attachment; filename*=UTF-8''{quote(filename)}"


@app.post("/api/anchor/resolve")
def api_anchor_resolve(input_text: str = Body(..., embed=True)) -> JSONResponse:
    """解析抖音分享文案 / 链接 / 直播号为主播身份信息。"""
    try:
        # Reuse the existing cached trust cookie for richer public room metadata.
        # This never opens a browser or mutates the cookie cache.
        result = resolve_anchor(
            input_text,
            cookie_header=browser_cookies.cached_cookie_header(),
        )
        rid = str(result.web_id or result.room_id or "").strip()
        anchor = {
            "source_url": result.source_url,
            "anchor_name": result.anchor_name,
            "avatar_url": result.avatar_url,
            "sec_user_id": result.sec_user_id,
            "web_id": result.web_id,
            "room_id": result.room_id,
            "is_live": result.is_live,
        }
        if rid:
            cached = anchor_profiles.save_profile(rid, anchor)
            anchor.update({k: v for k, v in cached.items() if v})
        return JSONResponse({
            "ok": True,
            "anchor": anchor,
        })
    except AnchorResolveError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/short-video/resolve-profile")
def api_short_video_resolve_profile(payload: dict[str, object] = Body(...)) -> JSONResponse:
    """解析短视频中心的抖音主页链接，并读取最近作品卡片。"""
    try:
        input_text = str(payload.get("input_text") or "")
        recent_count = int(payload.get("recent_count") or 5)
        result = short_video.resolve_profile(input_text, recent_count=recent_count)
        return JSONResponse({
            "ok": True,
            "profile": result["profile"],
            "videos": result["videos"],
            "warning": result.get("warning", ""),
            "message": "账号主页已识别，已读取最近作品。",
        })
    except short_video.ShortVideoError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/short-video/resolve-profile/stream")
def api_short_video_resolve_profile_stream(payload: dict[str, object] = Body(...)) -> StreamingResponse:
    """流式解析短视频主页；作品抓到一条就推一条。"""

    def _gen():
        try:
            input_text = str(payload.get("input_text") or "")
            recent_count = int(payload.get("recent_count") or 5)
            for event in short_video.iter_resolve_profile_events(input_text, recent_count=recent_count):
                yield json.dumps({"ok": True, **event}, ensure_ascii=False) + "\n"
        except short_video.ShortVideoError as exc:
            yield json.dumps({"ok": False, "type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
        except Exception as exc:  # noqa: BLE001
            yield json.dumps({"ok": False, "type": "error", "message": f"解析失败：{type(exc).__name__}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(_gen(), media_type="application/x-ndjson; charset=utf-8")


def _short_video_parse_cache_payload(payload: dict[str, object]) -> dict[str, object]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
    safe_candidates: list[dict[str, object]] = []
    for item in candidates[:150]:
        if not isinstance(item, dict):
            continue
        safe_candidates.append({
            "id": str(item.get("id") or "")[:128],
            "title": str(item.get("title") or "")[:300],
            "url": str(item.get("url") or "")[:1000],
            "cover_url": str(item.get("cover_url") or "")[:1200],
            "play_url": str(item.get("play_url") or "")[:1200],
            "like_count": item.get("like_count"),
            "comment_count": item.get("comment_count") or 0,
            "collect_count": item.get("collect_count") or 0,
            "share_count": item.get("share_count") or 0,
            "pinned": bool(item.get("pinned")),
            "source": str(item.get("source") or "profile")[:40],
            "selected": bool(item.get("selected")),
        })
    selected_keys = payload.get("selectedKeys")
    if not isinstance(selected_keys, list):
        selected_keys = []
    return {
        "version": 2,
        "profileUrl": str(payload.get("profileUrl") or "")[:1200],
        "profile": payload.get("profile") if isinstance(payload.get("profile"), dict) else None,
        "initialCount": int(payload.get("initialCount") or 10),
        "targetCount": int(payload.get("targetCount") or max(10, len(safe_candidates))),
        "customAppendCount": int(payload.get("customAppendCount") or 20),
        "positioning": payload.get("positioning") if isinstance(payload.get("positioning"), dict) else None,
        "candidates": safe_candidates,
        "selectedKeys": [str(x)[:256] for x in selected_keys[:150]],
        "savedAt": int(time.time() * 1000),
    }


@app.get("/api/short-video/parse-cache")
def api_short_video_parse_cache_get() -> JSONResponse:
    try:
        path = config.SHORT_VIDEO_PARSE_CACHE_JSON
        if not path.exists():
            return JSONResponse({"ok": True, "cache": None})
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
        return JSONResponse({"ok": True, "cache": data})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"读取缓存失败：{type(exc).__name__}"}, status_code=500)


@app.post("/api/short-video/parse-cache")
def api_short_video_parse_cache_save(payload: dict[str, object] = Body(...)) -> JSONResponse:
    try:
        data = _short_video_parse_cache_payload(payload)
        config.SHORT_VIDEO_PARSE_CACHE_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return JSONResponse({"ok": True})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"保存缓存失败：{type(exc).__name__}"}, status_code=500)


@app.delete("/api/short-video/parse-cache")
def api_short_video_parse_cache_delete() -> JSONResponse:
    try:
        config.SHORT_VIDEO_PARSE_CACHE_JSON.unlink(missing_ok=True)
        return JSONResponse({"ok": True})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"清空缓存失败：{type(exc).__name__}"}, status_code=500)


@app.get("/api/short-video/jobs")
def api_short_video_jobs(limit: int = Query(default=50, ge=1, le=200)) -> JSONResponse:
    return JSONResponse({"ok": True, "jobs": short_video.list_jobs(limit=limit)})


@app.post("/api/short-video/jobs")
def api_short_video_create_job(payload: dict[str, object] = Body(...)) -> JSONResponse:
    try:
        videos = payload.get("videos") if isinstance(payload.get("videos"), list) else []
        job = short_video.create_job(
            profile_url=str(payload.get("profile_url") or ""),
            sec_user_id=str(payload.get("sec_user_id") or ""),
            recent_count=int(payload.get("recent_count") or 5),
            videos=videos,  # type: ignore[arg-type]
        )
        return JSONResponse({"ok": True, "job": job})
    except (short_video.ShortVideoError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/short-video/assets")
def api_short_video_download_assets(payload: dict[str, object] = Body(...)) -> JSONResponse:
    """下载所选短视频作品的封面与 mp3。"""
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    videos = payload.get("videos") if isinstance(payload.get("videos"), list) else []
    limit = int(payload.get("limit") or len(videos) or 10)
    results = short_video.download_video_assets_batch(profile, videos, limit=limit)  # type: ignore[arg-type]
    ok_count = sum(1 for item in results if item.get("ok"))
    return JSONResponse({"ok": True, "results": results, "count": len(results), "ok_count": ok_count})


@app.post("/api/short-video/analyze")
def api_short_video_analyze(payload: dict[str, object] = Body(...)) -> JSONResponse:
    """后台自动获取封面/音频并进行短视频 AI 拆解。"""
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    videos = payload.get("videos") if isinstance(payload.get("videos"), list) else []
    limit = int(payload.get("limit") or len(videos) or 10)
    try:
        result = short_video_ai.analyze_selected_videos(profile, videos, limit=limit)  # type: ignore[arg-type]
        return JSONResponse(result)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"短视频 AI 拆解失败：{type(exc).__name__}: {exc}"}, status_code=500)


@app.post("/api/short-video/score")
def api_short_video_score(payload: dict[str, object] = Body(...)) -> JSONResponse:
    """对单条短视频或脚本进行作品潜力评分和相对爆款预测。"""
    work = payload.get("work") if isinstance(payload.get("work"), dict) else {}
    history = payload.get("account_history") if isinstance(payload.get("account_history"), list) else []
    template = str(payload.get("template") or "auto")
    try:
        score = short_video.score_short_video_work(work, account_history=history, template=template)  # type: ignore[arg-type]
        prediction = short_video.predict_short_video_performance(
            work,
            account_history=history,  # type: ignore[arg-type]
            template=template,
            score_result=score,
        )
        return JSONResponse({"ok": True, "score": score, "prediction": prediction})
    except short_video.ShortVideoError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/short-video/predict-script")
def api_short_video_predict_script(payload: dict[str, object] = Body(...)) -> JSONResponse:
    """对用户粘贴的新脚本进行发布前潜力预测。"""
    script = str(payload.get("script") or "").strip()
    if not script:
        return JSONResponse({"ok": False, "error": "请输入要预测的短视频脚本。"}, status_code=400)
    work = {
        "title": str(payload.get("title") or "待发布脚本"),
        "transcript": script,
        "cover_description": str(payload.get("cover_description") or ""),
    }
    history = payload.get("account_history") if isinstance(payload.get("account_history"), list) else []
    template = str(payload.get("template") or "auto")
    try:
        score = short_video.score_short_video_work(work, account_history=history, template=template)  # type: ignore[arg-type]
        prediction = short_video.predict_short_video_performance(
            work,
            account_history=history,  # type: ignore[arg-type]
            template=template,
            score_result=score,
        )
        return JSONResponse({"ok": True, "score": score, "prediction": prediction})
    except short_video.ShortVideoError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/short-video/learn-from-benchmark")
def api_short_video_learn_from_benchmark(payload: dict[str, object] = Body(...)) -> JSONResponse:
    """从当前账号或对标账号作品中总结可复用内容套路。"""
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    videos = payload.get("videos") if isinstance(payload.get("videos"), list) else []
    template = str(payload.get("template") or "auto")
    try:
        result = short_video.learn_from_benchmark_account(profile, videos, template=template)  # type: ignore[arg-type]
        return JSONResponse({"ok": True, "result": result})
    except short_video.ShortVideoError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/short-video/retro")
def api_short_video_retro(payload: dict[str, object] = Body(...)) -> JSONResponse:
    """发布后复盘预测准确性。"""
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    actual_metrics = payload.get("actual_metrics") if isinstance(payload.get("actual_metrics"), dict) else {}
    work = payload.get("work") if isinstance(payload.get("work"), dict) else {}
    try:
        result = short_video.retro_short_video_prediction(
            prediction=prediction,  # type: ignore[arg-type]
            actual_metrics=actual_metrics,  # type: ignore[arg-type]
            work=work,  # type: ignore[arg-type]
        )
        return JSONResponse({"ok": True, "result": result})
    except short_video.ShortVideoError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/short-video/positioning")
def api_short_video_positioning(payload: dict[str, object] = Body(...)) -> JSONResponse:
    """基于已解析作品做账号定位初判，并产出对标账号搜索方向。"""
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    videos = payload.get("videos") if isinstance(payload.get("videos"), list) else []
    return JSONResponse({
        "ok": True,
        "analysis": short_video.analyze_positioning(profile, videos),  # type: ignore[arg-type]
    })


@app.get("/api/short-video/benchmarks")
def api_short_video_benchmarks(limit: int = Query(default=200, ge=1, le=500)) -> JSONResponse:
    return JSONResponse({"ok": True, "benchmarks": short_video.list_benchmarks(limit=limit)})


@app.post("/api/short-video/benchmarks")
def api_short_video_create_benchmark(payload: dict[str, object] = Body(...)) -> JSONResponse:
    try:
        row = short_video.create_benchmark(
            source_profile=payload.get("source_profile") if isinstance(payload.get("source_profile"), dict) else {},
            positioning=payload.get("positioning") if isinstance(payload.get("positioning"), dict) else {},
            candidate=payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {},
            profile_url=str(payload.get("profile_url") or ""),
            account_name=str(payload.get("account_name") or ""),
            note=str(payload.get("note") or ""),
        )
        return JSONResponse({"ok": True, "benchmark": row})
    except short_video.ShortVideoError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/short-video/benchmark-recommendations")
def api_short_video_recommend_benchmark_accounts(payload: dict[str, object] = Body(...)) -> JSONResponse:
    """一键完成账号定位后的对标账号推荐，隐藏“搜索线索”中间步骤。"""
    try:
        row = short_video.recommend_benchmark_accounts(
            source_profile=payload.get("source_profile") if isinstance(payload.get("source_profile"), dict) else {},
            positioning=payload.get("positioning") if isinstance(payload.get("positioning"), dict) else {},
            limit=int(payload.get("limit") or 8),
        )
        return JSONResponse({"ok": True, "benchmark": row})
    except short_video.ShortVideoError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/short-video/benchmarks/{benchmark_id}/search")
def api_short_video_refresh_benchmark_search(benchmark_id: str) -> JSONResponse:
    try:
        row = short_video.refresh_benchmark_search(benchmark_id)
        return JSONResponse({"ok": True, "benchmark": row})
    except short_video.ShortVideoError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)


@app.post("/api/short-video/benchmarks/{benchmark_id}/accounts")
def api_short_video_search_benchmark_accounts(benchmark_id: str, payload: dict[str, object] = Body(default={})) -> JSONResponse:
    try:
        row = short_video.search_benchmark_accounts(
            benchmark_id,
            keyword=str(payload.get("keyword") or ""),
            limit=int(payload.get("limit") or 8),
        )
        return JSONResponse({"ok": True, "benchmark": row})
    except short_video.ShortVideoError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)


@app.get("/api/comment-leads/status")
def api_comment_leads_status() -> JSONResponse:
    return JSONResponse({"ok": True, **comment_leads.login_status()})


@app.post("/api/comment-leads/login")
def api_comment_leads_login(payload: dict[str, object] = Body(default={})) -> JSONResponse:
    start_url = str(payload.get("start_url") or "https://www.douyin.com/").strip()
    result = _run_blocking(comment_leads.open_login_browser, start_url=start_url, wait_ms=int(payload.get("wait_ms") or 30000))
    return JSONResponse(result, status_code=200 if result.get("ok") else 503)


@app.get("/api/comment-leads/monitors")
def api_comment_leads_monitors() -> JSONResponse:
    return JSONResponse({"ok": True, "monitors": comment_leads.list_monitors()})


@app.post("/api/comment-leads/monitors")
def api_comment_leads_add_monitor(payload: dict[str, object] = Body(...)) -> JSONResponse:
    try:
        monitor = comment_leads.add_monitor(
            str(payload.get("url") or ""),
            title=str(payload.get("title") or ""),
            owner=str(payload.get("owner") or ""),
            max_comments=int(payload.get("max_comments") or 100),
            max_videos=int(payload.get("max_videos") or 5),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "monitor": monitor})


@app.post("/api/comment-leads/profile-videos")
def api_comment_leads_profile_videos(payload: dict[str, object] = Body(...)) -> JSONResponse:
    try:
        result = _run_blocking(
            comment_leads.resolve_profile_works,
            str(payload.get("url") or ""),
            owner=str(payload.get("owner") or ""),
            max_comments=int(payload.get("max_comments") or 100),
            max_videos=int(payload.get("max_videos") or 5),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result, status_code=200 if result.get("ok") else 503)


@app.get("/api/comment-leads/leads")
def api_comment_leads_list(
    status: str = Query(default=""),
    keyword: str = Query(default=""),
    limit: int = Query(default=500),
) -> JSONResponse:
    return JSONResponse({"ok": True, "leads": comment_leads.list_leads(status=status, keyword=keyword, limit=limit)})


@app.post("/api/comment-leads/run")
def api_comment_leads_run(payload: dict[str, object] = Body(...)) -> JSONResponse:
    selected_videos = payload.get("videos")
    monitor_id = str(payload.get("monitor_id") or "").strip()
    if monitor_id and isinstance(selected_videos, list):
        try:
            result = _run_blocking(
                comment_leads.run_selected_videos,
                monitor_id,
                selected_videos,
                max_comments=int(payload.get("max_comments") or 0) or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result, status_code=200 if result.get("ok") else 503)
    if monitor_id:
        try:
            result = _run_blocking(comment_leads.run_monitor, monitor_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result, status_code=200 if result.get("ok") else 503)
    try:
        monitor = comment_leads.add_monitor(
            str(payload.get("url") or ""),
            title=str(payload.get("title") or ""),
            owner=str(payload.get("owner") or ""),
            max_comments=int(payload.get("max_comments") or 100),
            max_videos=int(payload.get("max_videos") or 5),
        )
        result = _run_blocking(comment_leads.run_monitor, monitor["id"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result, status_code=200 if result.get("ok") else 503)


@app.get("/api/comment-leads/export")
def api_comment_leads_export() -> FileResponse:
    out = comment_leads.export_leads_csv()
    return FileResponse(out, media_type="text/csv", filename=out.name)


@app.on_event("shutdown")
def _on_shutdown() -> None:
    _mgr.shutdown()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8848)
    args = ap.parse_args()
    print(f"控制台: http://{args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
