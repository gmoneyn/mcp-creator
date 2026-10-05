"""Paths are compared by what they ARE on disk, not by how they are spelled.

Letter case (two spellings of one folder on macOS and Windows) and hard links (two names
for one file) both defeat a comparison of path strings.
"""

import json
import os
from pathlib import Path

import pytest

from mcp_creator.services import file_writer
from mcp_creator.services.file_writer import UnsafePathError, write_project_files
from mcp_creator.services.project_guard import check_project_dir
from mcp_creator.tools.add_tool import add_tool
from mcp_creator.tools.scaffold_server import scaffold_server

TOOLS = json.dumps([{"name": "fetch", "description": "Fetch", "parameters": []}])


@pytest.fixture
def ignores_case(tmp_path):
    """Skip on a filesystem where FOO and foo are different folders: the bypass does not exist there."""
    (tmp_path / "CaseProbe").mkdir()
    if not (tmp_path / "caseprobe").exists():
        pytest.skip("case-sensitive filesystem")


def _project_like(folder):
    folder.mkdir(parents=True)
    (folder / "pyproject.toml").write_text('[project]\nname = "x"\n')
    return folder


# ------------------------------------------------ finding 2: home, by identity

def test_home_directory_is_refused_under_another_spelling(tmp_path, monkeypatch, ignores_case):
    home = _project_like(tmp_path / "fakehome")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for spelling in (tmp_path / "fakehome", tmp_path / "FAKEHOME", tmp_path / "FakeHome"):
        project, reason = check_project_dir(spelling)
        assert project is None and "home directory" in reason, spelling


def test_parent_of_home_is_refused_under_another_spelling(tmp_path, monkeypatch, ignores_case):
    parent = _project_like(tmp_path / "users")
    home = parent / "someone"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for spelling in (tmp_path / "users", tmp_path / "USERS"):
        project, reason = check_project_dir(spelling)
        assert project is None and "contains your home directory" in reason, spelling


def test_ordinary_project_is_still_accepted_under_any_spelling(tmp_path, monkeypatch, ignores_case):
    _project_like(tmp_path / "MyProject")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert check_project_dir(tmp_path / "myproject")[1] is None


# ---------------------------------------- finding 2: write confinement, by identity

def test_different_spelling_of_the_project_root_still_counts_as_inside(tmp_path, ignores_case):
    base = tmp_path / "Proj"
    base.mkdir()
    write_project_files(base, {str(tmp_path / "PROJ" / "a.txt"): "inside"})
    write_project_files(tmp_path / "proj", {"sub/b.txt": "inside too"})
    assert (base / "a.txt").read_text() == "inside" and (base / "sub" / "b.txt").read_text() == "inside too"
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.lower().startswith("proj")) == ["Proj"]


def test_outside_path_cannot_pass_by_letter_case(tmp_path):
    base = tmp_path / "proj"
    base.mkdir()
    sibling = tmp_path / "PROJ2"
    sibling.mkdir()
    for outside in (sibling / "x.txt", tmp_path / "Proj2" / "x.txt", tmp_path / "PROJ" / ".." / "PROJ2" / "x.txt",
                    tmp_path / "other" / "x.txt"):
        with pytest.raises(UnsafePathError):
            write_project_files(base, {str(outside): "x"})
    assert list(sibling.iterdir()) == [] and not (tmp_path / "other").exists()


def test_the_project_root_itself_is_not_a_file_target_under_any_spelling(tmp_path, ignores_case):
    base = tmp_path / "proj"
    base.mkdir()
    with pytest.raises(UnsafePathError):
        write_project_files(base, {str(tmp_path / "PROJ"): "x"})


# ------------------------------------------------------- finding 10: hard links

def test_existing_file_hard_linked_elsewhere_is_not_overwritten(tmp_path):
    base = tmp_path / "project"
    base.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("theirs")
    os.link(victim, base / "notes.txt")                 # one file, two names: one inside, one outside
    with pytest.raises(UnsafePathError) as refusal:
        write_project_files(base, {"ok.txt": "fine", "notes.txt": "overwritten"})
    assert "hard-linked" in str(refusal.value)
    assert victim.read_text() == "theirs" and not (base / "ok.txt").exists()


def test_inject_refuses_a_hard_linked_file(tmp_path):
    base = tmp_path / "project"
    base.mkdir()
    victim = tmp_path / "victim.py"
    victim.write_text("# --- IMPORTS ---\n")
    os.link(victim, base / "server.py")
    with pytest.raises(UnsafePathError):
        file_writer.inject_after_sentinel(base / "server.py", "# --- IMPORTS ---", "import os", base_dir=base)
    assert victim.read_text() == "# --- IMPORTS ---\n"


def test_overwriting_an_ordinary_file_replaces_it_and_keeps_its_mode(tmp_path):
    base = tmp_path / "project"
    base.mkdir()
    target = base / "run.sh"
    target.write_text("old")
    target.chmod(0o755)
    write_project_files(base, {"run.sh": "new", "fresh.txt": "new file"})
    assert target.read_text() == "new" and (target.stat().st_mode & 0o777) == 0o755
    assert ((base / "fresh.txt").stat().st_mode & 0o777) & 0o600 == 0o600
    assert sorted(p.name for p in base.iterdir()) == ["fresh.txt", "run.sh"]        # no temp file left behind


def test_writing_never_goes_through_a_shared_file_even_without_the_refusal(tmp_path, monkeypatch):
    # the second line of defence: the write creates a new file and renames it into place
    base = tmp_path / "project"
    base.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("theirs")
    os.link(victim, base / "notes.txt")
    monkeypatch.setattr(file_writer, "_refuse_shared_file", lambda path: None)
    write_project_files(base, {"notes.txt": "mine"})
    assert victim.read_text() == "theirs" and (base / "notes.txt").read_text() == "mine"


# ------------------------------------- finding 12: names that differ only by case

def test_scaffold_refuses_tools_that_differ_only_by_case(tmp_path):
    tools = json.dumps([{"name": "fetch", "description": "x", "parameters": []},
                        {"name": "Fetch", "description": "x", "parameters": []}])
    result = json.loads(scaffold_server("my-mcp", "x", tools, output_dir=str(tmp_path)))
    assert result["success"] is False and "ignoring case" in result["error"]
    assert list(tmp_path.iterdir()) == []


def test_add_tool_refuses_a_name_that_differs_only_by_case_from_an_existing_tool(tmp_path):
    project = Path(json.loads(scaffold_server("my-mcp", "x", TOOLS, output_dir=str(tmp_path)))["project_dir"])
    before = sorted(p.name for p in (project / "src" / "my_mcp" / "tools").iterdir())
    result = json.loads(add_tool(str(project), json.dumps({"name": "Fetch", "description": "x", "parameters": []})))
    assert result["success"] is False and "only by letter case" in result["error"]
    assert sorted(p.name for p in (project / "src" / "my_mcp" / "tools").iterdir()) == before
    assert json.loads(add_tool(str(project), json.dumps({"name": "fetch_all", "description": "x", "parameters": []})))["success"] is True
