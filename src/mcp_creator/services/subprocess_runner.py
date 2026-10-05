"""Safe subprocess.run wrapper for git, gh and uv."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def child_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a child process gets: the given one (or ours) without any GIT_* variable.

    GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE and their relatives silently point git at a
    different repository than the folder it is run in. Every tool here means "the
    repository in this project folder", so none of them is passed on.
    """
    source = os.environ if env is None else env
    return {k: v for k, v in source.items() if not k.upper().startswith("GIT_")}


def run_command(
    cmd: list[str],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> dict:
    """Run a subprocess and return structured output.

    Returns:
        dict with keys: success (bool), command (str), stdout, stderr, return_code
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=child_environment(env),
        )
        return {
            "success": result.returncode == 0,
            "command": " ".join(cmd),
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "return_code": result.returncode,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "command": " ".join(cmd),
            "stdout": "",
            "stderr": f"Command not found: {cmd[0]}. Make sure it is installed and on your PATH.",
            "return_code": -1,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "command": " ".join(cmd),
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s.",
            "return_code": -1,
        }
