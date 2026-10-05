"""Build an MCP server package with uv build."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from mcp_creator.services.project_guard import check_project_dir
from mcp_creator.services.subprocess_runner import run_command

# Written next to the built files. publish_package uploads exactly the files listed here,
# and only while they still have these hashes.
MANIFEST_NAME = ".mcp-creator-build.json"
_ARTIFACT_SUFFIXES = (".whl", ".tar.gz")


def check_dist_dir(project: Path) -> tuple[Path | None, str | None]:
    """Return (project/dist, None) when it is safe to build into or publish from.

    `dist` may be missing, or a real folder. A symlink is refused: building would write
    into, and publishing would upload from, wherever it points.
    """
    dist = project / "dist"
    if dist.is_symlink():
        return None, (
            f"{dist} is a symbolic link. Refusing to build into or publish from a folder "
            "outside the project. Remove the link and run build_package again."
        )
    if dist.exists() and not dist.is_dir():
        return None, f"{dist} exists and is not a folder."
    return dist, None


def _is_plain_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_built_files(project: Path) -> tuple[list[Path], str | None]:
    """The files the last build_package run produced: ([paths], None) or ([], reason).

    Every listed file must still be a plain file directly inside project/dist with the
    hash recorded at build time. Anything else in dist (older builds, files put there by
    something else) is not returned, so it is never uploaded.
    """
    dist, reason = check_dist_dir(project)
    if dist is None:
        return [], reason
    manifest = dist / MANIFEST_NAME
    if not dist.is_dir() or not _is_plain_file(manifest):
        return [], "No build from build_package was found. Run build_package first."
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return [], "The build record in dist/ is unreadable. Run build_package again."
    files: list[Path] = []
    for entry in entries if isinstance(entries, list) else []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or name != os.path.basename(name) or not name.endswith(_ARTIFACT_SUFFIXES):
            return [], "The build record in dist/ lists something that is not a built file. Run build_package again."
        path = dist / name
        if not _is_plain_file(path) or _sha256(path) != entry.get("sha256"):
            return [], (
                f"dist/{name} is missing or has changed since build_package produced it. "
                "Run build_package again."
            )
        files.append(path)
    if not files:
        return [], "The last build produced no files. Run build_package again."
    return files, None


def build_package(project_dir: str) -> str:
    """Build the MCP server package using uv build.

    Args:
        project_dir: Absolute path to the project root.

    Returns:
        JSON string with build result and next steps.
    """
    # `uv build` runs the build backend named in that folder's pyproject.toml, so only
    # ever run it in a project directory (see project_guard).
    project, reason = check_project_dir(project_dir)
    if project is None:
        return json.dumps({
            "success": False,
            "error": reason,
            "next_steps": ["Make sure you're pointing to the right project directory."],
        })
    dist, reason = check_dist_dir(project)
    if dist is None:
        return json.dumps({"success": False, "error": reason})

    # Build into a folder created here, empty, inside the project. Only what this build
    # put there is then moved up into dist/ and recorded. It sits inside dist/ so that the
    # project's own ignore rules keep it out of the source archive being built.
    dist.mkdir(exist_ok=True)
    fresh = Path(tempfile.mkdtemp(prefix=".build-", dir=dist))
    try:
        result = run_command(["uv", "build", "--out-dir", str(fresh)], cwd=project)
        if result["success"]:
            produced = sorted(
                p for p in fresh.iterdir() if _is_plain_file(p) and p.name.endswith(_ARTIFACT_SUFFIXES)
            )
            if not produced:
                result["success"] = False
                result["error"] = "uv build reported success but produced no wheel or source archive."
            else:
                entries = []
                for artifact in produced:
                    entries.append({
                        "name": artifact.name,
                        "sha256": _sha256(artifact),
                        "size": artifact.stat().st_size,
                    })
                    os.replace(artifact, dist / artifact.name)   # replaces the entry, never follows it
                record = fresh / MANIFEST_NAME
                record.write_text(json.dumps({"files": entries}, indent=2), encoding="utf-8")
                os.replace(record, dist / MANIFEST_NAME)
                result["built_files"] = [e["name"] for e in entries]
    finally:
        shutil.rmtree(fresh, ignore_errors=True)

    if result["success"]:
        built_files = result["built_files"]
        result["next_steps"] = [
            "Build successful!",
            f"Built files: {', '.join(built_files)}",
            "Next: use publish_package to upload to PyPI, or test locally first.",
        ]
    else:
        result["next_steps"] = [
            "Build failed. Check the error output above.",
            "Common fixes: make sure uv is installed, dependencies are correct, and there are no syntax errors.",
        ]

    return json.dumps(result, indent=2)
