"""Leftover guards: every project_dir tool checks the directory, setup_github will not
stage into someone else's repository, the scaffolder itself has no HTTP helper, and a
publish token never comes back in a tool result."""

import json
import os
from pathlib import Path

import pytest

from mcp_creator import transport
from mcp_creator.services.subprocess_runner import run_command as real_run_command
from mcp_creator.tools import build_package as build_module
from mcp_creator.tools import publish_package as publish_module
from mcp_creator.tools import setup_github as github_module
from mcp_creator.tools.add_tool import add_tool
from mcp_creator.tools.build_package import build_package
from mcp_creator.tools.generate_launchguide import generate_launchguide
from mcp_creator.tools.publish_package import publish_package
from mcp_creator.tools.scaffold_server import scaffold_server
from mcp_creator.tools.setup_github import setup_github

TOOLS = json.dumps([{"name": "get_weather", "description": "Get weather", "parameters": []}])
NEW_TOOL = json.dumps({"name": "get_forecast", "description": "Forecast", "parameters": []})
GUIDE = dict(package_name="my-mcp", tagline="t", description="d", category="c", features="- f", tags="x")
FAKE_TOKEN = "pypi-FAKE-not-a-real-token-0123456789"


class Recorder:
    def __init__(self, reply=None):
        self.calls = []
        self.kwargs = []
        self.reply = reply or {"success": True, "command": "", "stdout": "", "stderr": "", "return_code": 0}

    def __call__(self, cmd, cwd=None, env=None, timeout=120):
        self.calls.append(list(cmd))
        self.kwargs.append({"cwd": cwd, "env": env})
        return dict(self.reply, command=" ".join(cmd))


def _dir(tmp_path, name="proj", *, pyproject=True, src=True):
    project = tmp_path / name
    project.mkdir(parents=True)
    if pyproject:
        (project / "pyproject.toml").write_text('[project]\nname = "my-mcp"\n')
    if src:
        module = project / "src" / "my_mcp"
        module.mkdir(parents=True)
        (module / "server.py").write_text("# --- IMPORTS ---\n# --- END IMPORTS ---\n# --- TOOLS ---\n# --- END TOOLS ---\n")
    return project


def _snapshot(folder):
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


# --------------------------------------------------- 1. no HTTP helper in the scaffolder

def test_scaffolder_has_no_http_helper():
    # the scaffolder is a stdio server; a helper that binds a network address has no caller
    assert not hasattr(transport, "run_http")
    assert "0.0.0.0" not in Path(transport.__file__).read_text()


# -------------------------------------------- 2. project-directory rule on three more tools

CALLS = {
    "build_package": lambda d: build_package(str(d)),
    "add_tool": lambda d: add_tool(str(d), NEW_TOOL),
    "generate_launchguide": lambda d: generate_launchguide(project_dir=str(d), **GUIDE),
}


@pytest.fixture
def no_uv(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(build_module, "run_command", rec)
    return rec


@pytest.mark.parametrize("tool", sorted(CALLS))
def test_tool_refuses_folder_without_pyproject(tmp_path, no_uv, tool):
    folder = _dir(tmp_path, pyproject=False)
    before = _snapshot(folder)
    result = json.loads(CALLS[tool](folder))
    assert result["success"] is False and "pyproject.toml" in result["error"]
    assert _snapshot(folder) == before and no_uv.calls == []


@pytest.mark.parametrize("tool", sorted(CALLS))
def test_tool_refuses_home_directory(tmp_path, no_uv, monkeypatch, tool):
    home = _dir(tmp_path, "home")          # looks like a project in every other way
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    before = _snapshot(home)
    result = json.loads(CALLS[tool](home))
    assert result["success"] is False and "home directory" in result["error"]
    assert _snapshot(home) == before and no_uv.calls == []


@pytest.mark.parametrize("tool", sorted(CALLS))
def test_tool_refuses_parent_of_home_and_root(tmp_path, no_uv, monkeypatch, tool):
    parent = _dir(tmp_path, "users")
    home = parent / "someone"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    before = _snapshot(parent)
    result = json.loads(CALLS[tool](parent))
    assert result["success"] is False and "contains your home directory" in result["error"]
    root = json.loads(CALLS[tool](Path(tmp_path.anchor)))
    assert root["success"] is False and "filesystem root" in root["error"]
    assert _snapshot(parent) == before and no_uv.calls == []


@pytest.mark.parametrize("tool", sorted(CALLS))
def test_tool_refuses_missing_directory(tmp_path, no_uv, tool):
    result = json.loads(CALLS[tool](tmp_path / "nope"))
    assert result["success"] is False and "not found" in result["error"]
    assert not (tmp_path / "nope").exists() and no_uv.calls == []


# ------------------------------------- 3. setup_github and a surrounding repository


# ------------------------------------------------- 4. the publish token never comes back


