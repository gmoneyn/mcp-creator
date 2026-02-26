"""Scaffold a complete MCP server project."""

from __future__ import annotations

import json
from pathlib import Path

from mcp_creator.services import codegen, file_writer


def scaffold_server(
    package_name: str,
    description: str,
    tools: str,
    output_dir: str = ".",
    env_vars: str | None = None,
) -> str:
    """Scaffold a complete, runnable MCP server project.

    Args:
        package_name: PyPI package name (e.g. "my-weather-mcp").
        description: One-line description of the server.
        tools: JSON string — list of tool defs:
               [{"name": "get_weather", "description": "...",
                 "parameters": [{"name": "city", "type": "string",
                                  "required": true, "description": "..."}],
                 "returns": "Weather data as JSON"}]
        output_dir: Parent directory where the project folder is created.
        env_vars: Optional JSON string — list of env var defs:
                  [{"name": "API_KEY", "description": "...", "required": true}]

    Returns:
        JSON string with created files and next steps.
    """
    tool_defs = json.loads(tools)
    env_var_defs = json.loads(env_vars) if env_vars else None
    module_name = codegen._to_module_name(package_name)

    # Build file dict: relative_path -> content
    files: dict[str, str] = {}

    # Root files
    files["pyproject.toml"] = codegen.render_pyproject(package_name, description)
    files[".gitignore"] = codegen.render_gitignore()
    files["README.md"] = codegen.render_readme(package_name, description, tool_defs)

    env_content = codegen.render_env_example(env_var_defs)
    if env_content:
        files[".env.example"] = env_content

    # Source package
    src = f"src/{module_name}"
    files[f"{src}/__init__.py"] = codegen.render_init(package_name)
    files[f"{src}/server.py"] = codegen.render_server(package_name, tool_defs)
    files[f"{src}/transport.py"] = codegen.render_transport(package_name)

    # Tools and services
    files[f"{src}/tools/__init__.py"] = ""
    files[f"{src}/services/__init__.py"] = ""

    for tool in tool_defs:
        tool_name = tool["name"]
        files[f"{src}/tools/{tool_name}.py"] = codegen.render_tool_module(
            package_name, tool
        )
        files[f"{src}/services/{tool_name}_service.py"] = codegen.render_service_module(
            tool
        )

    # Tests
    files["tests/test_server.py"] = codegen.render_test_server(package_name, tool_defs)
    for tool in tool_defs:
        files[f"tests/test_{tool['name']}.py"] = codegen.render_test_tool(
            package_name, tool
        )

    # Write to disk
    project_dir = Path(output_dir).resolve() / package_name
    written = file_writer.write_project_files(project_dir, files)

    result = {
        "success": True,
        "project_dir": str(project_dir),
        "files_created": len(written),
        "file_list": sorted(files.keys()),
        "module_name": module_name,
        "next_steps": [
            f"Project scaffolded at {project_dir}",
            f"cd {project_dir} && uv venv .venv && source .venv/bin/activate && uv pip install -e '.[dev]'",
            "Open the services/ folder and replace the TODO stubs with your real logic.",
            "Run 'pytest -v' to verify everything works.",
            "When ready, use build_package to build and publish_package to publish to PyPI.",
        ],
    }

    return json.dumps(result, indent=2)
