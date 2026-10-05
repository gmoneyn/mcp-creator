"""Check the user's environment for required tools and setup status."""

from __future__ import annotations

import json
import os
import shutil

from mcp_creator.services.subprocess_runner import run_command


def check_setup() -> str:
    """Check what tools and accounts the user already has set up.

    Detects: Python, uv, gh CLI, PyPI token, git.
    Returns a status for each so the AI can skip setup steps the user
    has already completed.

    Returns:
        JSON string with setup status and next steps.
    """
    checks: dict[str, dict] = {}

    # Python
    python_result = run_command(["python3", "--version"])
    checks["python"] = {
        "installed": python_result["success"],
        "version": python_result["stdout"] if python_result["success"] else None,
    }

    # uv
    checks["uv"] = {
        "installed": shutil.which("uv") is not None,
    }
    if checks["uv"]["installed"]:
        uv_ver = run_command(["uv", "--version"])
        checks["uv"]["version"] = uv_ver["stdout"] if uv_ver["success"] else None

    # git
    checks["git"] = {
        "installed": shutil.which("git") is not None,
    }

    # gh CLI
    gh_installed = shutil.which("gh") is not None
    gh_authed = False
    gh_username = None
    if gh_installed:
        gh_auth = run_command(["gh", "auth", "status"])
        gh_authed = gh_auth["success"]
        if gh_authed:
            whoami = run_command(["gh", "api", "user", "--jq", ".login"])
            gh_username = whoami["stdout"].strip() if whoami["success"] else None
    checks["github_cli"] = {
        "installed": gh_installed,
        "authenticated": gh_authed,
        "username": gh_username,
    }

    # PyPI token
    has_token = bool(os.environ.get("UV_PUBLISH_TOKEN"))
    checks["pypi_token"] = {
        "configured": has_token,
    }

    # Determine what's missing
    missing = []
    if not checks["uv"]["installed"]:
        missing.append("Install uv: https://docs.astral.sh/uv/getting-started/installation/")
    if not checks["git"]["installed"]:
        missing.append("Install git: https://git-scm.com/downloads")
    if not checks["github_cli"]["installed"]:
        missing.append("Install GitHub CLI: https://cli.github.com/")
    elif not checks["github_cli"]["authenticated"]:
        missing.append("Authenticate GitHub CLI: run 'gh auth login'")
    if not checks["pypi_token"]["configured"]:
        missing.append(
            "Set up PyPI token: get one at https://pypi.org/manage/account/token/ "
            "then export UV_PUBLISH_TOKEN=pypi-..."
        )

    all_ready = len(missing) == 0

    result = {
        "checks": checks,
        "all_ready": all_ready,
        "missing_steps": missing,
        "next_steps": [],
    }

    if all_ready:
        result["next_steps"] = [
            "Everything is set up! The user is ready to create MCP servers.",
            "Skip all setup instructions — go straight to asking what they want to build.",
            "Use check_pypi_name to verify their package name, then scaffold_server to create it.",
        ]
    else:
        result["next_steps"] = [
            f"The user needs to complete {len(missing)} setup step(s) before they can fully publish.",
            "Walk them through only the missing steps listed above.",
            "They can still scaffold and develop locally even without all steps complete.",
        ]

    return json.dumps(result, indent=2)
