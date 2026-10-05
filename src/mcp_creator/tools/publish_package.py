"""Publish an MCP server package to PyPI with uv publish."""

from __future__ import annotations

import base64
import json
import os
import tomllib
from urllib.parse import quote, quote_plus

from mcp_creator.services.project_guard import check_project_dir
from mcp_creator.services.subprocess_runner import run_command
from mcp_creator.tools.build_package import read_built_files

PYPI_UPLOAD_URL = "https://upload.pypi.org/legacy/"
TOKEN_VAR = "UV_PUBLISH_TOKEN"
URL_VAR = "UV_PUBLISH_URL"
# Variables that choose WHERE uv uploads. The destination is passed on the command line
# instead, so none of them reaches the child process.
_DESTINATION_VARS = (URL_VAR, "UV_PUBLISH_INDEX", "UV_PUBLISH_CHECK_URL")


def _same_url(a: str, b: str) -> bool:
    return a.strip().rstrip("/") == b.strip().rstrip("/")


def _project_publish_urls(project) -> tuple[list[tuple[str, str]], str | None]:
    """Upload destinations the PROJECT's own files ask for: ([(file, url)], error)."""
    found: list[tuple[str, str]] = []
    for filename, section in (("pyproject.toml", ("tool", "uv")), ("uv.toml", ())):
        path = project / filename
        if not path.is_file():
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return [], f"Could not read {filename} to check where it uploads: {exc}"
        for key in section:
            data = data.get(key, {}) if isinstance(data, dict) else {}
        url = data.get("publish-url") if isinstance(data, dict) else None
        if url:
            found.append((filename, str(url)))
    return found, None


def _token_forms(*tokens: str | None) -> list[str]:
    """Every spelling of a token that could show up in tool output, longest first.

    The token itself, with and without surrounding whitespace; base64 of the token and of
    `__token__:<token>` (how it travels in an HTTP Authorization header), standard and
    URL-safe, with and without padding; and its URL-encoded forms.
    """
    forms: set[str] = set()
    for raw in tokens:
        if not raw:
            continue
        forms.add(raw)
        stripped = raw.strip()
        forms.add(stripped)
        forms.add(quote(stripped, safe=""))
        forms.add(quote_plus(stripped))
        for plain in (stripped, f"__token__:{stripped}"):
            for encode in (base64.b64encode, base64.urlsafe_b64encode):
                encoded = encode(plain.encode("utf-8")).decode("ascii")
                forms.update((encoded, encoded.rstrip("=")))
    # a very short string is not a credential, and replacing it would shred the output
    return sorted((f for f in forms if len(f) >= 6), key=len, reverse=True)


def publish_package(project_dir: str, token: str | None = None) -> str:
    """Publish the built package to PyPI using uv publish.

    Args:
        project_dir: Absolute path to the project root.
        token: Optional PyPI API token. If not provided, uses UV_PUBLISH_TOKEN
               environment variable. A token passed here is visible to the model;
               Trusted Publishing from GitHub Actions needs no token and is the
               recommended route. A token passed here is only ever sent to PyPI.

    Returns:
        JSON string with publish result and next steps.
    """
    # Only ever publish from a project directory (see project_guard).
    project, reason = check_project_dir(project_dir)
    if project is None:
        return json.dumps({"success": False, "error": reason})

    # Upload exactly the files the last build_package run produced, and nothing else that
    # happens to be in dist/ (and never from a dist that is a link to somewhere else).
    built_files, reason = read_built_files(project)
    if reason:
        return json.dumps({
            "success": False,
            "error": reason,
            "next_steps": ["Use build_package to build the project before publishing."],
        })

    token = token.strip() if isinstance(token, str) and token.strip() else None
    env = dict(os.environ)
    if token:
        env[TOKEN_VAR] = token

    if not env.get(TOKEN_VAR, "").strip():
        return json.dumps({
            "success": False,
            "error": "No PyPI token found. Set UV_PUBLISH_TOKEN or pass a token.",
            "next_steps": [
                "Get a PyPI API token at https://pypi.org/manage/account/token/",
                "Then either: export UV_PUBLISH_TOKEN=pypi-... or pass it to this tool.",
            ],
        })

    # Where the upload goes is decided HERE and passed on the command line, which uv puts
    # above both its environment and the project's files. A token handed to this tool goes
    # to PyPI only. Without one, the owner's own UV_PUBLISH_URL is honoured. The project
    # being published never gets to choose: a folder the model was pointed at must not be
    # able to send the owner's token somewhere else.
    owner_url = os.environ.get(URL_VAR, "").strip()
    if token and owner_url and not _same_url(owner_url, PYPI_UPLOAD_URL):
        return json.dumps({
            "success": False,
            "error": (
                f"{URL_VAR} is set to a different destination. A token passed to this tool is only sent to "
                f"PyPI ({PYPI_UPLOAD_URL}). Unset {URL_VAR}, or publish from your own shell."
            ),
        })
    destination = PYPI_UPLOAD_URL if token or not owner_url else owner_url
    project_urls, error = _project_publish_urls(project)
    if error:
        return json.dumps({"success": False, "error": error})
    elsewhere = [name for name, url in project_urls if not _same_url(url, destination)]
    if elsewhere:
        return json.dumps({
            "success": False,
            "error": (
                "This project's own configuration sets a different upload destination (publish-url in "
                + ", ".join(elsewhere) + "). Refusing to send a token anywhere but the destination "
                "you chose yourself (PyPI unless you set one). Remove that setting, or publish "
                "from your own shell."
            ),
        })
    for name in _DESTINATION_VARS:
        env.pop(name, None)

    # The token travels in the child's environment only, never on the command line.
    result = run_command(
        ["uv", "publish", "--publish-url", destination, *(str(f) for f in built_files)],
        cwd=project, env=env,
    )

    # Whatever uv printed goes back to the model, so make sure the token is not in it,
    # in any of the spellings it can take on the way to the server.
    for form in _token_forms(token, env.get(TOKEN_VAR)):
        for field in ("command", "stdout", "stderr"):
            if isinstance(result.get(field), str):
                result[field] = result[field].replace(form, "[token redacted]")

    if result["success"]:
        # Try to extract package name from pyproject.toml
        pyproject_path = project / "pyproject.toml"
        package_name = "your-package"
        if pyproject_path.exists():
            for line in pyproject_path.read_text().splitlines():
                if line.strip().startswith("name"):
                    package_name = line.split("=")[1].strip().strip('"').strip("'")
                    break

        result["next_steps"] = [
            f"Published to PyPI! Install with: pip install {package_name}",
            f"View at: https://pypi.org/project/{package_name}/",
            "Next: use setup_github to create a GitHub repo and push the code.",
            "Then use generate_launchguide to create a LAUNCHGUIDE.md for marketplace submission.",
        ]
    else:
        result["next_steps"] = [
            "Publish failed. Check the error output.",
            "Common issues: invalid token, package name conflict, or network error.",
        ]

    return json.dumps(result, indent=2)
