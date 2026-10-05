"""setup_github, exercised the way an independent review attacked it.

git is REAL here (in pytest's temp directory, with a made-up HOME so no developer
configuration leaks in). `gh` is a stand-in that knows one account and a set of
repositories, each backed by a local bare repository, so a push really happens and we
can look at where the commit landed. Nothing in this file talks to GitHub.
"""

import json
import os
from pathlib import Path

import pytest

from mcp_creator.services.subprocess_runner import run_command as real_run_command
from mcp_creator.tools import setup_github as github_module
from mcp_creator.tools.setup_github import setup_github

GOOD_IGNORE = ".env\n.venv/\ndist/\n"


def real_git(folder, *args):
    return real_run_command(["git", *args], cwd=folder)


class Harness:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        (self.home / ".gitconfig").write_text(
            "[user]\n\tname = Test\n\temail = test@example.invalid\n[init]\n\tdefaultBranch = main\n"
        )
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        self.github = tmp_path / "github"
        self.github.mkdir()
        self.login = "octocat"
        self.repos: dict[str, dict] = {}
        self.gh_calls: list[list[str]] = []
        self.git_calls: list[list[str]] = []
        self.fail: dict[tuple, str] = {}        # command prefix -> stderr of a simulated failure
        monkeypatch.setattr(github_module, "run_command", self)

    # ---- the stand-in for run_command -------------------------------------------------
    def __call__(self, cmd, cwd=None, env=None, timeout=120):
        def reply(ok, out="", err=""):
            return {"success": ok, "command": " ".join(cmd), "stdout": out, "stderr": err, "return_code": 0 if ok else 1}
        for prefix, stderr in self.fail.items():
            if tuple(cmd[:len(prefix)]) == prefix:
                return reply(False, err=stderr)
        if cmd[0] != "gh":
            self.git_calls.append(list(cmd))
            return real_run_command(cmd, cwd=cwd, env=env, timeout=timeout)
        self.gh_calls.append(list(cmd))
        if cmd[1:3] == ["auth", "status"]:
            return reply(True)
        if cmd[1:3] == ["api", "user"]:
            return reply(True, self.login)
        if cmd[1:3] == ["config", "get"]:
            return reply(True, "https")
        if cmd[1:3] == ["repo", "view"]:
            name = cmd[3].split("/", 1)[1]
            if name in self.repos:
                return reply(True, json.dumps(self.repos[name]))
            return reply(False, err="GraphQL: Could not resolve to a Repository with that name.")
        if cmd[1:3] == ["repo", "create"]:
            name = cmd[3]
            if name in self.repos:
                return reply(False, err="GraphQL: Name already exists on this account")
            self.add_repo(name, "PUBLIC" if "--public" in cmd else "PRIVATE")
            return reply(True)
        raise AssertionError(f"unexpected gh call: {cmd}")

    # ---- the pretend GitHub ---------------------------------------------------------------
    def add_repo(self, name, visibility="PRIVATE", url=None):
        bare = self.github / f"{name}.git"
        if url is None:
            assert real_run_command(["git", "init", "--bare", "-q", str(bare)])["success"]
            url = str(bare)
        self.repos[name] = {"visibility": visibility, "url": url, "sshUrl": url}
        return bare

    def created(self):
        return [c for c in self.gh_calls if c[1:3] == ["repo", "create"]]

    def commits(self, name):
        log = real_run_command(["git", "--git-dir", str(self.github / f"{name}.git"), "log", "--all", "--oneline"])
        return [line for line in log["stdout"].splitlines() if line]

    def pushed_files(self, name):
        tree = real_run_command(["git", "--git-dir", str(self.github / f"{name}.git"), "ls-tree", "-r", "--name-only", "main"])
        assert tree["success"], tree["stderr"]
        return tree["stdout"].splitlines()

    # ---- a project --------------------------------------------------------------------
    def project(self, gitignore=GOOD_IGNORE, files=(), parent=None, name="my-mcp", pyproject=True):
        project = (parent or self.tmp / "work") / name
        project.mkdir(parents=True)
        if pyproject:
            (project / "pyproject.toml").write_text('[project]\nname = "my-mcp"\n')
        if gitignore is not None:
            (project / ".gitignore").write_text(gitignore)
        for rel in ("src/app.py", *files):
            path = project / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("placeholder, not a real secret\n")
        return project

    def assert_untouched(self, project):
        """A refusal that came before git or gh was allowed to do anything."""
        assert self.gh_calls == [] and not (Path(project) / ".git").exists()

    def assert_nothing_published(self, *repo_names):
        assert self.created() == []
        assert not any(c[:2] == ["git", "push"] for c in self.git_calls)
        for name in repo_names:
            assert self.commits(name) == []


@pytest.fixture
def h(tmp_path, monkeypatch):
    return Harness(tmp_path, monkeypatch)


def run(project, name="my-mcp", **kw):
    return json.loads(setup_github(str(project), name, **kw))


# ------------------------------------------------------------ the normal path

def test_creates_a_private_repo_and_the_commit_lands_in_it(h):
    project = h.project()
    result = run(project)
    assert result["success"] is True and result["private"] is True
    assert len(h.created()) == 1 and "--private" in h.created()[0] and "--public" not in h.created()[0]
    assert len(h.commits("my-mcp")) == 1
    assert sorted(h.pushed_files("my-mcp")) == [".gitignore", "pyproject.toml", "src/app.py"]
    assert real_git(project, "remote", "get-url", "origin")["stdout"] == h.repos["my-mcp"]["url"]
    steps = " ".join(result["next_steps"])
    assert "never creates a public repository" in steps
    assert "gh repo edit octocat/my-mcp --visibility public --accept-visibility-change-consequences" in steps


def test_running_it_twice_does_not_push_again(h):
    # the tool creates new repositories; the second run finds one and leaves it alone
    project = h.project()
    assert run(project)["success"] is True
    (project / "src" / "more.py").write_text("x = 1\n")
    again = run(project)
    assert again["success"] is False and "already exists" in again["error"]
    assert len(h.created()) == 1 and len(h.commits("my-mcp")) == 1


# ------------------------- confirmation pass 3: an existing repository is never adopted

@pytest.mark.parametrize("private", [True, False])
@pytest.mark.parametrize("visibility", ["PRIVATE", "PUBLIC", "INTERNAL"])
def test_existing_repository_of_any_visibility_is_refused_before_anything_is_touched(h, private, visibility):
    h.add_repo("my-mcp", visibility)
    project = h.project()
    result = run(project, private=private)
    assert result["success"] is False
    assert "already exists" in result["error"] and visibility in result["error"]
    # how to do it by hand is spelled out
    assert "git remote add origin https://github.com/octocat/my-mcp.git" in result["error"]
    assert "git push -u origin HEAD" in result["error"]
    assert ("publishes the code" in result["error"]) == (visibility != "PRIVATE")
    assert not (project / ".git").exists()                # not even `git init` ran
    h.assert_nothing_published("my-mcp")


def test_existing_private_repository_is_not_adopted_even_when_origin_already_points_at_it(h):
    project = h.project()
    bare = h.add_repo("my-mcp")
    real_git(project, "init", "-q")
    real_git(project, "remote", "add", "origin", str(bare))
    result = run(project)
    assert result["success"] is False and "already exists" in result["error"]
    assert real_git(project, "ls-files")["stdout"] == ""  # nothing staged either
    h.assert_nothing_published("my-mcp")


# ----------------------------------------------- rule: never a public repository

def test_private_false_still_creates_a_private_repository(h):
    result = run(h.project(), private=False)
    assert result["success"] is True and result["private"] is True
    assert "--private" in h.created()[0] and "--public" not in h.created()[0]
    assert h.repos["my-mcp"]["visibility"] == "PRIVATE"
    steps = " ".join(result["next_steps"])
    assert "You asked for a public repository" in steps and "gh repo edit octocat/my-mcp --visibility public" in steps


@pytest.mark.parametrize("name", ["--public", "-x", "octocat/other", "a/b", "a b", "", ".hidden", "repo.git", "x" * 101])
def test_repo_name_that_gh_could_read_as_something_else_is_refused(h, name):
    project = h.project()
    result = run(project, name)
    assert result["success"] is False and "repo_name" in result["error"]
    h.assert_untouched(project)


def test_tool_schema_and_description_say_private(h):
    from mcp_creator.server import mcp

    tool = mcp._tool_manager._tools["setup_github"]
    assert tool.parameters["properties"]["private"]["default"] is True
    assert "never creates a public repository" in tool.description


# ------------------------------- finding 1: the commit goes only where this call says

def test_existing_origin_elsewhere_is_refused_and_nothing_lands_there(h):
    project = h.project()
    old = h.add_repo("oldname")
    h.add_repo("newname")
    real_git(project, "init", "-q")
    assert real_git(project, "remote", "add", "origin", str(old))["success"]
    result = run(project, "newname")
    assert result["success"] is False
    assert h.commits("oldname") == [] and h.commits("newname") == []
    assert real_git(project, "remote", "get-url", "origin")["stdout"] == str(old)   # their remote is left alone
    assert real_git(project, "ls-files")["stdout"] == ""


def test_existing_origin_blocks_creating_a_second_repository(h):
    project = h.project()
    old = h.add_repo("oldname")
    real_git(project, "init", "-q")
    real_git(project, "remote", "add", "origin", str(old))
    result = run(project, "newname")
    assert result["success"] is False and "already has a remote named origin" in result["error"]
    assert real_git(project, "remote", "get-url", "origin")["stdout"] == str(old)
    assert real_git(project, "ls-files")["stdout"] == ""
    h.assert_nothing_published("oldname")


@pytest.mark.parametrize("step, needle", [
    (("git", "push"), "git push"),
    (("git", "add"), "git add failed"),
    (("git", "commit"), "git commit failed"),
    (("git", "ls-files"), "staged files"),
    (("git", "init"), "git init failed"),
    (("git", "remote", "add"), "git remote add failed"),
    (("gh", "api", "user"), "GitHub account"),
    (("gh", "repo", "create"), "Failed to create GitHub repo"),
])
def test_every_failing_step_stops_the_run_and_is_reported(h, step, needle):
    h.fail[step] = "simulated failure"
    result = run(h.project())
    assert result["success"] is False and needle in result["error"]
    assert not any(c[:2] == ["git", "push"] for c in h.git_calls)


# ------------------------------------------------ the folder must be a project

def test_refuses_folder_without_pyproject(h):
    project = h.project(pyproject=False)
    assert "pyproject.toml" in run(project)["error"]
    h.assert_untouched(project)


def test_refuses_folder_without_gitignore_and_does_not_create_one(h):
    project = h.project(gitignore=None)
    assert ".gitignore" in run(project)["error"]
    assert not (project / ".gitignore").exists()
    h.assert_untouched(project)


def test_refuses_home_directory_even_if_it_looks_like_a_project(h, monkeypatch):
    home = h.project(name="fake-home")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert "home directory" in run(home)["error"]
    h.assert_untouched(home)


def test_refuses_a_symlink_to_the_home_directory(h, monkeypatch):
    home = h.project(name="fake-home")
    link = h.tmp / "looks-like-a-project"
    link.symlink_to(home, target_is_directory=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert "home directory" in run(link)["error"]
    h.assert_untouched(home)


def test_refuses_parent_of_home_and_filesystem_root(h, monkeypatch):
    parent = h.project(name="users")
    home = parent / "someone"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert "contains your home directory" in run(parent)["error"]
    assert "filesystem root" in run(Path(h.tmp.anchor))["error"]
    h.assert_untouched(parent)


def test_finding_2_home_is_refused_under_a_different_letter_case(h, monkeypatch):
    home = h.project(name="fakehome")
    shouted = home.parent / "FAKEHOME"
    if not shouted.exists():
        pytest.skip("this filesystem is case-sensitive: FAKEHOME is a different, non-existent folder")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    result = run(shouted)
    assert result["success"] is False and "home directory" in result["error"]
    h.assert_untouched(home)
    parent_shouted = Path(str(home.parent.parent / home.parent.name.upper()))
    assert "contains your home directory" in run(parent_shouted)["error"] or not parent_shouted.exists()


# ----------------------------------------- not inside someone else's repository

def test_refuses_project_inside_another_repository(h):
    outer = h.tmp / "outer"
    outer.mkdir()
    assert real_git(outer, "init", "-q")["success"]
    project = h.project(parent=outer / "work")
    result = run(project)
    assert result["success"] is False
    assert "inside another git repository" in result["error"] and str(outer) in result["error"]
    assert real_git(outer, "diff", "--cached", "--name-only")["stdout"] == ""
    h.assert_untouched(project)


def test_refuses_when_git_cannot_answer_and_a_git_entry_is_above(h):
    outer = h.tmp / "outer"
    outer.mkdir()
    (outer / ".git").write_text("gitdir: /nonexistent/elsewhere\n")
    project = h.project(parent=outer)
    assert "Refusing to stage" in run(project)["error"]
    h.assert_untouched(project)


def test_project_that_is_its_own_repository_is_accepted(h):
    project = h.project()
    assert real_git(project, "init", "-q")["success"]
    assert run(project)["success"] is True


def test_child_processes_do_not_inherit_git_variables(h, monkeypatch):
    # the reviewer's trigger: with GIT_DIR set, git add and git commit ran in the OTHER repository
    other = h.tmp / "other"
    other.mkdir()
    assert real_git(other, "init", "-q")["success"]
    project = h.project()
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    result = run(project)
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    assert result["success"] is True, result
    assert (project / ".git").is_dir() and len(h.commits("my-mcp")) == 1
    assert real_git(other, "rev-list", "--all")["stdout"] == ""
    assert real_git(other, "ls-files")["stdout"] == ""


# -------------------------------------- finding 3: the .gitignore has to work

@pytest.mark.parametrize("gitignore, uncovered", [
    ("", ".env"),
    ("dist/\n", ".env"),
    (".venv/\n", ".env"),
    (".env\n", ".venv/x"),
    (".env\n!.env\n.venv/\n", ".env"),
])
def test_gitignore_that_does_not_cover_the_basics_is_refused(h, gitignore, uncovered):
    project = h.project(gitignore=gitignore)
    result = run(project)
    assert result["success"] is False and "does not ignore" in result["error"] and uncovered in result["error"]
    assert real_git(project, "ls-files")["stdout"] == ""
    h.assert_nothing_published()


# ------------------------------------- finding 3: secret-looking files, by name

SECRET_FILES = [
    ".env.production", "config/.env.local", ".netrc", ".npmrc", ".pypirc", ".pgpass", ".htpasswd", ".envrc",
    ".git-credentials", "kubeconfig", "certs/server.pem", "deploy.key", "store.p12", "cert.pfx", "AuthKey.p8",
    "putty.ppk", "release.jks", "release.keystore", "vault.kdbx", "keys/id_rsa", "keys/id_rsa.pub", "id_dsa",
    "id_ecdsa", "id_ed25519", "credentials.json", "credentials", "service-account-prod.json", "prod.tfvars",
    "terraform.tfstate", ".aws/credentials", "home/.docker/config.json", "Server.PEM",
    # confirmation pass 1: these two must STILL be refused after the narrowing
    "service-account.json", "credentials.yaml", "credentials.ini", "config/Credentials.JSON",
    # a marker as the FIRST part of the name does not make a template: only a marker that
    # follows the secret-looking name does (server.pem.sample is a template, these are not)
    "example.pem", "sample.key", "sample.server.pem", "example.deploy.key",
]
# confirmation pass 1: honest source, documentation and template files (the reviewer's five first)
HONEST_FILES = ["src/pkg/credentials.py", "docs/credentials-howto.md", ".env.template", ".env.local.example",
                "config/service-account.example.json",
                "credentials.md", "credentials_test.py", "credentials-rotation.sh", "src/credentials/__init__.py",
                ".env.dist", "credentials.json.example", "credentials.example.json", "certs/server.pem.sample",
                "deploy.key.template", ".aws/credentials.example"]
NOT_SECRET_FILES = [".env.example", ".env.sample", "docs/monkey.md", "keyboard.txt", "docker/config.json",
                    "config.json", "service-account.md", "pem.txt", "my-credentials-notes.md", *HONEST_FILES]
TEMPLATE_FILES = [".env.example", "config/.env.sample", ".env.template", ".env.local.example",
                  "config/service-account.example.json", "credentials.json.dist"]


@pytest.mark.parametrize("name", SECRET_FILES)
def test_name_rules_flag_secrets(name):
    from mcp_creator.services.project_guard import is_secret_like, is_template_name

    assert is_secret_like(name) and not is_template_name(name)


@pytest.mark.parametrize("name", NOT_SECRET_FILES)
def test_name_rules_leave_honest_files_alone(name):
    from mcp_creator.services.project_guard import is_secret_like

    assert not is_secret_like(name)


@pytest.mark.parametrize("name", TEMPLATE_FILES + ["certs/server.pem.sample", "id_rsa.example"])
def test_template_variants_are_recognised_as_templates(name):
    from mcp_creator.services.project_guard import is_secret_like, is_template_name

    assert is_template_name(name) and not is_secret_like(name)


def test_refusal_says_what_to_do_with_an_ordinary_file(h):
    result = run(h.project(files=["deploy.key"]))
    assert result["success"] is False and "rename it" in result["error"]


def test_honest_files_already_in_history_do_not_block_the_push(h):
    # the reviewer's point: once such a file was committed, every later push was refused
    project = h.project(files=HONEST_FILES)
    real_git(project, "init", "-q")
    real_git(project, "add", "-A")
    assert real_git(project, "commit", "-q", "-m", "first")["success"]
    (project / "src" / "two.py").write_text("x = 2\n")
    result = run(project)
    assert result["success"] is True, result
    assert set(HONEST_FILES) <= set(h.pushed_files("my-mcp")) and len(h.commits("my-mcp")) == 2


@pytest.mark.parametrize("secret", SECRET_FILES)
def test_unignored_secret_in_the_working_tree_is_refused(h, secret):
    project = h.project(files=[secret])
    result = run(project)
    assert result["success"] is False
    assert result["secret_like_files"] == [secret] and secret in result["error"]
    assert real_git(project, "ls-files")["stdout"] == ""          # nothing staged
    h.assert_nothing_published()


def test_ordinary_file_names_are_not_mistaken_for_secrets(h):
    result = run(h.project(files=NOT_SECRET_FILES))
    assert result["success"] is True, result
    assert set(NOT_SECRET_FILES) <= set(h.pushed_files("my-mcp"))


def test_ignored_secrets_stay_out_of_the_push(h):
    project = h.project(gitignore=GOOD_IGNORE + "*.pem\n", files=[".env", "certs/server.pem", ".env.example"])
    assert run(project)["success"] is True
    pushed = h.pushed_files("my-mcp")
    assert ".env" not in pushed and "certs/server.pem" not in pushed and ".env.example" in pushed


def test_secret_staged_earlier_is_caught_although_gitignore_lists_it(h):
    project = h.project(gitignore=GOOD_IGNORE, files=[".env"])
    real_git(project, "init", "-q")
    assert real_git(project, "add", "-f", ".env")["success"]
    result = run(project)
    assert result["success"] is False and result["secret_like_files"] == [".env"]
    h.assert_nothing_published()


@pytest.mark.parametrize("hidden", ["node_modules/pkg/.npmrc", "tools-venv/lib/server.pem"])
def test_whole_index_is_checked_including_folders_the_scan_skips(h, hidden):
    files = [hidden] + (["tools-venv/pyvenv.cfg"] if hidden.startswith("tools-venv") else [])
    project = h.project(files=files)
    result = run(project)
    assert result["success"] is False and "in the index" in result["error"]
    assert result["secret_like_files"] == [hidden]
    tracked = real_git(project, "ls-files")["stdout"].splitlines()
    assert hidden not in tracked and "src/app.py" in tracked       # unstaged, the rest left alone
    h.assert_nothing_published()


# ----------------------------------------------- finding 4: the history is pushed too

def test_secret_committed_earlier_and_removed_since_is_refused(h):
    # the reviewer's trigger: commit it, then `git rm --cached` and add it to .gitignore
    project = h.project(gitignore="dist/\n", files=[".env"])
    real_git(project, "init", "-q")
    real_git(project, "add", "-A")
    assert real_git(project, "commit", "-q", "-m", "first")["success"]
    real_git(project, "rm", "--cached", "-q", ".env")
    (project / ".gitignore").write_text(GOOD_IGNORE)
    real_git(project, "add", "-A")
    assert real_git(project, "commit", "-q", "-m", "remove the secret")["success"]
    assert ".env" not in real_git(project, "ls-files")["stdout"].splitlines()

    result = run(project)
    assert result["success"] is False and "history" in result["error"]
    assert result["secret_like_files"] == [".env"]
    h.assert_nothing_published()


def test_secret_on_another_branch_is_refused_too(h):
    project = h.project()
    real_git(project, "init", "-q")
    real_git(project, "add", "-A")
    real_git(project, "commit", "-q", "-m", "first")
    real_git(project, "checkout", "-q", "-b", "experiment")
    (project / "deploy.key").write_text("placeholder\n")
    real_git(project, "add", "-f", "deploy.key")
    assert real_git(project, "commit", "-q", "-m", "oops")["success"]
    real_git(project, "checkout", "-q", "main")
    assert not (project / "deploy.key").exists()

    result = run(project)
    assert result["success"] is False and result["secret_like_files"] == ["deploy.key"]
    h.assert_nothing_published()


def test_clean_history_is_pushed_whole(h):
    project = h.project()
    real_git(project, "init", "-q")
    real_git(project, "add", "-A")
    real_git(project, "commit", "-q", "-m", "first")
    (project / "src" / "two.py").write_text("x = 2\n")
    assert run(project)["success"] is True
    assert len(h.commits("my-mcp")) == 2


# ------------------------- finding 9: the repository must be stored in project/.git

def _commit_everything(folder):
    real_git(folder, "add", "-A")
    assert real_git(folder, "commit", "-q", "-m", "base")["success"]


def test_linked_worktree_is_refused_and_the_main_repository_is_untouched(h):
    main = h.project(name="main-repo")
    real_git(main, "init", "-q")
    _commit_everything(main)
    worktree = h.tmp / "work" / "linked"
    assert real_git(main, "worktree", "add", "-q", "-b", "side", str(worktree))["success"]
    assert (worktree / ".git").is_file() and (worktree / "pyproject.toml").is_file()
    (worktree / "new.py").write_text("x = 1\n")
    commits_before = real_git(main, "rev-list", "--all")["stdout"]

    result = run(worktree)
    assert result["success"] is False and ".git" in result["error"]
    assert real_git(main, "rev-list", "--all")["stdout"] == commits_before        # no commit was added there
    assert real_git(worktree, "diff", "--cached", "--name-only")["stdout"] == ""  # nothing staged there
    h.assert_nothing_published()


def test_repository_stored_elsewhere_through_a_git_file_is_refused(h):
    project = h.project()
    elsewhere = h.tmp / "elsewhere.git"
    assert real_run_command(["git", "init", "-q", f"--separate-git-dir={elsewhere}", str(project)])["success"]
    assert (project / ".git").is_file()
    result = run(project)
    assert result["success"] is False and ".git" in result["error"]
    assert real_run_command(["git", "--git-dir", str(elsewhere), "ls-files", "--cached"])["stdout"] == ""
    h.assert_nothing_published()


def test_git_folder_that_is_a_symlink_is_refused(h):
    other = h.project(name="other-repo")
    real_git(other, "init", "-q")
    project = h.project()
    (project / ".git").symlink_to(other / ".git", target_is_directory=True)
    result = run(project)
    assert result["success"] is False
    assert real_git(other, "diff", "--cached", "--name-only")["stdout"] == ""
    h.assert_nothing_published()


# ---------------- finding 11: template files are exempt by name, not by content

# Credential-shaped strings are assembled here so that none sits in this file as a literal.
_BODY = "aB3dE5gH7jK9mN1pQ3sT5vW7yZ0cF2hJ4"
LIVE_LOOKING = {
    "openai": "s" + "k-" + _BODY,
    "github": "gh" + "p_" + _BODY,
    "github oauth": "gh" + "o_" + _BODY,
    "github fine-grained": "github" + "_pat_" + _BODY,
    "gitlab": "gl" + "pat-" + _BODY,
    "aws key id": "AK" + "IA" + "Q7ZP4MND2XWK9RTB",
    "aws temporary": "AS" + "IA" + "Q7ZP4MND2XWK9RTB",
    "pypi": "py" + "pi-" + _BODY,
    "npm": "np" + "m_" + _BODY,
    "slack bot": "xo" + "xb-" + _BODY,
    "slack user": "xo" + "xp-" + _BODY,
    "stripe": "sk" + "_live_" + _BODY,
    "stripe restricted": "rk" + "_live_" + _BODY,
    "marketplace": "mcp" + "_live_" + _BODY,
    "private key": "-----BEGIN " + "RSA PRIVATE KEY-----",
}
PLACEHOLDERS = [
    "API_KEY=", "API_KEY=your-key-here", "API_KEY=changeme", "KEY=sk-your-key-here", "KEY=mcp_live_your_key_here",
    "KEY=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "AWS=AKIAIOSFODNN7EXAMPLE", "# get one at https://example.com/keys",
    "TASK-ID=task-abcdefghijklmnopqrstuvwxyz", "PORT=8000", "KEY=sk-short", "KEY=pypi-replace-with-your-token-please",
]


@pytest.mark.parametrize("kind", sorted(LIVE_LOOKING))
@pytest.mark.parametrize("template", [".env.example", "config/.env.sample"])
def test_live_looking_credential_in_a_template_file_is_refused(h, kind, template):
    project = h.project(files=[template])
    value = LIVE_LOOKING[kind]
    (project / template).write_text(f"# settings\nPORT=8000\nSECRET={value}\n")
    result = run(project)
    assert result["success"] is False and result["credential_locations"] == [f"{template}:3"]
    assert f"{template}:3" in result["error"]
    assert value not in json.dumps(result)               # the value itself is never repeated
    assert real_git(project, "ls-files")["stdout"] == ""
    h.assert_nothing_published()


@pytest.mark.parametrize("template", TEMPLATE_FILES)
def test_every_template_variant_is_content_scanned(h, template):
    project = h.project(files=[template])
    value = LIVE_LOOKING["github"]
    (project / template).write_text(f"FIRST=1\nTOKEN={value}\n")
    result = run(project)
    assert result["success"] is False and result["credential_locations"] == [f"{template}:2"]
    assert value not in json.dumps(result)
    h.assert_nothing_published()


@pytest.mark.parametrize("filler_lines", [130_000, 20])
def test_confirmation_2_template_that_cannot_be_read_whole_is_refused(h, filler_lines):
    from mcp_creator.services import project_guard

    project = h.project(files=[".env.example"])
    filler = "# filler line\n" * filler_lines                   # 130,000 lines is about 1.8 MB
    (project / ".env.example").write_text(filler + "TOKEN=" + LIVE_LOOKING["pypi"] + "\n")
    result = run(project)
    assert result["success"] is False
    if len(filler) > project_guard._TEMPLATE_READ_LIMIT:
        assert "could not be fully checked" in result["error"]
        assert len(result["credential_locations"]) == 1
        assert result["credential_locations"][0].startswith(".env.example (larger than")
    else:
        assert result["credential_locations"] == [f".env.example:{filler_lines + 1}"]
    h.assert_nothing_published()


def test_placeholders_in_template_files_pass(h):
    project = h.project(files=[".env.example", ".env.sample"])
    (project / ".env.example").write_text("\n".join(PLACEHOLDERS) + "\n")
    (project / ".env.sample").write_text("")
    result = run(project)
    assert result["success"] is True, result
    assert ".env.example" in h.pushed_files("my-mcp")


def test_ignored_template_file_is_not_read_as_a_blocker(h):
    project = h.project(gitignore=GOOD_IGNORE + ".env.example\n", files=[".env.example"])
    (project / ".env.example").write_text("SECRET=" + LIVE_LOOKING["github"] + "\n")
    assert run(project)["success"] is True
    assert ".env.example" not in h.pushed_files("my-mcp")


def test_harness_home_is_the_made_up_one(h):
    # guards the isolation the whole file relies on: no developer git configuration
    assert os.environ["HOME"] == str(h.home)
    assert real_git(h.tmp, "config", "--global", "user.email")["stdout"] == "test@example.invalid"
