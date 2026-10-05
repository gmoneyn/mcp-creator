"""Check PyPI package name availability using stdlib urllib (zero deps)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"


def check_name_available(name: str) -> dict:
    """Check if a package name is available on PyPI.

    Returns:
        dict with keys: name, available (bool), existing_version (str|None),
        existing_description (str|None), suggestion (str|None)
    """
    url = PYPI_JSON_URL.format(name=name)
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            info = data.get("info", {})
            return {
                "name": name,
                "available": False,
                "existing_version": info.get("version"),
                "existing_description": info.get("summary"),
                "suggestion": f'Try "{name}-mcp" or add a unique prefix.',
            }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {
                "name": name,
                "available": True,
                "existing_version": None,
                "existing_description": None,
                "suggestion": None,
            }
        return {
            "name": name,
            "available": None,
            "error": f"PyPI returned HTTP {e.code}",
            "suggestion": "Try again in a moment.",
        }
    except (urllib.error.URLError, TimeoutError) as e:
        return {
            "name": name,
            "available": None,
            "error": str(e),
            "suggestion": "Could not reach PyPI. Check your internet connection.",
        }
