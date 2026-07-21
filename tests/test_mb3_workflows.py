from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_ci_uses_node24_actions_pypi_dependency_and_bef_suite():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    data = yaml.safe_load(text)
    assert "actions/checkout@v5" in text
    assert "actions/setup-python@v6" in text
    assert 'python-version: "3.11"' in text
    assert "pytest" in text
    assert "ruff check" in text
    assert "ruff format --check" in text
    assert "BEF conformance kit" in text
    # The job that validates against the released runtime must resolve
    # lab-executor from PyPI. A git pin there would mean the release path was
    # never actually exercised.
    assert "git+" not in yaml.safe_dump(data["jobs"]["test"])


def test_ci_has_an_allowed_to_fail_runtime_main_smoke_job():
    """The reverse direction: detect a breaking runtime change early.

    This is the one place a git pin belongs, and it must not gate this
    repository's CI — a red main is information about the runtime, not a defect
    here.
    """
    data = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    )
    smoke = data["jobs"]["main-compatibility-smoke"]
    assert smoke["continue-on-error"] is True
    assert "git+https://github.com/TECTOS-JP/lab-executor-mcp@main" in yaml.safe_dump(
        smoke
    )


def test_publish_uses_oidc_testpypi_and_sdist_guard():
    text = (ROOT / ".github" / "workflows" / "publish.yml").read_text("utf-8")
    yaml.safe_load(text)
    assert "actions/checkout@v5" in text
    assert "actions/setup-python@v6" in text
    assert "actions/upload-artifact@v6" in text
    assert "actions/download-artifact@v7" in text
    assert "id-token: write" in text
    assert "repository-url: https://test.pypi.org/legacy/" in text
    assert "twine check" in text
    for forbidden in (".uv-cache", ".venv", "site-packages"):
        assert forbidden in text
    assert "len(names) > 2000" in text
