"""Map local API operations to commercial license capabilities."""

from __future__ import annotations


def feature_for_request(method: str, path: str) -> str | None:
    """Return the commercial feature required by one local API request.

    This is intentionally a small, pure mapping so the entitlement boundary is
    testable without starting the recorder, browser, or FastAPI application.
    """
    target = path.rstrip("/") or "/"
    if target.startswith("/api/license/"):
        return None
    if target in {"/api/ai/config", "/api/ai/test"}:
        return None
    if target.startswith("/api/short-video/cookie/"):
        return "short_video_ai"
    if target == "/api/comment-leads/status":
        return None
    if target.startswith("/api/ai/"):
        return "ai_replay"
    if target.startswith("/api/performance/"):
        return "ai_replay"
    if target.startswith("/api/export"):
        return "export"
    if target.startswith("/api/short-video/"):
        return "short_video_ai"
    if target.startswith("/api/comment-leads/"):
        return "lead_radar"
    if target in {"/api/status", "/api/diagnostics", "/api/cookie/remint"}:
        return "live_monitor"
    if target.startswith("/api/data/"):
        return "live_monitor"
    if target.startswith(("/api/rooms", "/api/anchors", "/api/anchor/", "/api/pending")):
        return "live_monitor"
    if target.startswith(("/api/video-quality", "/api/proxy", "/api/export-dir")):
        return "live_monitor"
    if target in {"/api/start_all", "/api/stop_all"}:
        return "live_monitor"
    return None
