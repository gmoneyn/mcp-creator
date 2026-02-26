"""Check if a package name is available on PyPI."""

from __future__ import annotations

import json

from mcp_creator.services.pypi_client import check_name_available


def check_pypi_name(package_name: str) -> str:
    """Check if a PyPI package name is available.

    Args:
        package_name: The name to check (e.g. "my-cool-mcp").

    Returns:
        JSON string with availability info and next steps.
    """
    result = check_name_available(package_name)

    if result.get("available"):
        result["next_steps"] = [
            f'Great — "{package_name}" is available on PyPI!',
            "Next: define what tools your MCP server should have, then use scaffold_server to create the project.",
        ]
    elif result.get("available") is False:
        result["next_steps"] = [
            f'"{package_name}" is already taken on PyPI.',
            result.get("suggestion", 'Try adding "-mcp" or a unique prefix.'),
        ]
    else:
        result["next_steps"] = [
            "Could not check PyPI right now.",
            result.get("suggestion", "Try again in a moment."),
        ]

    return json.dumps(result, indent=2)
