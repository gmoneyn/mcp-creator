"""Code generation for scaffolded MCP server projects.

All functions are pure — they return strings, no I/O.
"""

from __future__ import annotations

import json
import keyword
import math
import re

PYPROJECT_TEMPLATE = """\
[project]
name = "{package_name}"
version = "0.1.0"
description = "{description}"
readme = "README.md"
requires-python = ">=3.11"
license = {{ text = "MIT" }}
dependencies = [
    "mcp[cli]>=2.0.0",  # v2 REQUIRED: this template emits `from mcp.server import MCPServer` (2.x). 1.x has no MCPServer and 2.x has no mcp.server.fastmcp, so the floor and the emitted code must move together.
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

import os
import sys

from mcp.server.transport_security import TransportSecuritySettings


def run_stdio(mcp_app):
    \"\"\"Run the MCP server over stdio (default for Claude Code / Cursor).\"\"\"
    mcp_app.run(transport="stdio")


def run_http(mcp_app, host: str = "0.0.0.0", port: int = 8000):
    \"\"\"Run the MCP server over Streamable HTTP (for remote hosting).\"\"\"
    allowed = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if host not in ("127.0.0.1", "localhost") and not allowed:
        sys.exit(
            "[mcp] REFUSING TO START: non-localhost bind requires MCP_ALLOWED_HOSTS "
            "or Host/Origin validation is disabled (DNS-rebinding exposure)."
        )
    sec = TransportSecuritySettings(allowed_hosts=allowed) if allowed else None
    mcp_app.run(transport="streamable-http", host=host, port=port, transport_security=sec)
"""


def _py_str(text) -> str:
    """A Python string literal whose value is exactly `text`.

    Free text (a description, a default) must never be pasted between quotes: a quote,
    a backslash or a newline in it would end the literal and the rest would run as code.
    """
    text = str(text)
    if text.isprintable() and '"' not in text and "\\" not in text:
        return f'"{text}"'
    return repr(text)


def _doc(text) -> str:
    """`text` escaped for the inside of a triple-double-quoted docstring.

    The result is one source line and the docstring's value is exactly `text`.
    """
    return repr(str(text))[1:-1].replace('"', '\\"')


def _one_line(text) -> str:
    """`text` made safe for a `#` comment: a newline would start a new line of the file."""
    return "".join(ch if ch.isprintable() else " " for ch in str(text))


def _py_literal(value) -> str:
    """Python source for a JSON value (a parameter default).

    `str(value)` is not source: inf and nan print as bare names that do not exist.
    """
    if isinstance(value, str):
        return _py_str(value)
    if value is None or isinstance(value, (bool, int)):
        return repr(value)
    if isinstance(value, float):
        if math.isnan(value):
            return 'float("nan")'
        if math.isinf(value):
            return 'float("inf")' if value > 0 else 'float("-inf")'
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_py_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_py_str(k)}: {_py_literal(v)}" for k, v in value.items()) + "}"
    return _py_str(value)


def _toml_str(text) -> str:
    """The inside of a TOML basic string.

    Its value is exactly `text`, except that an unpaired surrogate (which is not a
    Unicode scalar value, so neither TOML nor UTF-8 can carry it) becomes U+FFFD.
    """
    text = "".join("\ufffd" if 0xD800 <= ord(ch) <= 0xDFFF else ch for ch in str(text))
    return json.dumps(text, ensure_ascii=False)[1:-1].replace("\x7f", "\\u007f")


# Characters that can open Markdown structure anywhere in a line: emphasis, code,
# links and images, HTML, headings, tables, strikethrough, entities, e-mail autolinks.
_MD_SPECIAL = frozenset("\\`*_{}[]()<>#|~!&@")


# GitHub-flavoured renderers turn bare URLs, www. hosts and e-mail addresses into links,
# and some (remark-gfm) do it AFTER backslash escapes are resolved, so escaping cannot
# stop it. A code span can: its content is shown as written and is never linked.
_MD_LINK_LIKE = re.compile(r"://|www\.|@|mailto:|xmpp:", re.IGNORECASE)


def _md_code_span(word: str) -> str:
    """`word` as an inline code span (fence longer than any backtick run inside it)."""
    longest = max((len(run) for run in re.findall(r"`+", word)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if word.startswith("`") or word.endswith("`") else ""
    return f"{fence}{pad}{word}{pad}{fence}"


def _md_text(text, limit: int = 500) -> str:
    """Free text for a SINGLE-LINE Markdown slot, so that it renders as that text.

    Line breaks and control characters collapse to one space (a new line is where
    headings, fences and lists start), the result is capped with a visible ellipsis,
    every character that could open structure or a link is backslash-escaped, and any
    word a renderer would auto-link (a URL, a www. host, an e-mail address) is put in a
    code span.
    """
    flat = " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())
    if len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "\u2026"
    escaped = " ".join(
        _md_code_span(word) if _MD_LINK_LIKE.search(word)
        else "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in word)
        for word in flat.split(" ")
    )
    # the slot may begin a line: a list marker or a setext underline starts there
    ordered = re.match(r"(\d{1,9})([.)])", escaped)
    if ordered:
        escaped = ordered.group(1) + "\\" + ordered.group(2) + escaped[ordered.end():]
    elif escaped[:1] in ("-", "+", "="):
        escaped = "\\" + escaped
    return escaped


def _ordered_params(parameters):
    """Required params first, optional after — Python forbids a non-default arg
    following a default one, so input order alone emits `def f(opt=None, req)`,
    a SyntaxError. Stable within each group so declared order is otherwise kept."""
    req = [p for p in parameters if p.get("required", True)]
    opt = [p for p in parameters if not p.get("required", True)]
    return req + opt


def _to_module_name(package_name: str) -> str:
    """Convert a PyPI package name to a Python module name."""
    return package_name.replace("-", "_")


TYPE_MAP = {
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


def _python_type(type_str: str) -> str:
    """Map a simple type string to a Python type annotation."""
    return TYPE_MAP.get(str(type_str).lower(), "str")


def render_pyproject(package_name: str, description: str, *, paid: bool = False) -> str:
    module_name = _to_module_name(package_name)
    base = PYPROJECT_TEMPLATE.format(
        package_name=package_name,
        description=_toml_str(description),
        module_name=module_name,
    )
    if paid:
        # Anchor on the CLOSING BRACKET of the dependencies list, not on the mcp pin —
        # a previous edit to the pin string silently broke this replace and paid servers
        # scaffolded with NO license dependency (money path, failed silently). Assert it.
        # Anchor on a UNIQUE boundary, not a bare ']' — a bare bracket also matches the
        # dev-dependencies list, which would license the wrong list. And do NOT use assert:
        # it is stripped under `python -O`, restoring the silent no-op this replaces.
        marker = ']\n\n[project.scripts]'
        if base.count(marker) != 1:
            raise RuntimeError(
                "pyproject template shape changed: expected exactly one "
                f"'{marker!r}' boundary, found {base.count(marker)}. "
                "Paid license-dependency injection would silently no-op."
            )
        base = base.replace(marker, '    "mcp-marketplace-license>=1.1.0",\n' + marker, 1)
        if 'mcp-marketplace-license' not in base.split('[project.scripts]')[0]:
            raise RuntimeError("license dependency did not land in [project.dependencies]")
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
        # Left empty on purpose: the server refuses to start without it, and a filled-in
        # placeholder would satisfy that guard with a host nobody chose.
        lines.append("# Host values clients may use to reach this server (required, the server refuses to start without it)")
        lines.append("# Comma-separated. Example: my-server.example.com,localhost")
        lines.append("MCP_ALLOWED_HOSTS=")
        lines.append("")
    if env_vars:
        for var in env_vars:
            name = var.get("name", "UNKNOWN")
            desc = var.get("description", "")
            required = var.get("required", True)
            tag = "required" if required else "optional"
            lines.append(f"# {_one_line(desc)} ({tag})")
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
    """Render the main server.py with MCPServer (mcp SDK v2) and tool registrations."""
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

    lines.append("from mcp.server import MCPServer")
    if hosting == "remote":
        lines.append("import sys")
        lines.append("from mcp.server.transport_security import TransportSecuritySettings")

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
    lines.append(f'mcp = MCPServer("{package_name}", version="1.0.0")')

    if paid:
        lines.append("")
        lines.append("")
        lines.append("def _require_license(tool_name: str) -> str | None:")
        lines.append('    """Return None if licensed, or a JSON error string."""')
        if hosting == "remote":
            lines.append("    # Known limitation: this checks the license key set on the server, so it does not")
            lines.append("    # tell one caller from another. Per-buyer checks need a per-request key check.")
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
        params = _ordered_params(tool.get("parameters", []))
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
                    default_str = _py_str(default)
                else:
                    default_str = _py_literal(default)
                param_parts.append(f"{pname}: {ptype} = {default_str}")

        param_str = ", ".join(param_parts)
        call_args = ", ".join(p["name"] for p in params)

        lines.append("")
        lines.append(f"@mcp.tool(description={_py_str(tool_desc)})")
        lines.append(f"def {tool_name}({param_str}) -> str:")
        lines.append(f'    """Call the {tool_name} tool."""')
        if is_gated:
            lines.append(f'    _err = _require_license("{tool_name}")')
            lines.append("    if _err:")
            lines.append("        return _err")
        lines.append(f"    return _{tool_name}_impl({call_args})")

    lines.append("# --- END TOOLS ---")
    lines.append("")
    lines.append("")
    lines.append("def main():")
    lines.append('    """Run the MCP server."""')
    if hosting == "remote":
        lines.append('    port = int(os.environ.get("PORT", "8000"))')
        # 0.0.0.0 disables the automatic localhost Host/Origin allowlist, so pass
        # TransportSecuritySettings explicitly rather than binding wide with no guard.
        # FAIL CLOSED. Binding 0.0.0.0 disables the automatic localhost allowlist, so an
        # unset MCP_ALLOWED_HOSTS means "publicly bound with no Host/Origin validation".
        # A warning does not protect anything — refuse to start instead.
        lines.append('    allowed = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]')
        lines.append('    if not allowed:')
        lines.append('        sys.exit(')
        lines.append('            "[mcp] REFUSING TO START: binding 0.0.0.0 requires MCP_ALLOWED_HOSTS "')
        lines.append('            "(comma-separated Host values), otherwise Host/Origin validation is disabled "')
        lines.append('            "and the server is exposed to DNS-rebinding. Example: MCP_ALLOWED_HOSTS=my.host,localhost"')
        lines.append('        )')
        lines.append('    sec = TransportSecuritySettings(allowed_hosts=allowed)')
        lines.append('    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, transport_security=sec)')
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
    params = _ordered_params(tool.get("parameters", []))
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
                default_str = _py_str(default)
            else:
                default_str = _py_literal(default)
            param_parts.append(f"{pname}: {ptype} = {default_str}")

    param_str = ", ".join(param_parts)

    lines = [
        f'"""{_doc(tool_desc)}."""',
        "",
        "import json as _json",
        "",
        f"from {module_name}.services.{tool_name}_service import {_to_class_name(tool_name)} as _Service",
        "",
        "",
        f"def {tool_name}({param_str}) -> str:",
        f'    """{_doc(tool_desc)}',
        "",
        f"    Returns:",
        f"        {_doc(returns)}",
        '    """',
        f"    _result = _Service().execute({', '.join(p['name'] + '=' + p['name'] for p in params)})",
        "    return _json.dumps(_result, indent=2)",
        "",
    ]

    return "\n".join(lines)


def render_service_module(tool: dict) -> str:
    """Render a service stub (services/<name>_service.py)."""
    tool_name = tool["name"]
    tool_desc = tool.get("description", f"{tool_name} service")
    params = _ordered_params(tool.get("parameters", []))
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
                default_str = _py_str(default)
            else:
                default_str = _py_literal(default)
            param_parts.append(f"{pname}: {ptype} = {default_str}")

    param_str = ", ".join(param_parts)

    # Build placeholder return dict
    placeholder_fields = {}
    for p in params:
        placeholder_fields[p["name"]] = p["name"]
    placeholder_fields.setdefault("status", '"ok"')   # a parameter named status keeps its value

    result_lines = [f'            "{k}": {v},' for k, v in placeholder_fields.items()]
    result_block = "\n".join(result_lines)

    lines = [
        f'"""{_doc(tool_desc)} — service layer."""',
        "",
        "",
        f"class {class_name}:",
        f'    """{_doc(tool_desc)}.',
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
    params = _ordered_params(tool.get("parameters", []))

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
        # imported under an alias: pytest would otherwise collect a tool named test_*
        f"from {module_name}.tools.{tool_name} import {tool_name} as _tool",
        "",
        "",
        f"def test_{tool_name}_returns_json():",
        f"    _result = _tool({args_str})",
        "    _data = json.loads(_result)",
        "    assert isinstance(_data, dict)",
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
        f"- **{t['name']}** — {_md_text(t.get('description', t['name']))}" for t in tools
    )

    sections = [f"# {package_name}", "", _md_text(description), ""]

    if hosting == "local":
        sections += [
            "## Install", "",
            "```bash", f"uvx {package_name}", "```", "",
            "Or install permanently:", "",
            "```bash", f"pip install {package_name}", "```", "",
        ]
    else:
        sections += [
            "## Connect", "",
            "This is a remote MCP server. Add to your Claude Code config:", "",
            "```json", "{", '  "mcpServers": {', f'    "{package_name}": {{',
            f'      "url": "https://your-server.com/mcp"',
            "    }", "  }", "}", "```", "",
        ]

    sections += ["## Tools", "", tool_list, ""]

    if paid and hosting == "remote":
        # A hosted server reads the key from ITS OWN environment. Telling the person who
        # connects by URL to export a key on their machine would be false, so do not.
        sections += [
            "## License Key", "",
            f"Paid tools need a license key from [MCP Marketplace](https://mcp-marketplace.io/server/{package_name}).", "",
            "The key is read by the server, not sent by the people who connect to it. "
            "Whoever runs the server sets `MCP_LICENSE_KEY` in the server's environment "
            "(with Docker, add `-e MCP_LICENSE_KEY=mcp_live_your_key_here` to the `docker run` command below). "
            "Without it, every paid tool answers `premium_required`.", "",
            "**Known limitation:** this scaffold checks the license key set on the server, "
            "so it does not yet tell one caller from another. Per-buyer checks on a hosted "
            "server need a per-request key check, coming with the next license SDK release.", "",
        ]
    elif paid:
        sections += [
            "## License Key", "",
            f"This server requires a license key from [MCP Marketplace](https://mcp-marketplace.io/server/{package_name}).", "",
            "Set the `MCP_LICENSE_KEY` environment variable:", "",
            "```bash", "export MCP_LICENSE_KEY=mcp_live_your_key_here", "```", "",
        ]

    if hosting == "local":
        sections += [
            "## Usage with Claude Code", "",
            "```bash",
            f'claude mcp add {package_name} -- uvx {package_name}',
            "```", "",
            "Or add to your MCP config (`~/.claude/settings.json`):", "",
            "```json", "{", '  "mcpServers": {',
            f'    "{package_name}": {{',
            f'      "command": "uvx",',
            f'      "args": ["{package_name}"]',
        ]
        if paid:
            sections[-1] = f'      "args": ["{package_name}"],'
            sections += [
                f'      "env": {{ "MCP_LICENSE_KEY": "mcp_live_your_key_here" }}',
            ]
        sections += ["    }", "  }", "}", "```", ""]
    elif hosting == "remote":
        # The generated server exits at startup unless MCP_ALLOWED_HOSTS is set, so every
        # command shown here must set it. Keep these in step with render_server().
        sections += [
            "## Deployment", "",
            "The server binds `0.0.0.0` and refuses to start unless `MCP_ALLOWED_HOSTS` is set. "
            "Set it to the comma-separated Host values clients will send, for example "
            "`my-server.example.com,localhost`. A value must match the Host header exactly, "
            "port included (`localhost:8000`); `localhost:*` allows any port.", "",
            "With Docker:", "",
            "```bash", "docker build -t " + package_name + " .",
            "docker run -e MCP_ALLOWED_HOSTS=<your-host> -p 8000:8000 " + package_name, "```", "",
            "Without Docker:", "",
            "```bash", "pip install .",
            "MCP_ALLOWED_HOSTS=<your-host> " + package_name, "```", "",
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
    """Convert snake_case to PascalCase, always yielding a usable class name.

    `true` would become the keyword True, and a name with no letters before a digit
    would not be an identifier at all, so those get a fixed suffix or prefix.
    """
    name = "".join(word.capitalize() for word in snake_name.split("_") if word)
    if not name or not name[0].isalpha():
        name = "Tool" + name
    if keyword.iskeyword(name):
        name += "Service"
    return name


def render_dockerfile(package_name: str) -> str:
    """Render a Dockerfile for remote hosting."""
    return f"""\
FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir .

ENV PORT=8000

# MCP_ALLOWED_HOSTS is required at run time (comma-separated Host values); the server
# refuses to start without it. It is deliberately not set here. Pass it when you run:
#   docker run -e MCP_ALLOWED_HOSTS=<your-host> -p 8000:8000 {package_name}

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
    params = _ordered_params(tool.get("parameters", []))

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
                default_str = _py_str(default)
            else:
                default_str = _py_literal(default)
            param_parts.append(f"{pname}: {ptype} = {default_str}")

    param_str = ", ".join(param_parts)
    call_args = ", ".join(p["name"] for p in params)

    lines = [
        "",
        f"@mcp.tool(description={_py_str(tool_desc)})",
        f"def {tool_name}({param_str}) -> str:",
        f'    """Call the {tool_name} tool."""',
        f"    return _{tool_name}_impl({call_args})",
    ]

    return "\n".join(lines)
