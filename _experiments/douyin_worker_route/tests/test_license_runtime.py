from pipeline import license_runtime


def test_source_tree_defaults_to_non_enforcing_license_runtime() -> None:
    assert license_runtime.LICENSE_ENFORCE is False
    assert license_runtime.LICENSE_SERVER_URL == ""
    assert license_runtime.LICENSE_PUBLIC_KEY == ""

