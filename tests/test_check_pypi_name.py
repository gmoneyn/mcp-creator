"""Test check_pypi_name tool."""

import json

from mcp_creator.tools.check_pypi_name import check_pypi_name


def test_taken_name():
    """'requests' is definitely taken on PyPI."""
    result = json.loads(check_pypi_name("requests"))
    assert result["available"] is False
    assert result["existing_version"] is not None
    assert "next_steps" in result


def test_available_name():
    """An absurd name should be available."""
    result = json.loads(check_pypi_name("zzz-totally-fake-mcp-9999xyzabc"))
    assert result["available"] is True
    assert "next_steps" in result
