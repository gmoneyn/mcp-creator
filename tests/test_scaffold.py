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


def test_scaffold_paid_mode():
    """Scaffold with paid=true adds license SDK dep and gating code."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = json.loads(scaffold_server(
            package_name="test-paid-mcp",
            description="A paid MCP",
            tools=SAMPLE_TOOLS,
            output_dir=tmpdir,
            paid=True,
        ))

        assert result["success"] is True
        assert result["paid"] is True
        project_dir = Path(result["project_dir"])

        # pyproject.toml includes license SDK dep
        pyproject = (project_dir / "pyproject.toml").read_text()
        assert "mcp-marketplace-license" in pyproject

        # server.py has license verification
        server_py = (project_dir / "src" / "test_paid_mcp" / "server.py").read_text()
        assert "verify_license" in server_py
        assert "_require_license" in server_py

        # .env.example has MCP_LICENSE_KEY
        env = (project_dir / ".env.example").read_text()
        assert "MCP_LICENSE_KEY" in env

        # README mentions license key
        readme = (project_dir / "README.md").read_text()
        assert "License Key" in readme


def test_scaffold_paid_with_specific_tools():
    """Scaffold with paid_tools gates only specified tools."""
    tools = json.dumps([
        {
            "name": "free_tool",
            "description": "A free tool",
            "parameters": [{"name": "q", "type": "string", "required": True, "description": "Query"}],
        },
        {
            "name": "pro_tool",
            "description": "A paid tool",
            "parameters": [{"name": "q", "type": "string", "required": True, "description": "Query"}],
        },
    ])
    with tempfile.TemporaryDirectory() as tmpdir:
        result = json.loads(scaffold_server(
            package_name="test-partial-paid-mcp",
            description="Partially paid MCP",
            tools=tools,
            output_dir=tmpdir,
            paid=True,
            paid_tools=json.dumps(["pro_tool"]),
        ))

        assert result["success"] is True
        server_py = (Path(result["project_dir"]) / "src" / "test_partial_paid_mcp" / "server.py").read_text()

        # pro_tool should have license check
        assert '_require_license("pro_tool")' in server_py

        # free_tool should NOT have license check
        # Find the free_tool function body and verify no license check
        lines = server_py.split("\n")
        in_free_tool = False
        free_tool_has_license = False
        for line in lines:
            if "def free_tool(" in line:
                in_free_tool = True
            elif in_free_tool and "def " in line:
                break
            elif in_free_tool and "_require_license" in line:
                free_tool_has_license = True
        assert not free_tool_has_license


def test_scaffold_remote_hosting():
    """Scaffold with hosting='remote' generates HTTP server + Dockerfile."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = json.loads(scaffold_server(
            package_name="test-remote-mcp",
            description="A remote MCP",
            tools=SAMPLE_TOOLS,
            output_dir=tmpdir,
            hosting="remote",
        ))

        assert result["success"] is True
        assert result["hosting"] == "remote"
        project_dir = Path(result["project_dir"])

        # Dockerfile exists
        assert (project_dir / "Dockerfile").exists()
        dockerfile = (project_dir / "Dockerfile").read_text()
        assert "EXPOSE" in dockerfile

        # server.py uses SSE transport
        server_py = (project_dir / "src" / "test_remote_mcp" / "server.py").read_text()
        assert '"sse"' in server_py
        assert "PORT" in server_py

        # .env.example has PORT
        env = (project_dir / ".env.example").read_text()
        assert "PORT" in env

        # README has remote config
        readme = (project_dir / "README.md").read_text()
        assert "url" in readme


def test_scaffold_paid_remote():
    """Scaffold with both paid=true and hosting='remote'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = json.loads(scaffold_server(
            package_name="test-paid-remote-mcp",
            description="A paid remote MCP",
            tools=SAMPLE_TOOLS,
            output_dir=tmpdir,
            paid=True,
            hosting="remote",
        ))

        assert result["success"] is True
        project_dir = Path(result["project_dir"])

        # Has both license + remote features
        server_py = (project_dir / "src" / "test_paid_remote_mcp" / "server.py").read_text()
        assert "verify_license" in server_py
        assert '"sse"' in server_py
        assert (project_dir / "Dockerfile").exists()

        env = (project_dir / ".env.example").read_text()
        assert "MCP_LICENSE_KEY" in env
        assert "PORT" in env
