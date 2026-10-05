"""What the scaffolder refuses to overwrite, refuses to push, and how it writes hostile text.

Three groups:
- existing work is never overwritten (scaffold into a non-empty folder, add_tool over a tool)
- setup_github never stages a secret-looking file that git does not ignore (asked of real git)
- names are validated before generation, and free text is escaped where it is written
"""

import ast
import json
import os
import tomllib
from pathlib import Path

import pytest

from mcp_creator.services import codegen
from mcp_creator.services.subprocess_runner import run_command as real_run_command
from mcp_creator.tools import setup_github as github_module
from mcp_creator.tools.add_tool import add_tool
from mcp_creator.tools.scaffold_server import scaffold_server
from mcp_creator.tools.setup_github import setup_github

TOOLS = json.dumps([{
    "name": "get_weather",
    "description": "Get weather",
    "parameters": [{"name": "city", "type": "string", "required": True, "description": "City"}],
}])

# Quotes of every kind, a triple quote, a backslash, a newline, and code that would run
# if any of them ended the literal early.
HOSTILE = 'say "hi" and \'bye\' """triple""" back\\slash {brace}\nimport os; os.system("echo PWNED") # "'
HOSTILE_ONE_LINE = HOSTILE.replace("\n", " ")


# ------------------------------------------------- never overwrite existing work

def test_scaffold_refuses_existing_non_empty_directory(tmp_path):
    target = tmp_path / "my-mcp"
    target.mkdir()
    (target / "notes.txt").write_text("mine")
    result = json.loads(scaffold_server("my-mcp", "x", TOOLS, output_dir=str(tmp_path)))
    assert result["success"] is False
    assert str(target) in result["error"] and "not empty" in result["error"]
    assert sorted(p.name for p in target.iterdir()) == ["notes.txt"]


def test_scaffold_twice_keeps_the_first_project(tmp_path):
    first = json.loads(scaffold_server("my-mcp", "x", TOOLS, output_dir=str(tmp_path)))
    assert first["success"] is True
    service = Path(first["project_dir"]) / "src" / "my_mcp" / "services" / "get_weather_service.py"
    service.write_text("# my real implementation\n")
    second = json.loads(scaffold_server("my-mcp", "x", TOOLS, output_dir=str(tmp_path)))
    assert second["success"] is False
    assert service.read_text() == "# my real implementation\n"


def test_scaffold_into_existing_empty_directory_is_allowed(tmp_path):
    (tmp_path / "my-mcp").mkdir()
    result = json.loads(scaffold_server("my-mcp", "x", TOOLS, output_dir=str(tmp_path)))
    assert result["success"] is True


def test_add_tool_refuses_to_replace_an_existing_tool(tmp_path):
    project = Path(json.loads(scaffold_server("my-mcp", "x", TOOLS, output_dir=str(tmp_path)))["project_dir"])
    service = project / "src" / "my_mcp" / "services" / "get_weather_service.py"
    service.write_text("# my real implementation\n")
    server_before = (project / "src" / "my_mcp" / "server.py").read_text()
    again = json.dumps({"name": "get_weather", "description": "x", "parameters": []})
    result = json.loads(add_tool(str(project), again))
    assert result["success"] is False and "already exists" in result["error"]
    assert service.read_text() == "# my real implementation\n"
    assert (project / "src" / "my_mcp" / "server.py").read_text() == server_before


def test_add_tool_still_adds_a_new_tool(tmp_path):
    project = Path(json.loads(scaffold_server("my-mcp", "x", TOOLS, output_dir=str(tmp_path)))["project_dir"])
    new = json.dumps({"name": "get_forecast", "description": "x", "parameters": []})
    result = json.loads(add_tool(str(project), new))
    assert result["success"] is True and result["server_updated"] is True


# ------------------------------------------------ setup_github and secret files


# --------------------------------------------- names are validated before generation

@pytest.mark.parametrize("name", [
    "../x", "a/b", "my pkg", "1abc", "a" * 65, "class", 'x"; import os #', "my.pkg", "", "ends-",
])
def test_scaffold_refuses_invalid_package_name(tmp_path, name):
    result = json.loads(scaffold_server(name, "x", TOOLS, output_dir=str(tmp_path)))
    assert result["success"] is False and "package_name" in result["error"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["get weather", "1tool", "def", "x(): pass\nimport os", "a-b", "", "a" * 65])
def test_scaffold_refuses_invalid_tool_name(tmp_path, name):
    tools = json.dumps([{"name": name, "description": "x", "parameters": []}])
    result = json.loads(scaffold_server("my-mcp", "x", tools, output_dir=str(tmp_path)))
    assert result["success"] is False and "tool name" in result["error"]
    assert list(tmp_path.iterdir()) == []


def test_scaffold_refuses_invalid_parameter_and_env_var_names(tmp_path):
    bad_param = json.dumps([{"name": "t", "description": "x", "parameters": [
        {"name": "city: str = __import__('os').getcwd()", "type": "string"},
    ]}])
    result = json.loads(scaffold_server("my-mcp", "x", bad_param, output_dir=str(tmp_path)))
    assert result["success"] is False and "parameter name" in result["error"]
    bad_env = json.dumps([{"name": "A=1\nB", "description": "x"}])
    result = json.loads(scaffold_server("my-mcp", "x", TOOLS, output_dir=str(tmp_path), env_vars=bad_env))
    assert result["success"] is False and "env var name" in result["error"]
    assert list(tmp_path.iterdir()) == []


def test_add_tool_refuses_invalid_tool_name(tmp_path):
    project = json.loads(scaffold_server("my-mcp", "x", TOOLS, output_dir=str(tmp_path)))["project_dir"]
    result = json.loads(add_tool(project, json.dumps({"name": "x; import os", "description": "x"})))
    assert result["success"] is False and "tool name" in result["error"]


@pytest.mark.parametrize("name", ["my-weather-mcp", "a", "Pkg_2-x"])
def test_scaffold_accepts_ordinary_package_names(tmp_path, name):
    assert json.loads(scaffold_server(name, "x", TOOLS, output_dir=str(tmp_path)))["success"] is True


# ----------------------------------- free text is escaped for where it is written

def _tool(description="Get weather", default="metric", returns="JSON"):
    return {
        "name": "get_weather", "description": description, "returns": returns,
        "parameters": [
            {"name": "city", "type": "string", "required": True},
            {"name": "units", "type": "string", "required": False, "default": default},
        ],
    }


def _shape(source):
    """Statement types of a module and of its functions: changes if text became code."""
    tree = ast.parse(source)
    return [type(n).__name__ for n in ast.walk(tree) if isinstance(n, ast.stmt)]


def test_hostile_description_stays_inside_the_string_literal():
    source = codegen.render_server("my-mcp", [_tool(description=HOSTILE)])
    assert _shape(source) == _shape(codegen.render_server("my-mcp", [_tool()]))
    decorators = [d for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) for d in n.decorator_list]
    described = [kw.value for d in decorators if isinstance(d, ast.Call) for kw in d.keywords if kw.arg == "description"]
    assert [ast.literal_eval(v) for v in described] == [HOSTILE]


def test_hostile_description_in_add_tool_registration():
    source = "class mcp:\n    tool = staticmethod(lambda **kw: (lambda f: f))\n" + codegen.render_add_tool_registration(_tool(description=HOSTILE))
    fn = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef))
    assert ast.literal_eval(fn.decorator_list[0].keywords[0].value) == HOSTILE


@pytest.mark.parametrize("render", [
    lambda t: codegen.render_server("my-mcp", [t]),
    lambda t: codegen.render_tool_module("my-mcp", t),
    lambda t: codegen.render_service_module(t),
    lambda t: "class mcp:\n    tool = staticmethod(lambda **kw: (lambda f: f))\n" + codegen.render_add_tool_registration(t),
])
def test_hostile_default_value_stays_a_string(render):
    source = render(_tool(default=HOSTILE))
    assert _shape(source) == _shape(render(_tool()))
    defaults = [
        ast.literal_eval(d) for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)
        for d in n.args.defaults
    ]
    assert defaults == [HOSTILE]


def test_hostile_text_in_docstrings_keeps_its_exact_value():
    tool_src = codegen.render_tool_module("my-mcp", _tool(description=HOSTILE, returns=HOSTILE))
    assert _shape(tool_src) == _shape(codegen.render_tool_module("my-mcp", _tool()))
    tree = ast.parse(tool_src)
    assert ast.get_docstring(tree, clean=False) == HOSTILE + "."
    fn_doc = ast.get_docstring(next(n for n in tree.body if isinstance(n, ast.FunctionDef)), clean=False)
    assert fn_doc == f"{HOSTILE}\n\n    Returns:\n        {HOSTILE}\n    "

    service_src = codegen.render_service_module(_tool(description=HOSTILE))
    assert _shape(service_src) == _shape(codegen.render_service_module(_tool()))
    tree = ast.parse(service_src)
    assert ast.get_docstring(tree, clean=False) == HOSTILE + " — service layer."
    cls_doc = ast.get_docstring(next(n for n in tree.body if isinstance(n, ast.ClassDef)), clean=False)
    assert cls_doc.startswith(HOSTILE + ".\n")


def test_hostile_project_description_is_one_toml_string():
    for paid in (False, True):
        data = tomllib.loads(codegen.render_pyproject("my-mcp", HOSTILE, paid=paid))
        assert data["project"]["description"] == HOSTILE
        assert set(data["project"]["scripts"]) == {"my-mcp"}


def test_hostile_env_var_description_cannot_add_a_line():
    text = codegen.render_env_example([{"name": "API_KEY", "description": "the key\nEVIL=1\rALSO=2", "required": True}])
    assignments = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert assignments == ["API_KEY="]


def test_scaffolded_project_with_hostile_text_parses(tmp_path):
    tools = json.dumps([_tool(description=HOSTILE, default=HOSTILE, returns=HOSTILE)])
    result = json.loads(scaffold_server("my-mcp", HOSTILE_ONE_LINE, tools, output_dir=str(tmp_path)))
    assert result["success"] is True
    project = Path(result["project_dir"])
    for path in project.rglob("*.py"):
        ast.parse(path.read_text(), filename=str(path))
    assert tomllib.loads((project / "pyproject.toml").read_text())["project"]["description"] == HOSTILE_ONE_LINE
    assert not list(tmp_path.rglob("PWNED*"))
