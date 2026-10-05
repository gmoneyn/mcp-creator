"""Persistent creator profile — remembers setup state and project history."""

from __future__ import annotations

import json
from pathlib import Path

PROFILE_DIR = Path.home() / ".mcp-creator"
PROFILE_FILE = PROFILE_DIR / "profile.json"


def _load_profile() -> dict:
    """Load or initialize the creator profile."""
    if PROFILE_FILE.exists():
        return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    return {
        "setup_complete": False,
        "github_username": None,
        "pypi_username": None,
        "default_output_dir": None,
        "projects": [],
    }


def _save_profile(profile: dict) -> None:
    """Save the creator profile to disk."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(profile, indent=2), encoding="utf-8")


def get_creator_profile() -> str:
    """Load the creator's profile — their setup status and project history.

    Call this at the start of every session to know the user's state.
    If the profile exists, the user is returning — skip onboarding.

    Returns:
        JSON string with profile data and next steps.
    """
    profile = _load_profile()

    if profile.get("setup_complete") and profile.get("projects"):
        project_names = [p["name"] for p in profile["projects"]]
        next_steps = [
            f"Returning creator with {len(profile['projects'])} project(s): {', '.join(project_names)}.",
            "Skip all setup — ask what they want to build next.",
            "They can also add tools to existing projects or publish updates.",
        ]
    elif profile.get("setup_complete"):
        next_steps = [
            "Setup is complete but no projects yet.",
            "Skip setup instructions — go straight to asking what they want to build.",
        ]
    else:
        next_steps = [
            "New creator — run check_setup to see what they need to install.",
            "Walk them through any missing setup steps.",
        ]

    return json.dumps({"profile": profile, "next_steps": next_steps}, indent=2)


def update_creator_profile(
    setup_complete: bool | None = None,
    github_username: str | None = None,
    pypi_username: str | None = None,
    default_output_dir: str | None = None,
    add_project: str | None = None,
) -> str:
    """Update the creator's profile after setup steps or project creation.

    Args:
        setup_complete: Mark setup as done (all tools installed, accounts ready).
        github_username: Their GitHub username.
        pypi_username: Their PyPI username.
        default_output_dir: Where they want projects created by default.
        add_project: JSON string of a project to add to history:
                     {"name": "my-mcp", "pypi_url": "...", "github_url": "...", "description": "..."}

    Returns:
        JSON string with updated profile.
    """
    profile = _load_profile()

    if setup_complete is not None:
        profile["setup_complete"] = setup_complete
    if github_username is not None:
        profile["github_username"] = github_username
    if pypi_username is not None:
        profile["pypi_username"] = pypi_username
    if default_output_dir is not None:
        profile["default_output_dir"] = default_output_dir
    if add_project is not None:
        project = json.loads(add_project)
        # Don't duplicate
        existing_names = [p["name"] for p in profile["projects"]]
        if project["name"] not in existing_names:
            profile["projects"].append(project)

    _save_profile(profile)

    return json.dumps({
        "success": True,
        "profile": profile,
        "next_steps": ["Profile updated."],
    }, indent=2)
