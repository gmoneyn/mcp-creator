"""Publish an MCP server package to PyPI with uv publish."""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp_creator.services.subprocess_runner import run_command


def publish_package(project_dir: str, token: str | None = None) -> str:
    """Publish the built package to PyPI using uv publish.

    Args:
        project_dir: Absolute path to the project root.
        token: Optional PyPI API token. If not provided, uses UV_PUBLISH_TOKEN
               environment variable.

    Returns:
        JSON string with publish result and next steps.
    """
    project = Path(project_dir).resolve()
    dist_dir = project / "dist"

    if not dist_dir.exists() or not list(dist_dir.iterdir()):
        return json.dumps({
            "success": False,
            "error": "No dist/ directory or it's empty. Run build_package first.",
            "next_steps": ["Use build_package to build the project before publishing."],
        })

    # Build env with token if provided
    env = dict(os.environ)
    if token:
        env["UV_PUBLISH_TOKEN"] = token

    if not token and "UV_PUBLISH_TOKEN" not in env:
        return json.dumps({
            "success": False,
            "error": "No PyPI token found. Set UV_PUBLISH_TOKEN or pass a token.",
            "next_steps": [
                "Get a PyPI API token at https://pypi.org/manage/account/token/",
                "Then either: export UV_PUBLISH_TOKEN=pypi-... or pass it to this tool.",
            ],
        })

    result = run_command(["uv", "publish"], cwd=project, env=env)

    if result["success"]:
        # Try to extract package name from pyproject.toml
        pyproject_path = project / "pyproject.toml"
        package_name = "your-package"
        if pyproject_path.exists():
            for line in pyproject_path.read_text().splitlines():
                if line.strip().startswith("name"):
                    package_name = line.split("=")[1].strip().strip('"').strip("'")
                    break

        result["next_steps"] = [
            f"Published to PyPI! Install with: pip install {package_name}",
            f"View at: https://pypi.org/project/{package_name}/",
            "Next: use setup_github to create a GitHub repo and push the code.",
            "Then use generate_launchguide to create a LAUNCHGUIDE.md for marketplace submission.",
        ]
    else:
        result["next_steps"] = [
            "Publish failed. Check the error output.",
            "Common issues: invalid token, package name conflict, or network error.",
        ]

    return json.dumps(result, indent=2)
