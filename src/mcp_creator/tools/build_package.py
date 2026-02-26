"""Build an MCP server package with uv build."""

from __future__ import annotations

import json
from pathlib import Path

from mcp_creator.services.subprocess_runner import run_command


def build_package(project_dir: str) -> str:
    """Build the MCP server package using uv build.

    Args:
        project_dir: Absolute path to the project root.

    Returns:
        JSON string with build result and next steps.
    """
    project = Path(project_dir).resolve()

    if not (project / "pyproject.toml").exists():
        return json.dumps({
            "success": False,
            "error": f"No pyproject.toml found at {project}.",
            "next_steps": ["Make sure you're pointing to the right project directory."],
        })

    result = run_command(["uv", "build"], cwd=project)

    if result["success"]:
        # Find built files
        dist_dir = project / "dist"
        built_files = []
        if dist_dir.exists():
            built_files = [f.name for f in dist_dir.iterdir()]

        result["built_files"] = built_files
        result["next_steps"] = [
            "Build successful!",
            f"Built files: {', '.join(built_files)}",
            "Next: use publish_package to upload to PyPI, or test locally first.",
        ]
    else:
        result["next_steps"] = [
            "Build failed. Check the error output above.",
            "Common fixes: make sure uv is installed, dependencies are correct, and there are no syntax errors.",
        ]

    return json.dumps(result, indent=2)
