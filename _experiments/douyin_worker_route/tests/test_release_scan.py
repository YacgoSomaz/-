import importlib.util
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "packaging" / "build" / "check_release.py"
_SPEC = importlib.util.spec_from_file_location("livewatch_check_release", _CHECKER)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
scan_release = _MODULE.scan_release


def test_release_scan_passes_clean_runtime_files(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "frontend.html").write_text("<html>ok</html>", encoding="utf-8")
    (app / "pipeline_runtime.py").write_text("print('ok')", encoding="utf-8")

    assert scan_release(app) == []


def test_release_scan_blocks_runtime_data_and_logs(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "browser_cookies.json").write_text("{}", encoding="utf-8")
    (app / "license.json").write_text("{}", encoding="utf-8")
    (app / "license_clock.json").write_text("{}", encoding="utf-8")
    (app / "transcripts.db").write_bytes(b"sqlite")
    (app / "logs").mkdir()
    (app / "logs" / "webui.log").write_text("log", encoding="utf-8")
    (app / "license_data").mkdir()
    (app / "license_data" / "licenses.db").write_bytes(b"sqlite")

    findings = scan_release(app)

    assert any("browser_cookies.json" in item for item in findings)
    assert any("license.json" in item for item in findings)
    assert any("license_clock.json" in item for item in findings)
    assert any("transcripts.db" in item for item in findings)
    assert any("logs" in item for item in findings)
    assert any("license_data" in item for item in findings)


def test_release_scan_blocks_secret_like_content(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "settings.py").write_text("API_KEY = 'sk-abcdefghijklmnopqrstuvwxyz123456'\n", encoding="utf-8")

    findings = scan_release(app)

    assert any("secret-like content" in item for item in findings)


def test_release_scan_allows_cookie_field_names_but_blocks_cookie_values(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "parser.py").write_text("fields = ['passport_csrf_token', 'passport_auth_status']", encoding="utf-8")
    assert scan_release(tmp_path) == []

    (app / "leaked.txt").write_text("passport_csrf_token=abcdef1234567890", encoding="utf-8")
    findings = scan_release(tmp_path)

    assert any("passport_" in item for item in findings)


def test_release_scan_blocks_private_key_material_even_in_source_file(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "signing.py").write_text(
        "PRIVATE = '''-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----'''",
        encoding="utf-8",
    )

    findings = scan_release(app)

    assert any("private-key material" in item for item in findings)


def test_commercial_release_scan_blocks_business_python_source(tmp_path):
    app = tmp_path / "app" / "pipeline"
    app.mkdir(parents=True)
    (app / "webui.py").write_text("def hidden_business_logic(): pass", encoding="utf-8")
    (app / "license_runtime.py").write_text("LICENSE_ENFORCE = True", encoding="utf-8")

    findings = scan_release(tmp_path, commercial=True)

    assert any("source/vendor directories" in item for item in findings)
    assert any("license_runtime.py" in item for item in findings)


def test_commercial_release_scan_blocks_vendor_or_third_party_source_dirs(tmp_path):
    vendor = tmp_path / "app" / "vendor" / "SomeFetcher"
    third_party = tmp_path / "app" / "third_party" / "SomeSkill"
    vendor.mkdir(parents=True)
    third_party.mkdir(parents=True)
    (vendor / "README.md").write_text("implementation notes", encoding="utf-8")
    (third_party / "SKILL.md").write_text("prompt workflow", encoding="utf-8")

    findings = scan_release(tmp_path, commercial=True)

    assert any("app/vendor" in item.replace("\\", "/") for item in findings)
    assert any("app/third_party" in item.replace("\\", "/") for item in findings)


def test_release_scan_allows_known_bundled_runtime_false_positives(tmp_path):
    cert = tmp_path / "_internal" / "certifi"
    webview = tmp_path / "_internal" / "webview" / "js"
    static = tmp_path / "app" / "pipeline_data" / "static"
    source_static = tmp_path / "app" / "pipeline" / "static"
    cert.mkdir(parents=True)
    webview.mkdir(parents=True)
    static.mkdir(parents=True)
    source_static.mkdir(parents=True)
    (cert / "cacert.pem").write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")
    (webview / "api.js").write_text("const token = 'frontend-example-token';", encoding="utf-8")
    (static / "element-plus.css").write_text(".icon{content:'sk-example-frontend-font-name';}", encoding="utf-8")
    (source_static / "element-plus.css").write_text(".icon{content:'sk-example-frontend-font-name';}", encoding="utf-8")

    assert scan_release(tmp_path) == []
    commercial_findings = scan_release(tmp_path, commercial=True)
    assert any("source/vendor directories" in item for item in commercial_findings)
