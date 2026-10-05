"""Add a new tool to an existing scaffolded MCP server project."""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp_creator.services import codegen, file_writer
from mcp_creator.services.names import check_tool_def
from mcp_creator.services.project_guard import check_project_dir


def add_tool(project_dir: str, tool: str) -> str:
    """Add a new tool to an existing scaffolded MCP server.

    Args:
        project_dir: Absolute path to the project root.
        tool: JSON string — a single tool definition:
              {"name": "get_forecast", "description": "...",
               "parameters": [...], "returns": "..."}

    Returns:
        JSON string with created/modified files and next steps.
    """
    tool_def = json.loads(tool)
    reason = check_tool_def(tool_def)
    if reason:
        return json.dumps({"success": False, "error": reason})
    tool_name = tool_def["name"]
    project, reason = check_project_dir(project_dir)
    if project is None:
        return json.dumps({"success": False, "error": reason})

    # Detect module name from the src/ directory
    src_dir = project / "src"
    if not src_dir.exists():
        return json.dumps({
            "success": False,
            "error": f"No src/ directory found at {project}. Is this a scaffolded MCP project?",
        })

    module_dirs = [d for d in src_dir.iterdir() if d.is_dir() and not d.name.startswith("_")]
    if not module_dirs:
        return json.dumps({
            "success": False,
            "error": "No module directory found under src/.",
        })

    module_name = module_dirs[0].name
    package_name = module_name.replace("_", "-")

    # 1. Create tool module
    tool_file = f"src/{module_name}/tools/{tool_name}.py"
    tool_content = codegen.render_tool_module(package_name, tool_def)

    # 2. Create service stub
    service_file = f"src/{module_name}/services/{tool_name}_service.py"
    service_content = codegen.render_service_module(tool_def)

    # 3. Create test
    test_file = f"tests/test_{tool_name}.py"
    test_content = codegen.render_test_tool(package_name, tool_def)

    # A name that differs from an existing file only by letter case is the SAME file on a
    # case-insensitive filesystem (macOS, Windows), whatever this machine's does. Compare
    # against the folder listing, not through the filesystem.
    case_twins = []
    for candidate in (tool_file, service_file, test_file):
        folder, wanted = (project / candidate).parent, Path(candidate).name
        if folder.is_dir():
            case_twins += [
                f"{candidate} vs {entry}" for entry in sorted(os.listdir(folder))
                if entry != wanted and entry.casefold() == wanted.casefold()
            ]
    if case_twins:
        return json.dumps({
            "success": False,
            "error": (
                f"Tool '{tool_name}' differs only by letter case from files this project already "
                f"has ({'; '.join(case_twins)}). On a case-insensitive filesystem they are the "
                "same file. Pick another name."
            ),
        })

    # Never replace an implemented tool with a stub.
    existing = [
        f for f in (tool_file, service_file, test_file)
        if (project / f).exists() or (project / f).is_symlink()
    ]
    if existing:
        return json.dumps({
            "success": False,
            "error": (
                f"Tool '{tool_name}' already exists in this project ({', '.join(existing)}). "
                "add_tool does not overwrite: pick another name or edit those files directly."
            ),
        })

    files_to_write = {
        tool_file: tool_content,
        service_file: service_content,
        test_file: test_content,
    }

    try:
        written = file_writer.write_project_files(project, files_to_write)
    except file_writer.UnsafePathError as exc:
        return json.dumps({"success": False, "error": str(exc)})

    # 4. Inject import into server.py
    server_path = project / f"src/{module_name}/server.py"
    import_line = codegen.render_add_tool_import(package_name, tool_name)
    try:
        import_ok = file_writer.inject_after_sentinel(
            server_path, "# --- IMPORTS ---", import_line, base_dir=project
        )
    except file_writer.UnsafePathError as exc:
        return json.dumps({"success": False, "error": str(exc)})

    # 5. Inject tool registration into server.py
    registration = codegen.render_add_tool_registration(tool_def)
    reg_ok = file_writer.inject_after_sentinel(
        server_path, "# --- END TOOLS ---", "", base_dir=project
    )
    # Actually inject before END TOOLS
    reg_ok = file_writer.inject_after_sentinel(
        server_path, "# --- TOOLS ---", registration, base_dir=project
    )

    result = {
        "success": True,
        "tool_name": tool_name,
        "files_created": [tool_file, service_file, test_file],
        "server_updated": import_ok and reg_ok,
        "next_steps": [
            f"Tool '{tool_name}' added to the project.",
            f"Implement your logic in src/{module_name}/services/{tool_name}_service.py",
            "Run 'pytest -v' to verify it registers correctly.",
        ],
    }

    return json.dumps(result, indent=2)
