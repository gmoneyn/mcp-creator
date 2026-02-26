"""Test that all tools are registered on the MCP Creator server."""

from mcp_creator.server import mcp


def test_all_tools_registered():
    tool_names = set(mcp._tool_manager._tools.keys())
    expected = {
        "get_creator_profile",
        "update_creator_profile",
        "check_setup",
        "check_pypi_name",
        "scaffold_server",
        "add_tool",
        "build_package",
        "publish_package",
        "setup_github",
        "generate_launchguide",
    }
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"


def test_tool_count():
    assert len(mcp._tool_manager._tools) == 10
