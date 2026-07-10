from pipeline import web_security


def test_local_ui_origin_policy_accepts_only_loopback_browser_origins():
    assert web_security.is_local_ui_origin("http://127.0.0.1:8848")
    assert web_security.is_local_ui_origin("http://localhost:8851")
    assert web_security.is_local_ui_origin("https://localhost:9443")
    assert not web_security.is_local_ui_origin("https://example.com")
    assert not web_security.is_local_ui_origin("http://127.0.0.2:8848")
    assert not web_security.is_local_ui_origin("file://")
