"""MCP Creator — create, build, and publish Python MCP servers to PyPI."""

from mcp.server.fastmcp import FastMCP

from mcp_creator.tools.creator_profile import get_creator_profile as _get_creator_profile
from mcp_creator.tools.creator_profile import update_creator_profile as _update_creator_profile
from mcp_creator.tools.check_setup import check_setup as _check_setup
from mcp_creator.tools.check_pypi_name import check_pypi_name as _check_pypi_name
from mcp_creator.tools.scaffold_server import scaffold_server as _scaffold_server
from mcp_creator.tools.add_tool import add_tool as _add_tool
from mcp_creator.tools.build_package import build_package as _build_package
from mcp_creator.tools.publish_package import publish_package as _publish_package
from mcp_creator.tools.setup_github import setup_github as _setup_github
from mcp_creator.tools.generate_launchguide import generate_launchguide as _generate_launchguide

mcp = FastMCP("mcp-creator")


@mcp.tool(
    description=(
        "Load the creator's persistent profile — their setup status, GitHub/PyPI usernames, "
        "and project history. Call this FIRST in every session. If the profile exists with "
        "setup_complete=true, skip all onboarding and go straight to building."
    )
)
def get_creator_profile() -> str:
    """Load creator profile."""
    return _get_creator_profile()


@mcp.tool(
    description=(
        "Update the creator's profile after setup steps or project creation. "
        "Call this after: setup completes, a project is published, or GitHub/PyPI info is learned. "
        "This persists across sessions so the user never repeats setup."
    )
)
def update_creator_profile(
    setup_complete: bool | None = None,
    github_username: str | None = None,
    pypi_username: str | None = None,
    default_output_dir: str | None = None,
    add_project: str | None = None,
) -> str:
    """Update creator profile."""
    return _update_creator_profile(
        setup_complete=setup_complete,
        github_username=github_username,
        pypi_username=pypi_username,
        default_output_dir=default_output_dir,
        add_project=add_project,
    )


@mcp.tool(
    description=(
        "Check the user's environment for required tools (uv, git, gh CLI, PyPI token). "
        "Call this after get_creator_profile if setup_complete is false. "
        "If everything is set up, skip beginner instructions and go straight to building."
    )
)
def check_setup() -> str:
    """Check what's already set up."""
    return _check_setup()


@mcp.tool(
    description="Check if a package name is available on PyPI. Call this first before scaffolding."
)
def check_pypi_name(package_name: str) -> str:
    """Check PyPI name availability."""
    return _check_pypi_name(package_name=package_name)


@mcp.tool(
    description=(
        "Scaffold a complete, runnable MCP server project. "
        "Pass the package name, description, and a JSON array of tool definitions. "
        "Each tool def: {name, description, parameters: [{name, type, required, description, default}], returns}. "
        "The generated server runs immediately with stub implementations."
    )
)
def scaffold_server(
    package_name: str,
    description: str,
    tools: str,
    output_dir: str = ".",
    env_vars: str | None = None,
) -> str:
    """Scaffold a complete MCP server project."""
    return _scaffold_server(
        package_name=package_name,
        description=description,
        tools=tools,
        output_dir=output_dir,
        env_vars=env_vars,
    )


@mcp.tool(
    description=(
        "Add a new tool to an existing scaffolded MCP server. "
        "Pass the project directory and a JSON tool definition. "
        "Creates the tool module, service stub, test, and updates server.py."
    )
)
def add_tool(project_dir: str, tool: str) -> str:
    """Add a tool to an existing project."""
    return _add_tool(project_dir=project_dir, tool=tool)


@mcp.tool(
    description="Build the MCP server package using 'uv build'. Run this after implementing your tools."
)
def build_package(project_dir: str) -> str:
    """Build the package."""
    return _build_package(project_dir=project_dir)


@mcp.tool(
    description=(
        "Publish the built package to PyPI using 'uv publish'. "
        "Requires a PyPI token — either pass it directly or set UV_PUBLISH_TOKEN env var."
    )
)
def publish_package(project_dir: str, token: str | None = None) -> str:
    """Publish to PyPI."""
    return _publish_package(project_dir=project_dir, token=token)


@mcp.tool(
    description=(
        "Initialize git, create a GitHub repo, and push the project. "
        "Requires the gh CLI to be installed and authenticated. "
        "Run this after publishing to PyPI so the repo URL can be included in the LAUNCHGUIDE."
    )
)
def setup_github(
    project_dir: str,
    repo_name: str,
    description: str = "",
    private: bool = False,
) -> str:
    """Create GitHub repo and push code."""
    return _setup_github(
        project_dir=project_dir,
        repo_name=repo_name,
        description=description,
        private=private,
    )


@mcp.tool(
    description=(
        "Generate a LAUNCHGUIDE.md for MCP Marketplace submission. "
        "Creates a formatted file ready to submit at mcp-marketplace.io. "
        "Limits: tagline max 100 chars, features max 30 items, tags max 30."
    )
)
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
    """Generate LAUNCHGUIDE.md."""
    return _generate_launchguide(
        project_dir=project_dir,
        package_name=package_name,
        tagline=tagline,
        description=description,
        category=category,
        features=features,
        tools_summary=tools_summary,
        tags=tags,
        setup_requirements=setup_requirements,
        docs_url=docs_url,
    )


def main():
    """Run the MCP Creator server."""
    mcp.run()


if __name__ == "__main__":
    main()
