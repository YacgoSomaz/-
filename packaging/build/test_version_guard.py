import pathlib
import subprocess


SCRIPT = pathlib.Path(__file__).with_name("version_guard.ps1")


def run_guard(version: str, published: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-Version",
            version,
            "-PublishedVersion",
            published,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def run_next_version(published: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-NextVersion",
            "-PublishedVersion",
            published,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_guard_rejects_a_version_with_a_lower_minor_even_if_its_patch_is_larger() -> None:
    result = run_guard("1.0.17", "1.1.14")
    assert result.returncode != 0
    assert "1.0.17" in result.stderr
    assert "1.1.14" in result.stderr


def test_guard_accepts_only_a_strictly_newer_release() -> None:
    equal = run_guard("1.1.14", "1.1.14")
    newer = run_guard("1.1.15", "1.1.14")
    assert equal.returncode != 0
    assert newer.returncode == 0, newer.stderr


def test_guard_can_derive_the_next_patch_version_from_the_published_release() -> None:
    result = run_next_version("1.1.14")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1.1.15"
