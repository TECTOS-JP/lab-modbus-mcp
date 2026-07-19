from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_ci_uses_node24_actions_pypi_dependency_and_bef_suite():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    yaml.safe_load(text)
    assert "actions/checkout@v5" in text
    assert "actions/setup-python@v6" in text
    assert 'python-version: "3.11"' in text
    assert "git+" not in text
    assert "pytest" in text
    assert "ruff check" in text
    assert "ruff format --check" in text
    assert "BEF conformance kit" in text


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
