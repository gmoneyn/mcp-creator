"""The LLM-callable tools must stay inside a project directory.

A model that has read hostile text can pass any path. These tests pin what the tools
refuse: writing outside the target directory, and running git / gh / uv publish in a
folder that is not a project.
"""

import json
from pathlib import Path

import pytest

from mcp_creator.services import file_writer
from mcp_creator.services.file_writer import UnsafePathError, write_project_files
from mcp_creator.tools import publish_package as publish_module
from mcp_creator.tools import setup_github as github_module
from mcp_creator.tools.add_tool import add_tool
from mcp_creator.tools.publish_package import publish_package
from mcp_creator.tools.scaffold_server import scaffold_server
from mcp_creator.tools.setup_github import setup_github

TOOLS = json.dumps([{
    "name": "get_weather",
    "description": "Get weather",
    "parameters": [{"name": "city", "type": "string", "required": True, "description": "City"}],
}])


# ---------------------------------------------------------------- file writes

def test_write_refuses_parent_traversal_and_writes_nothing(tmp_path):
    base = tmp_path / "project"
    with pytest.raises(UnsafePathError):
        write_project_files(base, {"ok.txt": "fine", "../escape.txt": "x"})
    assert not (tmp_path / "escape.txt").exists()
    # every path is checked before the first write, so the good file is not left behind
    assert not (base / "ok.txt").exists()


def test_write_refuses_absolute_path_elsewhere(tmp_path):
    base = tmp_path / "project"
    elsewhere = tmp_path / "elsewhere" / "abs.txt"
    with pytest.raises(UnsafePathError):
        write_project_files(base, {str(elsewhere): "x"})
    assert not elsewhere.exists()


def test_write_refuses_symlink_that_leaves_the_directory(tmp_path):
    base = tmp_path / "project"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    (base / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafePathError):
        write_project_files(base, {"link/evil.txt": "x"})
    assert not (outside / "evil.txt").exists()


def test_write_into_a_new_directory_still_works(tmp_path):
    base = tmp_path / "brand" / "new"
    written = write_project_files(base, {"src/pkg/mod.py": "x = 1\n"})
    assert (base / "src" / "pkg" / "mod.py").read_text() == "x = 1\n"
    assert len(written) == 1


def test_inject_refuses_a_file_outside_the_project(tmp_path):
    base = tmp_path / "project"
    base.mkdir()
    victim = tmp_path / "victim.py"
    victim.write_text("# --- IMPORTS ---\n")
    (base / "server.py").symlink_to(victim)
    with pytest.raises(UnsafePathError):
        file_writer.inject_after_sentinel(base / "server.py", "# --- IMPORTS ---", "import os", base_dir=base)
    assert victim.read_text() == "# --- IMPORTS ---\n"


# ------------------------------------------------------------------- scaffold

def test_scaffold_refuses_package_name_that_leaves_output_dir(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    result = json.loads(scaffold_server(
        package_name="../escaped-mcp", description="x", tools=TOOLS, output_dir=str(out),
    ))
    assert result["success"] is False
    assert not (tmp_path / "escaped-mcp").exists()


def test_scaffold_refuses_tool_name_that_leaves_the_project(tmp_path):
    hostile = json.dumps([{"name": "../../../../evil", "description": "x", "parameters": []}])
    result = json.loads(scaffold_server(
        package_name="safe-mcp", description="x", tools=hostile, output_dir=str(tmp_path),
    ))
    # refused by the name check first; the write confinement behind it is tested directly above
    assert result["success"] is False
    assert not (tmp_path / "safe-mcp").exists()
    assert [p.name for p in tmp_path.iterdir()] == []


def test_scaffold_refuses_the_home_directory_as_target(tmp_path, monkeypatch):
    home = tmp_path / "fakehome"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    result = json.loads(scaffold_server(
        package_name="fakehome", description="x", tools=TOOLS, output_dir=str(tmp_path),
    ))
    assert result["success"] is False
    assert "home directory" in result["error"]
    assert list(home.iterdir()) == []


def test_add_tool_refuses_tool_name_that_leaves_the_project(tmp_path):
    scaffolded = json.loads(scaffold_server(
        package_name="add-mcp", description="x", tools=TOOLS, output_dir=str(tmp_path),
    ))
    assert scaffolded["success"] is True
    hostile = json.dumps({"name": "../../../../evil", "description": "x", "parameters": []})
    result = json.loads(add_tool(project_dir=scaffolded["project_dir"], tool=hostile))
    assert result["success"] is False
    assert not list(tmp_path.glob("evil*")) and not list(tmp_path.parent.glob("evil*"))


# ------------------------------------------- setup_github / publish_package

class Recorder:
    """Stands in for run_command: records every command, runs none."""

    def __init__(self, replies=None):
        self.calls = []
        self.replies = replies or {}

    def __call__(self, cmd, cwd=None, env=None, timeout=120):
        self.calls.append(list(cmd))
        if cmd[:3] == ["git", "rev-parse", "--show-toplevel"]:
            # stands in for "this folder is the top of its own repository"
            return {"success": True, "command": " ".join(cmd), "stdout": str(cwd), "stderr": "", "return_code": 0}
        for prefix, reply in self.replies.items():
            if tuple(cmd[:len(prefix)]) == prefix:
                return reply
        return {"success": True, "command": " ".join(cmd), "stdout": "octocat", "stderr": "", "return_code": 0}

    def ran(self, *prefix):
        return [c for c in self.calls if tuple(c[:len(prefix)]) == prefix]


def _project(tmp_path, *, pyproject=True, gitignore=True):
    project = tmp_path / "my-mcp"
    project.mkdir()
    if pyproject:
        (project / "pyproject.toml").write_text('[project]\nname = "my-mcp"\n')
    if gitignore:
        (project / ".gitignore").write_text(".env\n")
    return project


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(github_module, "run_command", rec)
    monkeypatch.setattr(publish_module, "run_command", rec)
    return rec


def test_publish_refuses_folder_without_pyproject(tmp_path, recorder):
    project = _project(tmp_path, pyproject=False)
    (project / "dist").mkdir()
    (project / "dist" / "x.whl").write_text("")
    result = json.loads(publish_package(str(project), token="not-a-real-token"))
    assert result["success"] is False and "pyproject.toml" in result["error"]
    assert recorder.calls == []


def test_publish_refuses_home_directory(tmp_path, recorder, monkeypatch):
    home = _project(tmp_path)
    (home / "dist").mkdir()
    (home / "dist" / "x.whl").write_text("")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    result = json.loads(publish_package(str(home), token="not-a-real-token"))
    assert result["success"] is False and "home directory" in result["error"]
    assert recorder.calls == []


def test_publish_accepts_a_real_project_directory(tmp_path, recorder):
    project = _project(tmp_path)
    result = json.loads(publish_package(str(project)))
    # past the directory check: it now complains about the missing build, not the folder
    assert result["success"] is False and "build_package" in result["error"]
    assert recorder.calls == []


# ------------------------------------------------ symlinks are followed first

def test_write_refuses_dangling_symlink_that_points_outside(tmp_path):
    base = tmp_path / "project"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    # the link's target does not exist yet: a plain write would create it out there
    (base / "notes.txt").symlink_to(outside / "created-by-write.txt")
    with pytest.raises(UnsafePathError):
        write_project_files(base, {"notes.txt": "x"})
    assert list(outside.iterdir()) == []


