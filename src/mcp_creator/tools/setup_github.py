"""Initialize git and create a GitHub repo for the MCP server project."""

from __future__ import annotations

import json
from pathlib import Path

from mcp_creator.services.subprocess_runner import run_command


def setup_github(
    project_dir: str,
    repo_name: str,
    description: str = "",
    private: bool = False,
) -> str:
    """Initialize a git repo, create a GitHub repo, and push the project.

    Requires the `gh` CLI to be installed and authenticated.

    Args:
        project_dir: Absolute path to the project root.
        repo_name: GitHub repo name (e.g. "my-weather-mcp").
        description: One-line repo description.
        private: If True, create a private repo. Default is public.

    Returns:
        JSON string with repo URL and next steps.
    """
    project = Path(project_dir).resolve()

    if not project.exists():
        return json.dumps({
            "success": False,
            "error": f"Project directory not found: {project}",
        })

    # 1. Check gh CLI is available
    gh_check = run_command(["gh", "auth", "status"], cwd=project)
    if not gh_check["success"]:
        return json.dumps({
            "success": False,
            "error": "GitHub CLI (gh) is not installed or not authenticated.",
            "next_steps": [
                "Install gh: https://cli.github.com/",
                "Then run: gh auth login",
            ],
        })

    # 2. git init (if not already a repo)
    git_check = run_command(["git", "rev-parse", "--git-dir"], cwd=project)
    if not git_check["success"]:
        init_result = run_command(["git", "init"], cwd=project)
        if not init_result["success"]:
            return json.dumps({
                "success": False,
                "error": f"git init failed: {init_result['stderr']}",
            })

    # 3. Stage and commit all files
    run_command(["git", "add", "."], cwd=project)
    commit_result = run_command(
        ["git", "commit", "-m", "Initial commit — scaffolded with mcp-creator"],
        cwd=project,
    )
    # commit may fail if already committed — that's ok

    # 4. Create GitHub repo
    visibility = "--private" if private else "--public"
    create_args = [
        "gh", "repo", "create", repo_name,
        visibility,
        "--source", str(project),
        "--push",
    ]
    if description:
        create_args.extend(["--description", description])

    create_result = run_command(create_args, cwd=project, timeout=30)

    if not create_result["success"]:
        # Maybe repo already exists — try to just add remote and push
        if "already exists" in create_result["stderr"].lower():
            # Get the GitHub username
            whoami = run_command(["gh", "api", "user", "--jq", ".login"], cwd=project)
            username = whoami["stdout"].strip() if whoami["success"] else "OWNER"
            repo_url = f"https://github.com/{username}/{repo_name}"

            run_command(
                ["git", "remote", "add", "origin", f"{repo_url}.git"],
                cwd=project,
            )
            push_result = run_command(
                ["git", "push", "-u", "origin", "main"],
                cwd=project,
                timeout=30,
            )
            if not push_result["success"]:
                # Try HEAD branch name
                run_command(
                    ["git", "push", "-u", "origin", "HEAD"],
                    cwd=project,
                    timeout=30,
                )

            return json.dumps({
                "success": True,
                "repo_url": repo_url,
                "note": "Repo already existed — pushed to it.",
                "next_steps": [
                    f"Code pushed to {repo_url}",
                    "Use generate_launchguide with this URL as the docs_url.",
                ],
            })

        return json.dumps({
            "success": False,
            "error": f"Failed to create GitHub repo: {create_result['stderr']}",
            "next_steps": [
                "Check that gh is authenticated: gh auth status",
                "Try creating the repo manually: gh repo create",
            ],
        })

    # 5. Get the repo URL
    whoami = run_command(["gh", "api", "user", "--jq", ".login"], cwd=project)
    username = whoami["stdout"].strip() if whoami["success"] else "OWNER"
    repo_url = f"https://github.com/{username}/{repo_name}"

    return json.dumps({
        "success": True,
        "repo_url": repo_url,
        "next_steps": [
            f"GitHub repo created: {repo_url}",
            "Use generate_launchguide with this URL as the docs_url for marketplace submission.",
        ],
    })
