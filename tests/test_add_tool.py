"""Test add_tool — adding a new tool to an existing scaffolded project."""

import json
import tempfile
from pathlib import Path

from mcp_creator.tools.scaffold_server import scaffold_server
from mcp_creator.tools.add_tool import add_tool


INITIAL_TOOLS = json.dumps([
    {
        "name": "get_weather",
        "description": "Get current weather",
        "parameters": [
            {"name": "city", "type": "string", "required": True, "description": "City"},
        ],
        "returns": "Weather JSON",
    }
])

NEW_TOOL = json.dumps({
    "name": "get_forecast",
    "description": "Get weather forecast",
    "parameters": [
        {"name": "city", "type": "string", "required": True, "description": "City"},
        {"name": "days", "type": "integer", "required": False, "description": "Days", "default": 5},
    ],
    "returns": "Forecast JSON",
})


def test_add_tool_creates_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        # First scaffold
        scaffold_result = json.loads(scaffold_server(
            package_name="test-add-mcp",
            description="Test",
            tools=INITIAL_TOOLS,
            output_dir=tmpdir,
        ))
        project_dir = scaffold_result["project_dir"]

        # Then add a tool
        result = json.loads(add_tool(project_dir=project_dir, tool=NEW_TOOL))

        assert result["success"] is True
        assert result["tool_name"] == "get_forecast"

        project = Path(project_dir)
        assert (project / "src" / "test_add_mcp" / "tools" / "get_forecast.py").exists()
        assert (project / "src" / "test_add_mcp" / "services" / "get_forecast_service.py").exists()
        assert (project / "tests" / "test_get_forecast.py").exists()


def test_add_tool_updates_server():
    with tempfile.TemporaryDirectory() as tmpdir:
        scaffold_result = json.loads(scaffold_server(
            package_name="test-add-mcp",
            description="Test",
            tools=INITIAL_TOOLS,
            output_dir=tmpdir,
        ))
        project_dir = scaffold_result["project_dir"]

        result = json.loads(add_tool(project_dir=project_dir, tool=NEW_TOOL))
        assert result["server_updated"] is True

        server_content = (Path(project_dir) / "src" / "test_add_mcp" / "server.py").read_text()
        assert "get_forecast" in server_content


def test_add_tool_bad_dir():
    result = json.loads(add_tool(project_dir="/nonexistent/path", tool=NEW_TOOL))
    assert result["success"] is False
