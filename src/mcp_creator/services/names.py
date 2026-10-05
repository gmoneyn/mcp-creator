"""Validate the names that are interpolated into generated source as identifiers.

Package, tool, parameter and env-var names become module names, function names, file
names and variable names in the generated project. They are checked BEFORE anything is
generated, so a name can never carry code or a path, and can never collide with a name
the generated code already uses. Free text (descriptions) is a different case: it is
escaped where it is written, in codegen.

The reserved names are NOT a hand-written list. `reserved_names()` renders the templates
with a probe tool and reads the result with `ast`, so a template that starts binding a
new name reserves it automatically.
"""

from __future__ import annotations

import ast
import builtins
import functools
import importlib.metadata
import keyword
import re
import sys

PACKAGE_RE = re.compile(r"^[A-Za-z](?:[A-Za-z0-9_-]{0,62}[A-Za-z0-9])?$")
# Tool and parameter names start with a LETTER. Every private name the templates bind
# starts with an underscore, so the two sets cannot meet. (The MCP SDK also rejects a
# parameter whose name starts with an underscore.)
IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

# Rejected by the SDK itself when the tool is registered. Observed on mcp 2.3.0 by
# registering a function with that parameter; not derivable from the templates.
SDK_REJECTED_PARAMS = frozenset({"model_config"})
# Top-level packages of the SDK the generated project installs that the scaffolder's own
# environment (mcp 1.x) cannot see. Observed in a generated project's venv on mcp 2.3.0.
SDK_V2_TOP_LEVELS = frozenset({"mcp", "mcp_types"})

_PROBE_PACKAGE = "zzprobepkg"
_PROBE_TOOL = "zzprobetool"
_PROBE_PARAMS = ("zzreq", "zzopt")


def _module_bindings(tree: ast.Module) -> set[str]:
    """Names bound at module level: imports, assignments, functions, classes."""
    bound: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            bound.update(n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return bound


def _builtins_used(tree: ast.AST) -> set[str]:
    return {
        n.id for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and hasattr(builtins, n.id)
    }


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _names_in_functions_using(tree: ast.AST, wanted: set[str], *, as_argument: bool) -> set[str]:
    """Every name read, written or taken as an argument inside the functions that either
    take one of `wanted` as an argument or (as_argument=False) read one of them."""
    names: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = {a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]}
        body_names = {n.id for stmt in fn.body for n in ast.walk(stmt) if isinstance(n, ast.Name)}
        touches = (args & wanted) if as_argument else (body_names & wanted)
        if touches:
            names |= args | body_names
    return names


def _dependency_top_levels(root_dists: tuple[str, ...]) -> set[str]:
    """Top-level import names of the given distributions and everything they depend on,
    as installed next to the scaffolder. A project named like one of these shadows it."""
    def norm(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    tops_by_dist: dict[str, set[str]] = {}
    for top, dists in importlib.metadata.packages_distributions().items():
        for dist in dists:
            tops_by_dist.setdefault(norm(dist), set()).add(top)
    seen: set[str] = set()
    todo = [norm(d) for d in root_dists]
    while todo:
        dist = todo.pop()
        if dist in seen:
            continue
        seen.add(dist)
        try:
            requirements = importlib.metadata.requires(dist) or []
        except importlib.metadata.PackageNotFoundError:
            continue
        for req in requirements:
            # optional extras are not installed with the generated project, except the
            # `cli` extra of the SDK itself, which the generated pyproject asks for
            marker = req.partition(";")[2]
            if "extra" in marker and not (dist == "mcp" and re.search(r"extra\s*==\s*['\"]cli['\"]", marker)):
                continue
            todo.append(norm(re.split(r"[\s;\[<>=!~(]", req.strip(), maxsplit=1)[0]))
    return set().union(*(tops_by_dist.get(d, set()) for d in seen)) if seen else set()


@functools.lru_cache(maxsize=1)
def reserved_names() -> dict[str, frozenset[str]]:
    """Names a tool, a parameter or a package may not use, derived from the templates.

    tool:     bound at module level, or used as a builtin, in a generated module where the
              tool's own name is also bound at module level (server.py, tools/<tool>.py,
              tests/test_<tool>.py), plus the locals of any function that calls the tool
    param:    every other name inside a generated function that takes the tool's parameters
    package:  modules the generated code imports, the standard library, and the SDK with
              its dependencies (a package of the same name shadows them or is shadowed)
    """
    from mcp_creator.services import codegen  # codegen does not import this module

    # one parameter per type the generator knows, so every annotation it can emit is seen,
    # plus the defaults that are written as calls rather than literals
    typed = [
        {"name": f"zzt{i}", "type": type_name, "required": False, "default": default}
        for i, (type_name, default) in enumerate(
            [(t, None) for t in codegen.TYPE_MAP] + [("float", float("inf")), ("float", float("nan"))]
        )
    ]
    probe = {
        "name": _PROBE_TOOL, "description": "d", "returns": "r",
        "parameters": [
            {"name": _PROBE_PARAMS[0], "type": "string", "required": True},
            {"name": _PROBE_PARAMS[1], "type": "string", "required": False, "default": "x"},
            *typed,
        ],
    }
    servers = [
        codegen.render_server(_PROBE_PACKAGE, [probe], paid=paid, hosting=hosting)
        for paid in (False, True) for hosting in ("local", "remote")
    ]
    # add_tool injects this into an existing server.py, so it shares that module's names
    servers.append(servers[-1] + "\n" + codegen.render_add_tool_registration(probe))
    tool_modules = [*servers, codegen.render_tool_module(_PROBE_PACKAGE, probe),
                    codegen.render_test_tool(_PROBE_PACKAGE, probe)]
    all_sources = [*tool_modules, codegen.render_service_module(probe),
                   codegen.render_test_server(_PROBE_PACKAGE, [probe]),
                   codegen.render_transport(_PROBE_PACKAGE)]

    own = {_PROBE_TOOL, *_PROBE_PARAMS, *(p["name"] for p in typed)}
    tool: set[str] = set()
    param: set[str] = set()
    imports: set[str] = set()
    for source in tool_modules:
        tree = ast.parse(source)
        tool |= _module_bindings(tree) | _builtins_used(tree)
        tool |= _names_in_functions_using(tree, {_PROBE_TOOL}, as_argument=False)
    for source in all_sources:
        tree = ast.parse(source)
        param |= _names_in_functions_using(tree, set(_PROBE_PARAMS), as_argument=True)
        imports |= _import_roots(tree)
    # names that exist only because of the probe itself are not reservations
    probe_made = {n for n in tool | param if _PROBE_TOOL in n} | own
    return {
        "tool": frozenset(tool - probe_made),
        "param": frozenset(param - probe_made),
        "package": frozenset(
            (imports - {_PROBE_PACKAGE})
            | set(sys.stdlib_module_names)
            | _dependency_top_levels(("mcp",))
            | SDK_V2_TOP_LEVELS
        ),
    }


def check_package_name(package_name: object) -> str | None:
    """Reason the package name is unusable, or None."""
    if not isinstance(package_name, str) or not PACKAGE_RE.fullmatch(package_name):
        return (
            f"Invalid package_name {package_name!r}: use 1 to 64 characters, letters, digits, "
            "'-' or '_', starting with a letter and ending with a letter or digit."
        )
    module = package_name.replace("-", "_")
    if keyword.iskeyword(module):
        return f"Invalid package_name {package_name!r}: its module name is a Python keyword."
    if module in reserved_names()["package"] or module.lower() in reserved_names()["package"]:
        return (
            f"Invalid package_name {package_name!r}: its module name '{module}' is already a "
            "module the generated server imports (the Python standard library, the MCP SDK or "
            "one of its dependencies), so the project would shadow it or be shadowed by it. "
            "Pick a more specific name, for example with a suffix such as '-mcp'."
        )
    return None


def _check_identifier(kind: str, value: object) -> str | None:
    if not isinstance(value, str) or not IDENT_RE.fullmatch(value):
        return (
            f"Invalid {kind} {value!r}: use 1 to 64 characters, letters, digits or '_', "
            "starting with a letter."
        )
    if keyword.iskeyword(value):
        return f"Invalid {kind} {value!r}: it is a Python keyword."
    return None


def check_tool_def(tool: object) -> str | None:
    """Reason a tool definition's names are unusable, or None."""
    if not isinstance(tool, dict) or "name" not in tool:
        return "Each tool must be an object with a 'name'."
    name = tool["name"]
    reason = _check_identifier("tool name", name)
    if reason:
        return reason
    reserved = reserved_names()
    if name in reserved["tool"]:
        return (
            f"Invalid tool name {name!r}: the generated server already uses that name "
            "(reserved name rule), so a tool with it would replace it. Pick another name."
        )
    seen: set[str] = set()
    for param in tool.get("parameters", []) or []:
        if not isinstance(param, dict) or "name" not in param:
            return f"Tool {name!r}: each parameter must be an object with a 'name'."
        pname = param["name"]
        reason = _check_identifier(f"parameter name in tool {name!r}", pname)
        if reason:
            return reason
        if pname in reserved["param"] or pname in SDK_REJECTED_PARAMS:
            return (
                f"Invalid parameter name {pname!r} in tool {name!r}: the generated code or the "
                "MCP SDK already uses that name (reserved name rule). Pick another name."
            )
        if pname in seen:
            return (
                f"Invalid parameters in tool {name!r}: {pname!r} appears more than once "
                "(parameter names must be unique within a tool)."
            )
        seen.add(pname)
    return None


def check_tool_defs(tools: object) -> str | None:
    if not isinstance(tools, list):
        return "tools must be a JSON list of tool definitions."
    seen: dict[str, str] = {}
    for tool in tools:
        reason = check_tool_def(tool)
        if reason:
            return reason
        # files are named after tools, and some filesystems ignore case
        key = tool["name"].casefold()
        if key in seen:
            return (
                f"Invalid tools: {tool['name']!r} and {seen[key]!r} are the same name "
                "(tool names must be unique, ignoring case), so one would overwrite the other."
            )
        seen[key] = tool["name"]
    return None


def check_env_vars(env_vars: object) -> str | None:
    """Reason an env-var definition list is unusable, or None."""
    if env_vars is None:
        return None
    if not isinstance(env_vars, list):
        return "env_vars must be a JSON list."
    for var in env_vars:
        name = var.get("name") if isinstance(var, dict) else None
        if not isinstance(name, str) or not ENV_RE.fullmatch(name):
            return (
                f"Invalid env var name {name!r}: use letters, digits or '_', "
                "not starting with a digit."
            )
    return None
