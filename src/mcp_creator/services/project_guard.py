"""Checks that keep the LLM-callable tools inside a project directory.

These tools take a directory from the model. A model that has read hostile text can be
talked into passing the home directory or an unrelated folder, and the tools then run
`git add .`, push, publish, or write files there. Every check here returns a reason
string when it refuses, so the caller can hand the model a clear message.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path


def same_file(a: str | Path, b: str | Path) -> bool:
    """True when both paths are the SAME directory entry on disk.

    Comparing path strings is not enough: on a case-insensitive filesystem
    `/Users/Me` and `/users/me` are one folder with two spellings.
    """
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _too_broad(path: Path) -> str | None:
    """Reason if `path` is a filesystem root, the home directory, or a parent of it."""
    if path.parent == path or same_file(path, path.anchor or "/"):
        return f"{path} is a filesystem root, not a project directory."
    home = Path.home().resolve()
    if path == home or same_file(path, home):
        return f"{path} is your home directory, not a project directory."
    if any(path == parent or same_file(path, parent) for parent in home.parents):
        return f"{path} contains your home directory, so it is not a project directory."
    return None


def check_project_dir(
    project_dir: str | Path, *, require_gitignore: bool = False
) -> tuple[Path | None, str | None]:
    """Return (resolved_path, None) for a project directory, else (None, reason).

    A project directory exists, is not a filesystem root, the home directory or a
    parent of it, and contains a pyproject.toml. With require_gitignore it must also
    contain a .gitignore, which is never created here.
    """
    project = Path(project_dir).resolve()
    if not project.is_dir():
        return None, f"Project directory not found: {project}"
    reason = _too_broad(project)
    if reason:
        return None, reason
    if not (project / "pyproject.toml").is_file():
        return None, (
            f"{project} has no pyproject.toml, so it is not a Python project directory. "
            "Pass the folder that scaffold_server created."
        )
    if require_gitignore and not (project / ".gitignore").is_file():
        return None, (
            f"{project} has no .gitignore. Refusing to run 'git add .' without one, because "
            "it would stage every file in the folder (including .env and build output). "
            "Add a .gitignore first, then run this again."
        )
    return project, None


def check_new_project_dir(
    output_dir: str | Path, package_name: str
) -> tuple[Path | None, str | None]:
    """Return (resolved_target, None) when output_dir/package_name is a safe place to scaffold.

    The target must be a direct child of output_dir (a package name carrying `..` or a
    path separator is refused) and must not be the home directory or a parent of it.
    """
    out = Path(output_dir).resolve()
    target = (out / package_name).resolve()
    if target.parent != out or target == out:
        return None, (
            f"package_name {package_name!r} would place the project outside {out}. "
            "Use a plain package name with no path separators."
        )
    reason = _too_broad(target)
    if reason:
        return None, reason
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        return None, (
            f"{target} already exists and is not empty. This tool does not overwrite an "
            "existing project: choose another package_name or output_dir."
        )
    return target, None


def check_not_nested_in_repo(project: Path, toplevel: dict) -> str | None:
    """Reason if `project` sits inside ANOTHER git repository's worktree, else None.

    `toplevel` is the result of running `git rev-parse --show-toplevel` in `project`.
    Staging from a folder nested in someone else's repository stages into THAT
    repository. Allowed: the project is the top of its own repository, or there is no
    repository yet. If git cannot say and a `.git` exists somewhere above, refuse.
    """
    if toplevel.get("success") and toplevel.get("stdout", "").strip():
        top = Path(toplevel["stdout"].strip()).resolve()
        if top == project or same_file(top, project):
            return None
        return (
            f"{project} is inside another git repository ({top}). Staging here would add "
            "files to that repository. Move the project out of it, or run git yourself."
        )
    for folder in (project, *project.parents):
        if (folder / ".git").exists():
            return (
                f"git could not tell which repository {project} belongs to, and {folder} "
                f"has a .git entry. Refusing to stage. git said: {toplevel.get('stderr', '')}"
            )
    return None


# Files that usually hold credentials. A NAME match is enough to stop and ask; such a
# file is never opened. This list is shared with the TypeScript scaffolder: change both.
_SECRET_NAMES = {
    ".env", ".netrc", ".npmrc", ".pypirc", ".pgpass", ".htpasswd", ".envrc",
    ".git-credentials", "kubeconfig",
}
_SECRET_GLOBS = (
    ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.p8", "*.ppk", "*.jks", "*.keystore",
    "*.kdbx", "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    "service-account*.json", "*.tfvars", "*.tfstate",
)
# A credentials FILE, by its exact name. Not a prefix: `credentials.py` and
# `credentials-howto.md` are ordinary source and documentation.
_CREDENTIALS_FILE_EXTENSIONS = ("json", "ini", "csv", "yml", "yaml", "txt", "xml")
_SECRET_NAMES |= {"credentials"} | {f"credentials.{ext}" for ext in _CREDENTIALS_FILE_EXTENSIONS}
# matched against the end of the path, so the folder is part of the rule
_SECRET_PATH_SUFFIXES = (".aws/credentials", ".docker/config.json")
_SKIP_DIRS = {".git", "node_modules"}
# A .gitignore that merely exists protects nothing. These two must come back "ignored".
GITIGNORE_MUST_COVER = (".env", ".venv/x")
# A dot-separated part of a file name that marks it as a template meant to be committed:
# `.env.example`, `.env.local.sample`, `service-account.example.json`, `credentials.json.dist`.
TEMPLATE_MARKERS = frozenset({"example", "sample", "template", "dist"})


def _matches_secret_rules(lowered_path: str) -> bool:
    name = lowered_path.rsplit("/", 1)[-1]
    if name in _SECRET_NAMES:
        return True
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in _SECRET_GLOBS):
        return True
    return any(
        lowered_path == suffix or lowered_path.endswith("/" + suffix)
        for suffix in _SECRET_PATH_SUFFIXES
    )


def is_template_name(path: str) -> bool:
    """True for the TEMPLATE variant of a secret-looking name.

    That is a name which stops looking like a secret only because one of its
    dot-separated parts is a template marker: take the marker out and the rest matches
    the secret rules. Such a file is meant to be committed, so its name is allowed, and
    its content is scanned instead.
    """
    lowered = str(path).lower()
    folder, _, name = lowered.rpartition("/")
    parts = name.split(".")
    for index, part in enumerate(parts):
        if part in TEMPLATE_MARKERS and index > 0:
            without = ".".join(parts[:index] + parts[index + 1:])
            if without and _matches_secret_rules(f"{folder}/{without}" if folder else without):
                return True
    return False


def is_secret_like(path: str) -> bool:
    """True when a file's name (or, for two cases, its folder and name) looks like credentials.

    `path` may be a bare name or a POSIX-style relative path. Template variants
    (see is_template_name) are not secrets by name.
    """
    lowered = str(path).lower()
    if is_template_name(lowered):
        return False
    return _matches_secret_rules(lowered)


def find_secret_like_files(project: Path) -> list[str]:
    """Secret-looking files under `project`, as POSIX paths relative to it.

    Only names are looked at; no file is opened. Skips .git, node_modules and
    virtualenvs (any folder holding a pyvenv.cfg). Whether git would ignore a hit is
    the caller's question to put to git.
    """
    found = []
    for root, dirs, files in os.walk(project):
        here = Path(root)
        dirs[:] = [
            d for d in dirs
            if d not in _SKIP_DIRS and not (here / d / "pyvenv.cfg").is_file()
        ]
        for name in files:
            relative = (here / name).relative_to(project).as_posix()
            if is_secret_like(relative):
                found.append(relative)
    return sorted(found)


def check_own_git_dir(project: Path, absolute_git_dir: dict, common_dir: dict) -> str | None:
    """Reason if the repository `project` belongs to does not live in `project/.git`.

    `git rev-parse --show-toplevel` equal to the project is not enough: a linked worktree,
    a submodule checkout and a `.git` FILE pointing elsewhere all report the project as
    the top level while every `git add` and `git commit` changes a repository stored
    somewhere else. So the git directory itself must be the project's own `.git` folder,
    and so must the common directory (which differs for a linked worktree).

    The two dict arguments are the results of `git rev-parse --absolute-git-dir` and
    `git rev-parse --git-common-dir`, run in `project`.
    """
    dot_git = project / ".git"
    if dot_git.is_symlink() or not dot_git.is_dir():
        return (
            f"{project} is not the home of its own git repository: its .git is not a plain "
            "folder (this is what a linked worktree, a submodule checkout or a repository "
            "stored elsewhere looks like). Staging here would change that other repository. "
            "Run git yourself for this folder."
        )
    for label, result in (("git directory", absolute_git_dir), ("common git directory", common_dir)):
        reported = result.get("stdout", "").strip() if result.get("success") else ""
        if not reported:
            return f"git could not report the {label} of {project}, so nothing was staged."
        location = Path(reported)
        if not location.is_absolute():
            location = project / location
        if not same_file(location, dot_git):
            return (
                f"The {label} of {project} is {location}, not its own .git folder. Staging here "
                "would change a repository stored somewhere else. Run git yourself for this folder."
            )
    return None


# ---------------------------------------------------------------- template files
# Template variants of secret-looking names (see is_template_name) are meant to be
# committed, so their NAME is exempt. Their CONTENT is not: a real credential pasted into
# one would be published. Only these template files are ever opened, and a finding
# reports the file and line, never the value.
_CREDENTIAL_PREFIXES = (
    "sk-", "ghp_", "gho_", "github_pat_", "glpat-", "pypi-", "npm_", "xoxb-", "xoxp-",
    "sk_live_", "rk_live_", "mcp_live_",
)
_CREDENTIAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    + "|".join(re.escape(p) for p in sorted(_CREDENTIAL_PREFIXES, key=len, reverse=True))
    + r")([A-Za-z0-9_\-]{16,})"
    r"|(?<![A-Za-z0-9])(?:AKIA|ASIA)([A-Z0-9]{16})(?![A-Za-z0-9])"
)
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_PLACEHOLDER_WORDS = ("your", "example", "placeholder", "changeme", "replace", "xxxx")
_TEMPLATE_READ_LIMIT = 1_000_000


def _looks_live(token_body: str) -> bool:
    """A long token that is not an obvious placeholder (your-key-here, xxxx..., EXAMPLE)."""
    lowered = token_body.lower()
    return len(set(lowered)) >= 6 and not any(word in lowered for word in _PLACEHOLDER_WORDS)


def credential_lines(text: str) -> list[int]:
    """1-based numbers of the lines in `text` that hold something shaped like a live credential."""
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        if _PRIVATE_KEY_RE.search(line):
            hits.append(number)
            continue
        for match in _CREDENTIAL_RE.finditer(line):
            if _looks_live(match.group(1) or match.group(2)):
                hits.append(number)
                break
    return hits


def find_template_files(project: Path) -> list[str]:
    """The exempt template files under `project` (same folders skipped as the name scan)."""
    found = []
    for root, dirs, files in os.walk(project):
        here = Path(root)
        dirs[:] = [
            d for d in dirs
            if d not in _SKIP_DIRS and not (here / d / "pyvenv.cfg").is_file()
        ]
        for name in files:
            relative = (here / name).relative_to(project).as_posix()
            if is_template_name(relative):
                found.append(relative)
    return sorted(found)


def template_credential_locations(project: Path, relative: str) -> list[str]:
    """`file:line` for each credential-shaped value in one template file. Never the value.

    A file that cannot be read, or is too large to read whole, is reported as not
    checked: a partial scan must not pass as a clean one.
    """
    path = project / relative
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read(_TEMPLATE_READ_LIMIT + 1)
    except OSError:
        return [f"{relative} (could not be read, so it could not be checked)"]
    if len(text) > _TEMPLATE_READ_LIMIT:
        return [
            f"{relative} (larger than {_TEMPLATE_READ_LIMIT:,} characters, so it could not be "
            "fully checked; a template file has no reason to be that large)"
        ]
    return [f"{relative}:{number}" for number in credential_lines(text)]
