"""Code generation for scaffolded MCP server projects.

All functions are pure — they return strings, no I/O.
"""

from __future__ import annotations

PYPROJECT_TEMPLATE = """\
[project]
name = "{package_name}"
version = "0.1.0"
description = "{description}"
readme = "README.md"
requires-python = ">=3.11"
license = {{ text = "MIT" }}
dependencies = [
    "mcp[cli]>=1.0.0",
]

[project.scripts]
{package_name} = "{module_name}.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{module_name}"]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]
"""

GITIGNORE_TEMPLATE = """\
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.eggs/
*.egg
.venv/
venv/
.env
*.so
.pytest_cache/
.mypy_cache/
.ruff_cache/
"""

INIT_TEMPLATE = '""""{package_name} MCP server."""\n'

TRANSPORT_TEMPLATE = """\
\"\"\"Transport helpers for {package_name}.\"\"\"

import sys


def run_stdio(mcp_app):
    \"\"\"Run the MCP server over stdio (default for Claude Code / Cursor).\"\"\"
    mcp_app.run(transport="stdio")


def run_http(mcp_app, host: str = "0.0.0.0", port: int = 8000):
    \"\"\"Run the MCP server over HTTP (for remote hosting).\"\"\"
    mcp_app.run(transport="sse", host=host, port=port)
"""


def _to_module_name(package_name: str) -> str:
    """Convert a PyPI package name to a Python module name."""
    return package_name.replace("-", "_")


def _python_type(type_str: str) -> str:
    """Map a simple type string to a Python type annotation."""
    mapping = {
        "string": "str",
        "str": "str",
        "integer": "int",
        "int": "int",
        "number": "float",
        "float": "float",
        "boolean": "bool",
        "bool": "bool",
        "list": "list",
        "array": "list",
        "dict": "dict",
        "object": "dict",
    }
    return mapping.get(type_str.lower(), "str")


def render_pyproject(package_name: str, description: str, *, paid: bool = False) -> str:
    module_name = _to_module_name(package_name)
    base = PYPROJECT_TEMPLATE.format(
        package_name=package_name,
        description=description,
        module_name=module_name,
    )
    if paid:
        base = base.replace(
            '    "mcp[cli]>=1.0.0",\n]',
            '    "mcp[cli]>=1.0.0",\n    "mcp-marketplace-license>=1.0.0",\n]',
        )
    return base


def render_gitignore() -> str:
    return GITIGNORE_TEMPLATE


def render_init(package_name: str) -> str:
    return INIT_TEMPLATE.format(package_name=package_name)


def render_transport(package_name: str) -> str:
    return TRANSPORT_TEMPLATE.format(package_name=package_name)


def render_env_example(
    env_vars: list[dict] | None,
    *,
    paid: bool = False,
    hosting: str = "local",
) -> str | None:
    """Render .env.example if env vars are declared or paid/remote. Returns None if nothing needed."""
    has_vars = bool(env_vars) or paid or hosting == "remote"
    if not has_vars:
        return None
    lines = ["# Environment variables for this MCP server", ""]
    if paid:
        lines.append("# License key for paid features (required)")
        lines.append("# Get one at mcp-marketplace.io")
        lines.append("MCP_LICENSE_KEY=")
        lines.append("")
    if hosting == "remote":
        lines.append("# Server port (optional, default 8000)")
        lines.append("PORT=8000")
        lines.append("")
    if env_vars:
        for var in env_vars:
            name = var.get("name", "UNKNOWN")
            desc = var.get("description", "")
            required = var.get("required", True)
            tag = "required" if required else "optional"
            lines.append(f"# {desc} ({tag})")
            lines.append(f"{name}=")
            lines.append("")
    return "\n".join(lines)


def render_server(
    package_name: str,
    tools: list[dict],
    *,
    paid: bool = False,
    paid_tools: list[str] | None = None,
    hosting: str = "local",
) -> str:
    """Render the main server.py with FastMCP and tool registrations."""
    module_name = _to_module_name(package_name)
    gated = set(paid_tools or [])

    lines = [
        f'"""MCP server for {package_name}."""',
        "",
    ]

    if paid:
        lines.append("import json")
        lines.append("")

    if hosting == "remote":
        lines.append("import os")
        lines.append("")

    lines.append("from mcp.server.fastmcp import FastMCP")

    if paid:
        lines.append("from mcp_marketplace_license import verify_license")

    lines.append("")
    lines.append("# --- IMPORTS ---")

    for tool in tools:
        tool_name = tool["name"]
        lines.append(
            f"from {module_name}.tools.{tool_name} import {tool_name} as _{tool_name}_impl"
        )

    lines.append("# --- END IMPORTS ---")
    lines.append("")
    lines.append(f'mcp = FastMCP("{package_name}")')

    if paid:
        lines.append("")
        lines.append("")
        lines.append("def _require_license(tool_name: str) -> str | None:")
        lines.append('    """Return None if licensed, or a JSON error string."""')
        lines.append(f'    result = verify_license(slug="{package_name}")')
        lines.append('    if result.get("valid"):')
        lines.append("        return None")
        lines.append("    return json.dumps({")
        lines.append('        "error": "premium_required",')
        lines.append('        "reason": result.get("reason", "unknown"),')
        lines.append("        \"message\": f\"The '{tool_name}' tool requires a license. \"")
        lines.append(f'            "Set MCP_LICENSE_KEY to unlock it. "')
        lines.append(f'            "Get your key at https://mcp-marketplace.io/server/{package_name}",')
        lines.append("    })")

    lines.append("")
    lines.append("# --- TOOLS ---")

    for tool in tools:
        tool_name = tool["name"]
        tool_desc = tool.get("description", f"{tool_name} tool")
        params = tool.get("parameters", [])
        is_gated = paid and (not gated or tool_name in gated)

        # Build parameter list
        param_parts = []
        for p in params:
            pname = p["name"]
            ptype = _python_type(p.get("type", "string"))
            if p.get("required", True):
                param_parts.append(f"{pname}: {ptype}")
            else:
                default = p.get("default")
                if default is None:
                    default_str = "None"
                    ptype = f"{ptype} | None"
                elif isinstance(default, str):
                    default_str = f'"{default}"'
                else:
                    default_str = str(default)
                param_parts.append(f"{pname}: {ptype} = {default_str}")

        param_str = ", ".join(param_parts)
        call_args = ", ".join(p["name"] for p in params)

        lines.append("")
        lines.append(f'@mcp.tool(description="{tool_desc}")')
        lines.append(f"def {tool_name}({param_str}) -> str:")
        lines.append(f'    """Call the {tool_name} tool."""')
        if is_gated:
            lines.append(f'    err = _require_license("{tool_name}")')
            lines.append("    if err:")
            lines.append("        return err")
        lines.append(f"    return _{tool_name}_impl({call_args})")

    lines.append("# --- END TOOLS ---")
    lines.append("")
    lines.append("")
    lines.append("def main():")
    lines.append('    """Run the MCP server."""')
    if hosting == "remote":
        lines.append('    port = int(os.environ.get("PORT", "8000"))')
        lines.append('    mcp.run(transport="sse", host="0.0.0.0", port=port)')
    else:
        lines.append("    mcp.run()")
    lines.append("")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    main()")
    lines.append("")

    return "\n".join(lines)


def render_tool_module(package_name: str, tool: dict) -> str:
    """Render a single tool module file (tools/<name>.py)."""
    module_name = _to_module_name(package_name)
    tool_name = tool["name"]
    tool_desc = tool.get("description", f"{tool_name} tool")
    params = tool.get("parameters", [])
    returns = tool.get("returns", "Result as JSON string")

    # Build function signature
    param_parts = []
    for p in params:
        pname = p["name"]
        ptype = _python_type(p.get("type", "string"))
        if p.get("required", True):
            param_parts.append(f"{pname}: {ptype}")
        else:
            default = p.get("default")
            if default is None:
                default_str = "None"
                ptype = f"{ptype} | None"
            elif isinstance(default, str):
                default_str = f'"{default}"'
            else:
                default_str = str(default)
            param_parts.append(f"{pname}: {ptype} = {default_str}")

    param_str = ", ".join(param_parts)

    lines = [
        f'"""{tool_desc}."""',
        "",
        "import json",
        "",
        f"from {module_name}.services.{tool_name}_service import {_to_class_name(tool_name)}",
        "",
        "",
        f"def {tool_name}({param_str}) -> str:",
        f'    """{tool_desc}',
        "",
        f"    Returns:",
        f"        {returns}",
        '    """',
        f"    service = {_to_class_name(tool_name)}()",
        f"    result = service.execute({', '.join(p['name'] + '=' + p['name'] for p in params)})",
        "    return json.dumps(result, indent=2)",
        "",
    ]

    return "\n".join(lines)


def render_service_module(tool: dict) -> str:
    """Render a service stub (services/<name>_service.py)."""
    tool_name = tool["name"]
    tool_desc = tool.get("description", f"{tool_name} service")
    params = tool.get("parameters", [])
    class_name = _to_class_name(tool_name)

    param_parts = []
    for p in params:
        pname = p["name"]
        ptype = _python_type(p.get("type", "string"))
        if p.get("required", True):
            param_parts.append(f"{pname}: {ptype}")
        else:
            default = p.get("default")
            if default is None:
                default_str = "None"
                ptype = f"{ptype} | None"
            elif isinstance(default, str):
                default_str = f'"{default}"'
            else:
                default_str = str(default)
            param_parts.append(f"{pname}: {ptype} = {default_str}")

    param_str = ", ".join(param_parts)

    # Build placeholder return dict
    placeholder_fields = {}
    for p in params:
        placeholder_fields[p["name"]] = p["name"]
    placeholder_fields["status"] = '"ok"'

    result_lines = [f'            "{k}": {v},' for k, v in placeholder_fields.items()]
    result_block = "\n".join(result_lines)

    lines = [
        f'"""{tool_desc} — service layer."""',
        "",
        "",
        f"class {class_name}:",
        f'    """{tool_desc}.',
        "",
        "    TODO: Replace the stub implementation with your real logic.",
        '    """',
        "",
        f"    def execute(self, {param_str}) -> dict:",
        f'        """Run {tool_name} and return results."""',
        "        # TODO: Implement your logic here",
        "        return {",
        result_block,
        "        }",
        "",
    ]

    return "\n".join(lines)


def render_test_server(package_name: str, tools: list[dict]) -> str:
    """Render test_server.py that verifies tool registration."""
    module_name = _to_module_name(package_name)
    tool_names = [t["name"] for t in tools]
    expected_set = "{" + ", ".join(f'"{n}"' for n in tool_names) + "}"

    lines = [
        f'"""Test that all tools are registered on the MCP server."""',
        "",
        f"from {module_name}.server import mcp",
        "",
        "",
        "def test_tools_registered():",
        f"    tool_names = set(mcp._tool_manager._tools.keys())",
        f"    expected = {expected_set}",
        "    assert expected.issubset(tool_names), f\"Missing tools: {expected - tool_names}\"",
        "",
    ]

    return "\n".join(lines)


def render_test_tool(package_name: str, tool: dict) -> str:
    """Render a basic test for a single tool."""
    module_name = _to_module_name(package_name)
    tool_name = tool["name"]
    params = tool.get("parameters", [])

    # Build test call args
    test_args = []
    for p in params:
        ptype = p.get("type", "string").lower()
        if ptype in ("string", "str"):
            test_args.append(f'{p["name"]}="test"')
        elif ptype in ("integer", "int"):
            test_args.append(f'{p["name"]}=1')
        elif ptype in ("number", "float"):
            test_args.append(f'{p["name"]}=1.0')
        elif ptype in ("boolean", "bool"):
            test_args.append(f'{p["name"]}=True')
        else:
            test_args.append(f'{p["name"]}="test"')

    args_str = ", ".join(test_args)

    lines = [
        f'"""Test {tool_name} tool."""',
        "",
        "import json",
        "",
        f"from {module_name}.tools.{tool_name} import {tool_name}",
        "",
        "",
        f"def test_{tool_name}_returns_json():",
        f"    result = {tool_name}({args_str})",
        "    data = json.loads(result)",
        "    assert isinstance(data, dict)",
        "",
    ]

    return "\n".join(lines)


def render_readme(
    package_name: str,
    description: str,
    tools: list[dict],
    *,
    paid: bool = False,
    hosting: str = "local",
) -> str:
    """Render README.md for the generated project."""
    module_name = _to_module_name(package_name)

    tool_list = "\n".join(
        f"- **{t['name']}** — {t.get('description', t['name'])}" for t in tools
    )

    sections = [f"# {package_name}", "", description, ""]

    if hosting == "local":
        sections += [
            "## Install", "",
            "```bash", f"pip install {package_name}", "```", "",
        ]
    else:
        sections += [
            "## Connect", "",
            "This is a remote MCP server. Add to your Claude Code config:", "",
            "```json", "{", f'  "mcpServers": {{', f'    "{package_name}": {{',
            f'      "url": "https://your-server.com/mcp"',
            "    }", "  }", "}", "```", "",
        ]

    sections += ["## Tools", "", tool_list, ""]

    if paid:
        sections += [
            "## License Key", "",
            f"This server requires a license key from [MCP Marketplace](https://mcp-marketplace.io/server/{package_name}).", "",
            "Set the `MCP_LICENSE_KEY` environment variable:", "",
            "```bash", "export MCP_LICENSE_KEY=mcp_live_your_key_here", "```", "",
        ]

    if hosting == "local":
        sections += [
            "## Usage with Claude Code", "",
            "Add to your Claude Code MCP config (`~/.claude/settings.json`):", "",
            "```json", "{{", '  "mcpServers": {{',
            f'    "{package_name}": {{',
            f'      "command": "{package_name}",',
            '      "args": []',
        ]
        if paid:
            sections[-1] = '      "args": [],'
            sections += [
                f'      "env": {{ "MCP_LICENSE_KEY": "mcp_live_your_key_here" }}',
            ]
        sections += ["    }}", "  }}", "}}", "```", ""]
    elif hosting == "remote":
        sections += [
            "## Deployment", "",
            "```bash", "docker build -t " + package_name + " .",
            "docker run -p 8000:8000 " + package_name, "```", "",
        ]

    sections += [
        "## Development", "",
        "```bash",
        f"git clone https://github.com/YOUR_USERNAME/{package_name}.git",
        f"cd {package_name}",
        "uv venv .venv && source .venv/bin/activate",
        'uv pip install -e ".[dev]"',
        "pytest -v",
        "```",
        "",
    ]

    return "\n".join(sections)


def _to_class_name(snake_name: str) -> str:
    """Convert snake_case to PascalCase."""
    return "".join(word.capitalize() for word in snake_name.split("_"))


def render_dockerfile(package_name: str) -> str:
    """Render a Dockerfile for remote hosting."""
    return f"""\
FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir .

ENV PORT=8000

EXPOSE ${{PORT}}

CMD ["{package_name}"]
"""


def render_add_tool_import(package_name: str, tool_name: str) -> str:
    """Render the import line for a new tool to inject into server.py."""
    module_name = _to_module_name(package_name)
    return f"from {module_name}.tools.{tool_name} import {tool_name} as _{tool_name}_impl"


def render_add_tool_registration(tool: dict) -> str:
    """Render the @mcp.tool decorated function for a new tool."""
    tool_name = tool["name"]
    tool_desc = tool.get("description", f"{tool_name} tool")
    params = tool.get("parameters", [])

    param_parts = []
    for p in params:
        pname = p["name"]
        ptype = _python_type(p.get("type", "string"))
        if p.get("required", True):
            param_parts.append(f"{pname}: {ptype}")
        else:
            default = p.get("default")
            if default is None:
                default_str = "None"
                ptype = f"{ptype} | None"
            elif isinstance(default, str):
                default_str = f'"{default}"'
            else:
                default_str = str(default)
            param_parts.append(f"{pname}: {ptype} = {default_str}")

    param_str = ", ".join(param_parts)
    call_args = ", ".join(p["name"] for p in params)

    lines = [
        "",
        f'@mcp.tool(description="{tool_desc}")',
        f"def {tool_name}({param_str}) -> str:",
        f'    """Call the {tool_name} tool."""',
        f"    return _{tool_name}_impl({call_args})",
    ]

    return "\n".join(lines)
