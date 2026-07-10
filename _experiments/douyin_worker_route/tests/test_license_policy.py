from pipeline.license_policy import feature_for_request


def test_policy_maps_paid_workflows_but_keeps_activation_and_settings_available() -> None:
    assert feature_for_request("POST", "/api/license/activate") is None
    assert feature_for_request("GET", "/api/license/status") is None
    assert feature_for_request("PUT", "/api/ai/config") is None
    assert feature_for_request("POST", "/api/rooms/123/start") == "live_monitor"
    assert feature_for_request("POST", "/api/export") == "export"
    assert feature_for_request("POST", "/api/ai/report/stream") == "ai_replay"
    assert feature_for_request("POST", "/api/short-video/analyze") == "short_video_ai"
    assert feature_for_request("POST", "/api/comment-leads/run") == "lead_radar"

