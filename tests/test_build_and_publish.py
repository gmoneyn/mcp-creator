"""build_package and publish_package: what gets built where, what gets uploaded, and to whom.

`uv` is a stand-in throughout. For a build it writes two archive files into the folder it
is told to use, as the real one does; for a publish it only records the call. No package
is ever built or uploaded by these tests, and the token is a made-up string.
"""

import base64
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

from mcp_creator.services.subprocess_runner import child_environment, run_command
from mcp_creator.tools import build_package as build_module
from mcp_creator.tools import publish_package as publish_module
from mcp_creator.tools.build_package import MANIFEST_NAME, build_package
from mcp_creator.tools.publish_package import PYPI_UPLOAD_URL, TOKEN_VAR, URL_VAR, publish_package

# assembled at run time so that no credential-shaped literal sits in the repository
FAKE_TOKEN = "py" + "pi-" + "AgEIcHlwaS5vcmc+Zm9v/YmFy=" + "Qk9HVVM"
WHEEL, SDIST = "my_mcp-0.1.0-py3-none-any.whl", "my_mcp-0.1.0.tar.gz"


class FakeUv:
    def __init__(self, publish_reply=None, build_ok=True):
        self.calls, self.child_vars = [], []
        self.publish_reply = publish_reply or {}
        self.build_ok = build_ok

    def __call__(self, cmd, cwd=None, env=None, timeout=120):
        self.calls.append(list(cmd))
        self.child_vars.append(None if env is None else dict(env))
        reply = {"success": True, "command": " ".join(cmd), "stdout": "", "stderr": "", "return_code": 0}
        if cmd[:2] == ["uv", "build"]:
            out = Path(cmd[cmd.index("--out-dir") + 1])
            if self.build_ok:
                (out / WHEEL).write_bytes(b"wheel bytes")
                (out / SDIST).write_bytes(b"sdist bytes")
                (out / ".gitignore").write_text("*\n")          # uv leaves one in its output folder
            return reply
        if cmd[:2] == ["uv", "publish"]:
            return reply | self.publish_reply
        raise AssertionError(f"unexpected command: {cmd}")

    def published(self):
        return [c for c in self.calls if c[:2] == ["uv", "publish"]]


@pytest.fixture
def uv(monkeypatch):
    fake = FakeUv()
    monkeypatch.setattr(build_module, "run_command", fake)
    monkeypatch.setattr(publish_module, "run_command", fake)
    monkeypatch.delenv(TOKEN_VAR, raising=False)
    monkeypatch.delenv(URL_VAR, raising=False)
    return fake


def _project(tmp_path, pyproject='[project]\nname = "my-mcp"\n'):
    project = tmp_path / "my-mcp"
    project.mkdir()
    (project / "pyproject.toml").write_text(pyproject)
    return project


def _built(tmp_path, uv, **kw):
    project = _project(tmp_path, **kw)
    assert json.loads(build_package(str(project)))["success"] is True
    return project


# ----------------------------------------------------------------------- build

def test_build_goes_into_a_fresh_folder_inside_the_project_and_is_recorded(tmp_path, uv):
    project = _project(tmp_path)
    result = json.loads(build_package(str(project)))
    assert result["success"] is True and sorted(result["built_files"]) == sorted([WHEEL, SDIST])
    out_dir = Path(uv.calls[0][uv.calls[0].index("--out-dir") + 1])
    assert out_dir.parent == project / "dist" and not out_dir.exists()      # created for this build, gone after
    assert sorted(p.name for p in (project / "dist").iterdir()) == sorted([MANIFEST_NAME, WHEEL, SDIST])
    recorded = json.loads((project / "dist" / MANIFEST_NAME).read_text())["files"]
    assert sorted(e["name"] for e in recorded) == sorted([WHEEL, SDIST])


def test_finding_8_build_refuses_a_dist_that_is_a_symlink(tmp_path, uv):
    project = _project(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (project / "dist").symlink_to(elsewhere, target_is_directory=True)
    result = json.loads(build_package(str(project)))
    assert result["success"] is False and "symbolic link" in result["error"]
    assert uv.calls == [] and list(elsewhere.iterdir()) == []


def test_build_that_produces_nothing_is_a_failure(tmp_path, uv):
    uv.build_ok = False
    result = json.loads(build_package(str(_project(tmp_path))))
    assert result["success"] is False and "produced no" in result["error"]


# --------------------------------------------------- publish: which files are sent

def test_publish_uploads_exactly_the_files_the_build_produced(tmp_path, uv):
    project = _built(tmp_path, uv)
    (project / "dist" / "old_thing-9.9.9-py3-none-any.whl").write_bytes(b"left over from something else")
    result = json.loads(publish_package(str(project), token=FAKE_TOKEN))
    assert result["success"] is True
    sent = uv.published()[0]
    assert sent[:4] == ["uv", "publish", "--publish-url", PYPI_UPLOAD_URL]
    assert sorted(sent[4:]) == sorted(str(project / "dist" / n) for n in (WHEEL, SDIST))
    assert not any("*" in arg for arg in sent)


def test_finding_8_publish_refuses_a_dist_that_is_a_symlink(tmp_path, uv):
    victim = _built(tmp_path / "victim-parent", uv) if (tmp_path / "victim-parent").mkdir() is None else None
    project = _project(tmp_path)
    (project / "dist").symlink_to(victim / "dist", target_is_directory=True)
    result = json.loads(publish_package(str(project), token=FAKE_TOKEN))
    assert result["success"] is False and "symbolic link" in result["error"]
    assert uv.published() == []


def test_publish_refuses_a_dist_that_build_package_did_not_produce(tmp_path, uv):
    project = _project(tmp_path)
    (project / "dist").mkdir()
    (project / "dist" / WHEEL).write_bytes(b"put here by hand")
    result = json.loads(publish_package(str(project), token=FAKE_TOKEN))
    assert result["success"] is False and "build_package" in result["error"]
    assert uv.published() == []


@pytest.mark.parametrize("tamper", ["changed", "symlink", "missing"])
def test_publish_refuses_when_a_built_file_changed_after_the_build(tmp_path, uv, tamper):
    project = _built(tmp_path, uv)
    target = project / "dist" / WHEEL
    if tamper == "changed":
        target.write_bytes(b"something else now")
    else:
        target.unlink()
        if tamper == "symlink":
            other = tmp_path / "other.whl"
            other.write_bytes(b"wheel bytes")                   # same content, different file
            target.symlink_to(other)
    result = json.loads(publish_package(str(project), token=FAKE_TOKEN))
    assert result["success"] is False and "build_package" in result["error"]
    assert uv.published() == []


# -------------------------------------------- publish: where the token may go

def test_token_parameter_is_stripped_and_travels_only_in_the_child_variables(tmp_path, uv):
    project = _built(tmp_path, uv)
    publish_package(str(project), token=f"  {FAKE_TOKEN}\n")
    assert uv.child_vars[-1][TOKEN_VAR] == FAKE_TOKEN
    assert not any(FAKE_TOKEN in arg for arg in uv.published()[0])


@pytest.mark.parametrize("where", ["pyproject", "uv.toml", "variable"])
def test_finding_6_a_token_parameter_is_never_sent_anywhere_but_pypi(tmp_path, uv, monkeypatch, where):
    evil = "https://evil.example/legacy/"
    project = _built(tmp_path, uv, pyproject='[project]\nname = "my-mcp"\n' + (
        f'[tool.uv]\npublish-url = "{evil}"\n' if where == "pyproject" else ""))
    if where == "uv.toml":
        (project / "uv.toml").write_text(f'publish-url = "{evil}"\n')
    if where == "variable":
        monkeypatch.setenv(URL_VAR, evil)
    raw = publish_package(str(project), token=FAKE_TOKEN)
    assert json.loads(raw)["success"] is False and "destination" in raw
    assert uv.published() == [] and FAKE_TOKEN not in raw


def test_project_naming_pypi_itself_is_fine(tmp_path, uv):
    project = _built(tmp_path, uv, pyproject=f'[project]\nname = "my-mcp"\n[tool.uv]\npublish-url = "{PYPI_UPLOAD_URL}"\n')
    assert json.loads(publish_package(str(project), token=FAKE_TOKEN))["success"] is True


def test_owner_url_is_honoured_for_the_owners_own_token_and_passed_explicitly(tmp_path, uv, monkeypatch):
    project = _built(tmp_path, uv)
    monkeypatch.setenv(TOKEN_VAR, FAKE_TOKEN)
    monkeypatch.setenv(URL_VAR, "https://test.pypi.org/legacy/")
    assert json.loads(publish_package(str(project)))["success"] is True
    assert uv.published()[0][2:4] == ["--publish-url", "https://test.pypi.org/legacy/"]
    assert URL_VAR not in uv.child_vars[-1]            # the destination is on the command line only


def test_project_cannot_redirect_the_owners_own_token_either(tmp_path, uv, monkeypatch):
    project = _built(tmp_path, uv, pyproject='[project]\nname = "my-mcp"\n[tool.uv]\npublish-url = "https://evil.example/"\n')
    monkeypatch.setenv(TOKEN_VAR, FAKE_TOKEN)
    assert json.loads(publish_package(str(project)))["success"] is False
    assert uv.published() == []


def test_unreadable_project_configuration_is_refused(tmp_path, uv):
    project = _built(tmp_path, uv)
    (project / "uv.toml").write_text("this is [not toml\n")
    result = json.loads(publish_package(str(project), token=FAKE_TOKEN))
    assert result["success"] is False and uv.published() == []


# -------------------------------------------------- publish: the token never comes back

def _forms(token):
    b64 = lambda s: base64.b64encode(s.encode()).decode()
    url = lambda s: base64.urlsafe_b64encode(s.encode()).decode()
    return {
        "as passed": token,
        "base64": b64(token),
        "base64 of __token__:<token>": b64(f"__token__:{token}"),
        "base64 without padding": b64(f"__token__:{token}").rstrip("="),
        "url-safe base64": url(f"__token__:{token}"),
        "url-encoded": quote(token, safe=""),
    }


@pytest.mark.parametrize("form", sorted(_forms(FAKE_TOKEN)))
@pytest.mark.parametrize("passed_as", ["parameter", "parameter with spaces around it", "variable"])
def test_finding_5_no_spelling_of_the_token_comes_back(tmp_path, monkeypatch, form, passed_as):
    leaked = _forms(FAKE_TOKEN)[form]
    uv = FakeUv(publish_reply={"success": False, "return_code": 2, "stdout": f"sent {leaked}",
                               "stderr": f"error: 403 for Authorization: Basic {leaked} ({leaked})"})
    monkeypatch.setattr(build_module, "run_command", uv)
    monkeypatch.setattr(publish_module, "run_command", uv)
    monkeypatch.delenv(URL_VAR, raising=False)
    monkeypatch.delenv(TOKEN_VAR, raising=False)
    project = _built(tmp_path, uv)
    if passed_as == "variable":
        monkeypatch.setenv(TOKEN_VAR, FAKE_TOKEN)
        raw = publish_package(str(project))
    else:
        raw = publish_package(str(project), token=FAKE_TOKEN if passed_as == "parameter" else f"\t{FAKE_TOKEN}  \n")
    assert leaked not in raw and FAKE_TOKEN not in raw
    assert json.loads(raw)["stderr"].count("[token redacted]") == 2


def test_refusals_never_mention_the_token(tmp_path, uv):
    plain = tmp_path / "plain"
    plain.mkdir()
    unbuilt = _project(tmp_path)
    for folder in (plain, unbuilt, tmp_path / "missing"):
        raw = publish_package(str(folder), token=FAKE_TOKEN)
        assert json.loads(raw)["success"] is False and FAKE_TOKEN not in raw
    assert uv.published() == []


def test_description_recommends_trusted_publishing():
    from mcp_creator.server import mcp

    description = mcp._tool_manager._tools["publish_package"].description
    assert "Trusted Publishing" in description and "visible to the model" in description
    assert "only ever sent to PyPI" in description


def test_whole_flow_on_a_scaffolded_project(tmp_path, uv):
    from mcp_creator.tools.add_tool import add_tool
    from mcp_creator.tools.generate_launchguide import generate_launchguide
    from mcp_creator.tools.scaffold_server import scaffold_server

    tools = json.dumps([{"name": "get_weather", "description": "Get weather", "parameters": []}])
    project = json.loads(scaffold_server("flow-mcp", "x", tools, output_dir=str(tmp_path)))["project_dir"]
    assert json.loads(add_tool(project, json.dumps({"name": "get_forecast", "description": "F", "parameters": []})))["success"] is True
    guide = dict(package_name="flow-mcp", tagline="t", description="d", category="c", features="- f", tags="x")
    assert json.loads(generate_launchguide(project_dir=project, **guide))["success"] is True
    assert json.loads(build_package(project))["success"] is True
    assert uv.calls[0][:3] == ["uv", "build", "--out-dir"]
    assert json.loads(publish_package(project, token=FAKE_TOKEN))["success"] is True


# ------------------------------------------ every child process: no GIT_* variable

def test_finding_6_child_processes_get_no_git_variables(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/somewhere/else/.git")
    monkeypatch.setenv("GIT_WORK_TREE", "/somewhere/else")
    monkeypatch.setenv("GIT_INDEX_FILE", "/somewhere/else/index")
    monkeypatch.setenv("NOT_GIT_RELATED", "kept")
    probe = "import os, json; print(json.dumps(sorted(k for k in os.environ if k.startswith('GIT_') or k == 'NOT_GIT_RELATED')))"
    assert json.loads(run_command([sys.executable, "-c", probe])["stdout"]) == ["NOT_GIT_RELATED"]
    explicit = child_environment({"GIT_DIR": "x", "GIT_CONFIG_GLOBAL": "y", "PATH": os.environ["PATH"], "HOME": "/h"})
    assert sorted(explicit) == ["HOME", "PATH"]
