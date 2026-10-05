"""Initialize git and create a PRIVATE GitHub repo for the MCP server project.

This tool runs `git add .` and pushes, on a folder and with arguments chosen by a model.
So every step is checked before the next one runs, and three things never happen here:
a public repository is never created or pushed to, a secret-looking file is never
committed or pushed (working tree, index and history are all looked at), and a commit is
never pushed anywhere except the one repository this call is about.
"""

from __future__ import annotations

import json
import re

from mcp_creator.services.project_guard import (
    GITIGNORE_MUST_COVER,
    check_not_nested_in_repo,
    check_own_git_dir,
    check_project_dir,
    find_secret_like_files,
    find_template_files,
    is_secret_like,
    template_credential_locations,
)
from mcp_creator.services.subprocess_runner import run_command

# GitHub's own rule for repository names. Anything else (a leading "-" that gh would read
# as a flag, an "owner/name" that would create it somewhere else) is refused.
REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,99}$")


def _make_public_hint(repo: str) -> str:
    return (
        "The repository is private. This tool never creates a public repository: making it "
        "public is your own step (MCP Marketplace needs a public repo for a free listing). "
        f"Run: gh repo edit {repo} --visibility public --accept-visibility-change-consequences"
    )


def _by_hand(slug: str) -> str:
    return (
        "To push this project there yourself, run in the project folder: "
        f"git remote add origin https://github.com/{slug}.git  and then  git push -u origin HEAD"
    )


def _fail(error: str, **extra) -> str:
    return json.dumps({"success": False, "error": error, **extra})


def _secret_paths(nul_separated: str) -> list[str]:
    return sorted({p for p in nul_separated.split("\0") if p and is_secret_like(p)})


def setup_github(
    project_dir: str,
    repo_name: str,
    description: str = "",
    private: bool = True,
) -> str:
    """Initialize a git repo, create a PRIVATE GitHub repo, and push the project.

    Requires the `gh` CLI to be installed and authenticated.

    Args:
        project_dir: Absolute path to the project root.
        repo_name: GitHub repo name (e.g. "my-weather-mcp").
        description: One-line repo description.
        private: Kept for compatibility. The repository is ALWAYS created private,
                 whatever is passed here; the result explains how the owner makes it
                 public.

    Returns:
        JSON string with repo URL and next steps.
    """
    if not isinstance(repo_name, str) or not REPO_NAME_RE.fullmatch(repo_name) or repo_name.endswith(".git"):
        return _fail(
            f"Invalid repo_name {repo_name!r}: use letters, digits, '.', '-' or '_', not "
            "starting with '-' or '.', with no owner prefix and no slash."
        )

    # Refuse anything that is not a project directory BEFORE running git or gh in it:
    # `git add .` followed by a push in the wrong folder publishes whatever is there.
    project, reason = check_project_dir(project_dir, require_gitignore=True)
    if project is None:
        return _fail(reason)

    def git(*args: str, timeout: int = 120) -> dict:
        return run_command(["git", *args], cwd=project, timeout=timeout)

    def gh(*args: str, timeout: int = 60) -> dict:
        return run_command(["gh", *args], cwd=project, timeout=timeout)

    # Ask git where the repository starts. It must start HERE (or not exist yet):
    # `git add .` inside someone else's worktree stages into their repository.
    toplevel = git("rev-parse", "--show-toplevel")
    reason = check_not_nested_in_repo(project, toplevel)
    if reason:
        return _fail(reason)
    # A repository that reports this folder as its top level can still be STORED elsewhere
    # (linked worktree, submodule, a .git file). Its git directory must be project/.git.
    dot_git = project / ".git"
    if toplevel["success"] or dot_git.exists() or dot_git.is_symlink():
        reason = check_own_git_dir(
            project, git("rev-parse", "--absolute-git-dir"), git("rev-parse", "--git-common-dir")
        )
        if reason:
            return _fail(reason)

    # 1. gh must be usable, and we need to know whose account this is
    if not gh("auth", "status")["success"]:
        return json.dumps({
            "success": False,
            "error": "GitHub CLI (gh) is not installed or not authenticated.",
            "next_steps": ["Install gh: https://cli.github.com/", "Then run: gh auth login"],
        })
    whoami = gh("api", "user", "--jq", ".login")
    username = whoami["stdout"].strip()
    if not whoami["success"] or not username:
        return _fail(f"Could not find out which GitHub account gh is using: {whoami['stderr']}")
    slug = f"{username}/{repo_name}"

    # 1b. This tool creates NEW repositories. It does not adopt one that already exists
    #     (whatever its visibility), and it does not repoint or push to a remote the
    #     project already has. Both are checked before anything in the project is touched.
    view = gh("repo", "view", slug, "--json", "visibility,url,sshUrl")
    if view["success"]:
        try:
            visibility_now = str(json.loads(view["stdout"])["visibility"]).upper()
        except (ValueError, KeyError, TypeError):
            visibility_now = "UNKNOWN"
        return _fail(
            f"https://github.com/{slug} already exists (visibility: {visibility_now}). This tool "
            "creates new repositories and does not push to an existing one. Nothing was changed. "
            + ("That repository is not private, so pushing there publishes the code. "
               if visibility_now != "PRIVATE" else "")
            + _by_hand(slug)
        )
    origin = git("remote", "get-url", "origin")
    if origin["success"] and origin["stdout"].strip():
        return _fail(
            f"This project already has a remote named origin ({origin['stdout'].strip()}). This "
            "tool creates a new repository and would have to point origin at it. Nothing was "
            "changed. Push to that remote yourself, or remove or rename it and run this again."
        )

    # 2. git init (if not already a repo)
    if not git("rev-parse", "--git-dir")["success"]:
        init = git("init")
        if not init["success"]:
            return _fail(f"git init failed: {init['stderr']}")

    # 3. The .gitignore has to WORK, not merely exist: ask git about two paths that must
    #    never be committed. (--no-index: this question is about the ignore rules only.)
    uncovered = [
        path for path in GITIGNORE_MUST_COVER
        if git("check-ignore", "-q", "--no-index", "--", path)["return_code"] != 0
    ]
    if uncovered:
        return _fail(
            "The project's .gitignore does not ignore " + " or ".join(uncovered)
            + ", so `git add .` could stage secrets or a whole virtualenv. Add `.env` and "
            "`.venv/` to .gitignore, then run this again. Nothing was staged."
        )

    # 4. Working tree: refuse a secret-looking file that git does not ignore. Asked WITH
    #    the index, so a file that is already tracked counts as not ignored.
    exposed = [
        f for f in find_secret_like_files(project)
        if git("check-ignore", "-q", "--", f)["return_code"] != 0
    ]
    if exposed:
        return _fail(
            "Refusing to stage files that look like secrets and are not ignored by git: "
            + ", ".join(exposed)
            + ". If one is a real secret, add it to .gitignore or remove it. If it is an ordinary "
            "file that only has a secret-looking name, rename it. Then run this again. "
            "Nothing was staged.",
            secret_like_files=exposed,
        )

    #    Template files (NAME.example, NAME.sample, ...) are exempt by NAME because they are meant
    #    to be committed. Their content is read here, and only here, for values shaped like
    #    live credentials. The refusal names file and line, never the value.
    leaked = [
        location
        for template in find_template_files(project)
        if git("check-ignore", "-q", "--", template)["return_code"] != 0
        for location in template_credential_locations(project, template)
    ]
    if leaked:
        return _fail(
            "Refusing to stage: a template file holds what looks like a live credential at "
            + ", ".join(leaked)
            + ". Replace it with a placeholder (and rotate it if it is real), then run this "
            "again. Nothing was staged.",
            credential_locations=leaked,
        )

    # 5. History: a push sends every reachable commit, so a secret that was committed once
    #    and removed later would still be published.
    any_commit = git("rev-list", "--all", "--max-count=1")
    if not any_commit["success"]:
        return _fail(f"Could not read the repository's history, so nothing was pushed: {any_commit['stderr']}")
    if any_commit["stdout"].strip():
        history = git("log", "--all", "--name-only", "-z", "--pretty=format:")
        if not history["success"]:
            return _fail(f"Could not list the files in the repository's history: {history['stderr']}")
        in_history = _secret_paths(history["stdout"].replace("\n", "\0"))
        if in_history:
            return _fail(
                "Refusing to push: the repository's history contains files that look like "
                "secrets: " + ", ".join(in_history) + ". Removing a file later does not remove "
                "it from earlier commits. Rewrite the history (or start a fresh repository) "
                "and rotate those credentials, then run this again. (A committed template is "
                "fine under a template name such as NAME.example.) Nothing was pushed.",
                secret_like_files=in_history,
            )

    # 6. Stage, then look at the WHOLE index (not only what this call added, and with no
    #    folder skipped) before anything is committed.
    add = git("add", ".")
    if not add["success"]:
        return _fail(f"git add failed, so nothing was committed: {add['stderr']}")
    index = git("ls-files", "-z")
    if not index["success"]:
        return _fail(f"Could not list the staged files, so nothing was committed: {index['stderr']}")
    staged_secrets = _secret_paths(index["stdout"])
    if staged_secrets:
        unstage = git("rm", "--cached", "-q", "--", *staged_secrets)
        return _fail(
            "Refusing to commit: files that look like secrets are in the index"
            + (" and have been unstaged: " if unstage["success"] else " (and could NOT be unstaged): ")
            + ", ".join(staged_secrets)
            + ". If one is a real secret, add it to .gitignore or remove it. If it is an ordinary "
            "file that only has a secret-looking name, rename it. Then run this again.",
            secret_like_files=staged_secrets,
        )

    # 7. Commit when there is something to commit
    has_head = git("rev-parse", "--verify", "-q", "HEAD")["success"]
    staged_changes = git("diff", "--cached", "--quiet")["return_code"] != 0
    if staged_changes:
        commit = git("commit", "-m", "Initial commit — scaffolded with mcp-creator")
        if not commit["success"]:
            return _fail(f"git commit failed, so nothing was pushed: {commit['stderr'] or commit['stdout']}")
    elif not has_head:
        return _fail("There is nothing to commit in this project, so there is nothing to push.")

    # 8. Create it. Always private. (That no repository of this name exists yet, and that
    #    this project has no origin, was established in step 1b.)
    create_args = ["repo", "create", repo_name, "--private"]
    if description:
        create_args += ["--description", description]
    created = gh(*create_args)
    if not created["success"]:
        return json.dumps({
            "success": False,
            "error": f"Failed to create GitHub repo: {created['stderr']}",
            "next_steps": [
                "Check that gh is authenticated: gh auth status",
                "If the repository exists already, this tool will not push to it: " + _by_hand(slug),
            ],
        })
    view = gh("repo", "view", slug, "--json", "visibility,url,sshUrl")
    try:
        info = json.loads(view["stdout"]) if view["success"] else None
        visibility_now = str(info["visibility"]).upper()
    except (ValueError, KeyError, TypeError):
        return _fail(f"{slug} was created, but gh could not describe it afterwards, so nothing was pushed.")
    if visibility_now != "PRIVATE":
        return _fail(f"{slug} was created but gh reports it as {visibility_now}, not PRIVATE. Nothing was pushed.")

    https_url, ssh_url = str(info.get("url") or ""), str(info.get("sshUrl") or "")
    protocol = gh("config", "get", "git_protocol", "-h", "github.com")
    push_url = ssh_url if (protocol["success"] and protocol["stdout"].strip() == "ssh" and ssh_url) else https_url
    if not push_url:
        return _fail(f"gh did not report a URL for {slug}, so nothing was pushed.")

    added = git("remote", "add", "origin", push_url)
    if not added["success"]:
        return _fail(f"git remote add failed, so nothing was pushed: {added['stderr']}")

    # 9. Push to the URL itself, never to a remote name that could mean something else
    push = git("push", "-u", push_url, "HEAD", timeout=120)
    if not push["success"]:
        return _fail(
            f"git push to {push_url} failed: {push['stderr'] or push['stdout']}",
            repo_url=https_url,
            next_steps=[
                "The repository was created and is private, but the code was not pushed. "
                "Push it yourself from the project folder: git push -u origin HEAD"
            ],
        )

    asked_public = private is False
    return json.dumps({
        "success": True,
        "repo_url": https_url,
        "private": True,
        "next_steps": [
            f"GitHub repo created (private): {https_url}",
            "Use generate_launchguide with this URL as the docs_url for marketplace submission.",
            ("You asked for a public repository. " if asked_public else "") + _make_public_hint(slug),
        ],
    })
