"""Transport helpers for mcp-creator."""


def run_stdio(mcp_app):
    """Run the MCP server over stdio (default for Claude Code / Cursor)."""
    mcp_app.run(transport="stdio")


def run_http(mcp_app, host: str = "0.0.0.0", port: int = 8000):
    """Run the MCP server over HTTP (for remote hosting)."""
    mcp_app.run(transport="sse", host=host, port=port)
