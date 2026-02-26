"""Safe subprocess.run wrapper for uv build / uv publish."""

from __future__ import annotations

import subprocess
from pathlib import Path


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
            env=env,
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
