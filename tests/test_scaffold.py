"""Test scaffold_server tool."""

import json
import tempfile
from pathlib import Path

from mcp_creator.tools.scaffold_server import scaffold_server


SAMPLE_TOOLS = json.dumps([
    {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "parameters": [
            {"name": "city", "type": "string", "required": True, "description": "City name"},
        ],
        "returns": "Weather data as JSON",
    }
])


def test_scaffold_creates_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = json.loads(scaffold_server(
            package_name="test-weather-mcp",
            description="A test weather MCP",
            tools=SAMPLE_TOOLS,
            output_dir=tmpdir,
        ))

        assert result["success"] is True
        project_dir = Path(result["project_dir"])
        assert project_dir.exists()
        assert (project_dir / "pyproject.toml").exists()
        assert (project_dir / "src" / "test_weather_mcp" / "server.py").exists()
        assert (project_dir / "src" / "test_weather_mcp" / "tools" / "get_weather.py").exists()
        assert (project_dir / "src" / "test_weather_mcp" / "services" / "get_weather_service.py").exists()
        assert (project_dir / "tests" / "test_server.py").exists()
        assert (project_dir / "tests" / "test_get_weather.py").exists()


def test_scaffold_with_env_vars():
    env_vars = json.dumps([
        {"name": "WEATHER_API_KEY", "description": "API key for weather service", "required": True},
    ])
    with tempfile.TemporaryDirectory() as tmpdir:
        result = json.loads(scaffold_server(
            package_name="test-weather-mcp",
            description="A test weather MCP",
            tools=SAMPLE_TOOLS,
            output_dir=tmpdir,
            env_vars=env_vars,
        ))

        assert result["success"] is True
        project_dir = Path(result["project_dir"])
        assert (project_dir / ".env.example").exists()


def test_scaffold_server_py_has_sentinels():
    """Verify server.py has sentinel comments for add_tool injection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = json.loads(scaffold_server(
            package_name="test-weather-mcp",
            description="A test",
            tools=SAMPLE_TOOLS,
            output_dir=tmpdir,
        ))

        server_py = Path(result["project_dir"]) / "src" / "test_weather_mcp" / "server.py"
        content = server_py.read_text()
        assert "# --- IMPORTS ---" in content
        assert "# --- END IMPORTS ---" in content
        assert "# --- TOOLS ---" in content
        assert "# --- END TOOLS ---" in content


def test_scaffold_multiple_tools():
    tools = json.dumps([
        {
            "name": "get_weather",
            "description": "Get weather",
            "parameters": [
                {"name": "city", "type": "string", "required": True, "description": "City"},
            ],
            "returns": "Weather JSON",
        },
        {
            "name": "get_forecast",
            "description": "Get forecast",
            "parameters": [
                {"name": "city", "type": "string", "required": True, "description": "City"},
                {"name": "days", "type": "integer", "required": False, "description": "Days", "default": 5},
            ],
            "returns": "Forecast JSON",
        },
    ])

    with tempfile.TemporaryDirectory() as tmpdir:
        result = json.loads(scaffold_server(
            package_name="test-multi-mcp",
            description="Multi tool test",
            tools=tools,
            output_dir=tmpdir,
        ))

        assert result["success"] is True
        project_dir = Path(result["project_dir"])
        assert (project_dir / "src" / "test_multi_mcp" / "tools" / "get_weather.py").exists()
        assert (project_dir / "src" / "test_multi_mcp" / "tools" / "get_forecast.py").exists()
