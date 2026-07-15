from __future__ import annotations

from pipeline import account_policy


def test_account_routes_are_not_paywalled_but_commercial_actions_are() -> None:
    assert account_policy.feature_for_request("POST", "/api/account/login") is None
    assert account_policy.feature_for_request("POST", "/api/account/send-code") is None
    assert account_policy.feature_for_request("GET", "/api/account/status") is None
    assert account_policy.feature_for_request("POST", "/api/rooms/123") == "live_monitor"
    assert account_policy.feature_for_request("POST", "/api/comment-leads/run") == "lead_radar"
    assert account_policy.feature_for_request("GET", "/api/live-workbench") == "live_monitor"
    assert account_policy.feature_for_request("GET", "/api/live-preview/123") == "live_monitor"
