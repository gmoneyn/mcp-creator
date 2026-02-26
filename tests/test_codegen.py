"""Test codegen service — pure function output validation."""

from mcp_creator.services.codegen import (
    render_pyproject,
    render_server,
    render_tool_module,
    render_service_module,
    render_readme,
    render_env_example,
    render_test_server,
    render_test_tool,
    _to_module_name,
    _to_class_name,
)


SAMPLE_TOOL = {
    "name": "get_weather",
    "description": "Get current weather for a city",
    "parameters": [
        {"name": "city", "type": "string", "required": True, "description": "City name"},
    ],
    "returns": "Weather data as JSON",
}

SAMPLE_TOOL_OPTIONAL = {
    "name": "get_forecast",
    "description": "Get weather forecast",
    "parameters": [
        {"name": "city", "type": "string", "required": True, "description": "City name"},
        {"name": "days", "type": "integer", "required": False, "description": "Forecast days", "default": 5},
    ],
    "returns": "Forecast data as JSON",
}


def test_to_module_name():
    assert _to_module_name("my-weather-mcp") == "my_weather_mcp"
    assert _to_module_name("simple") == "simple"


def test_to_class_name():
    assert _to_class_name("get_weather") == "GetWeather"
    assert _to_class_name("fetch_data") == "FetchData"


def test_render_pyproject():
    result = render_pyproject("my-weather-mcp", "A weather server")
    assert 'name = "my-weather-mcp"' in result
    assert "my_weather_mcp.server:main" in result
    assert "hatchling" in result


def test_render_server_has_sentinels():
    result = render_server("my-weather-mcp", [SAMPLE_TOOL])
    assert "# --- IMPORTS ---" in result
    assert "# --- END IMPORTS ---" in result
    assert "# --- TOOLS ---" in result
    assert "# --- END TOOLS ---" in result
    assert "FastMCP" in result
    assert "get_weather" in result


def test_render_server_optional_params():
    result = render_server("my-weather-mcp", [SAMPLE_TOOL_OPTIONAL])
    assert "days: int = 5" in result


def test_render_tool_module():
    result = render_tool_module("my-weather-mcp", SAMPLE_TOOL)
    assert "def get_weather(city: str)" in result
    assert "GetWeather" in result
    assert "json.dumps" in result


def test_render_service_module():
    result = render_service_module(SAMPLE_TOOL)
    assert "class GetWeather:" in result
    assert "def execute(self" in result
    assert "TODO" in result


def test_render_readme():
    result = render_readme("my-weather-mcp", "A weather server", [SAMPLE_TOOL])
    assert "# my-weather-mcp" in result
    assert "pip install my-weather-mcp" in result
    assert "get_weather" in result


def test_render_env_example_none():
    assert render_env_example(None) is None
    assert render_env_example([]) is None


def test_render_env_example():
    result = render_env_example([
        {"name": "API_KEY", "description": "Weather API key", "required": True},
    ])
    assert "API_KEY=" in result
    assert "required" in result


def test_render_test_server():
    result = render_test_server("my-weather-mcp", [SAMPLE_TOOL])
    assert "def test_tools_registered" in result
    assert '"get_weather"' in result


def test_render_test_tool():
    result = render_test_tool("my-weather-mcp", SAMPLE_TOOL)
    assert "def test_get_weather_returns_json" in result
    assert "json.loads" in result
