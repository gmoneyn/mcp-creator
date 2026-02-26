"""Generate a LAUNCHGUIDE.md for MCP Marketplace submission."""

from __future__ import annotations

import json
from pathlib import Path

from mcp_creator.services.file_writer import write_project_files


LAUNCHGUIDE_TEMPLATE = """\
# {package_name}

## Tagline
{tagline}

## Description
{description}

## Setup Requirements
{setup_requirements}

## Category
{category}

## Features
{features}

## Getting Started
{getting_started}

## Tags
{tags}

## Documentation URL
{docs_url}
"""


def generate_launchguide(
    project_dir: str,
    package_name: str,
    tagline: str,
    description: str,
    category: str,
    features: str,
    tools_summary: str,
    tags: str,
    setup_requirements: str = "No environment variables required.",
    docs_url: str = "",
) -> str:
    """Generate a LAUNCHGUIDE.md for MCP Marketplace submission.

    Args:
        project_dir: Absolute path to the project root.
        package_name: PyPI package name.
        tagline: One-liner (max 100 chars).
        description: What the server does, how it works, who it's for.
        category: One of: Developer Tools, Data & Analytics, Productivity, etc.
        features: Bullet-point features (one per line, prefixed with "- "). Max 30 items.
        tools_summary: Tool descriptions for Getting Started (one per line).
        tags: Comma-separated tags. Max 30.
        setup_requirements: Env vars or setup steps (default: none required).
        docs_url: Link to docs or README.

    Returns:
        JSON string with file path and next steps.
    """
    project = Path(project_dir).resolve()

    content = LAUNCHGUIDE_TEMPLATE.format(
        package_name=package_name,
        tagline=tagline,
        description=description,
        setup_requirements=setup_requirements,
        category=category,
        features=features,
        getting_started=tools_summary,
        tags=tags,
        docs_url=docs_url or f"https://pypi.org/project/{package_name}/",
    )

    written = write_project_files(project, {"LAUNCHGUIDE.md": content})

    result = {
        "success": True,
        "file": str(project / "LAUNCHGUIDE.md"),
        "next_steps": [
            "LAUNCHGUIDE.md created!",
            "Review it and make any final edits.",
            f"Submit to MCP Marketplace at https://mcp-marketplace.io with this file.",
        ],
    }

    return json.dumps(result, indent=2)
