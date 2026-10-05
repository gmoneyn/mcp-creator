"""Transport helpers for mcp-creator."""


def run_stdio(mcp_app):
    """Run the MCP server over stdio (default for Claude Code / Cursor)."""
    mcp_app.run(transport="stdio")
