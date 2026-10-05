"""Scaffold a complete MCP server project."""

from __future__ import annotations

import json

from mcp_creator.services import codegen, file_writer
from mcp_creator.services.names import check_env_vars, check_package_name, check_tool_defs
from mcp_creator.services.project_guard import check_new_project_dir


def scaffold_server(
    package_name: str,
    description: str,
    tools: str,
    output_dir: str = ".",
    env_vars: str | None = None,
    paid: bool = False,
    paid_tools: str | None = None,
    hosting: str = "local",
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
        paid: If true, add license key gating via mcp-marketplace-license SDK.
        paid_tools: Optional JSON string — list of tool names to gate behind license.
                    If omitted and paid=true, all tools are gated.
        hosting: "local" (default, stdio) or "remote" (SSE/HTTP for hosted model).

    Returns:
        JSON string with created files and next steps.
    """
    tool_defs = json.loads(tools)
    env_var_defs = json.loads(env_vars) if env_vars else None
    paid_tool_list = json.loads(paid_tools) if paid_tools else None

    # Names become identifiers and file names in the generated source: check them
    # before a single line is generated.
    for reason in (
        check_package_name(package_name),
        check_tool_defs(tool_defs),
        check_env_vars(env_var_defs),
    ):
        if reason:
            return json.dumps({"success": False, "error": reason})
    module_name = codegen._to_module_name(package_name)

    # Build file dict: relative_path -> content
    files: dict[str, str] = {}

    # Root files
    files["pyproject.toml"] = codegen.render_pyproject(package_name, description, paid=paid)
    files[".gitignore"] = codegen.render_gitignore()
    files["README.md"] = codegen.render_readme(
        package_name, description, tool_defs, paid=paid, hosting=hosting,
    )

    env_content = codegen.render_env_example(env_var_defs, paid=paid, hosting=hosting)
    if env_content:
        files[".env.example"] = env_content

    if hosting == "remote":
        files["Dockerfile"] = codegen.render_dockerfile(package_name)

    # Source package
    src = f"src/{module_name}"
    files[f"{src}/__init__.py"] = codegen.render_init(package_name)
    files[f"{src}/server.py"] = codegen.render_server(
        package_name, tool_defs, paid=paid, paid_tools=paid_tool_list, hosting=hosting,
    )
    files[f"{src}/transport.py"] = codegen.render_transport(package_name)

    # Tools and services
    files[f"{src}/tools/__init__.py"] = ""
    files[f"{src}/services/__init__.py"] = ""

    # Tests
    files["tests/test_server.py"] = codegen.render_test_server(package_name, tool_defs)

    # Per-tool files. Each tool's files are named after it, so a tool name can land on a
    # file another part of the project already owns (a tool called `server` and
    # tests/test_server.py). Compare ignoring case: some filesystems do.
    claimed = {path.casefold(): "the project itself" for path in files}
    for tool in tool_defs:
        tool_name = tool["name"]
        for path, content in (
            (f"{src}/tools/{tool_name}.py", codegen.render_tool_module(package_name, tool)),
            (f"{src}/services/{tool_name}_service.py", codegen.render_service_module(tool)),
            (f"tests/test_{tool_name}.py", codegen.render_test_tool(package_name, tool)),
        ):
            owner = claimed.get(path.casefold())
            if owner:
                return json.dumps({
                    "success": False,
                    "error": (
                        f"Invalid tool name {tool_name!r}: it needs the file {path}, which is "
                        f"already generated for {owner} (generated file name rule). "
                        "Pick another tool name."
                    ),
                })
            claimed[path.casefold()] = f"tool {tool_name!r}"
            files[path] = content

    # Write to disk. The project lands in output_dir/package_name and nowhere else:
    # the target is checked first, then every file path is confined to it.
    project_dir, reason = check_new_project_dir(output_dir, package_name)
    if project_dir is None:
        return json.dumps({"success": False, "error": reason})
    try:
        written = file_writer.write_project_files(project_dir, files)
    except file_writer.UnsafePathError as exc:
        return json.dumps({"success": False, "error": str(exc)})

    result = {
        "success": True,
        "project_dir": str(project_dir),
        "files_created": len(written),
        "file_list": sorted(files.keys()),
        "module_name": module_name,
        "paid": paid,
        "hosting": hosting,
        "next_steps": [
            f"Project scaffolded at {project_dir}",
            f"cd {project_dir} && uv venv .venv && source .venv/bin/activate && uv pip install -e '.[dev]'",
            "Open the services/ folder and replace the TODO stubs with your real logic.",
            "Run 'pytest -v' to verify everything works.",
            "When ready, use build_package to build and publish_package to publish to PyPI.",
        ],
    }

    if paid and hosting == "remote":
        result["next_steps"].append(
            "License gating is enabled. On a hosted server the key is read from the server's own "
            "MCP_LICENSE_KEY, not from each caller, so it does not yet tell one caller from another "
            "(see Known limitation in the generated README)."
        )
    elif paid:
        result["next_steps"].append(
            "License gating is enabled. Users need MCP_LICENSE_KEY to use paid tools."
        )
    if hosting == "remote":
        result["next_steps"].append(
            "Remote hosting enabled. The server refuses to start unless MCP_ALLOWED_HOSTS is set: "
            "follow the Deployment section of the generated README "
            "(docker run -e MCP_ALLOWED_HOSTS=<your-host> -p 8000:8000 " + package_name + ")."
        )

    return json.dumps(result, indent=2)
