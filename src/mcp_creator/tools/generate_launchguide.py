"""Generate a LAUNCHGUIDE.md for MCP Marketplace submission."""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from mcp_creator.services.file_writer import UnsafePathError, write_project_files
from mcp_creator.services.project_guard import check_project_dir


# The sections of LAUNCHGUIDE.md, in order: (heading, field). A section whose content is
# empty is left out altogether. MCP Marketplace treats a heading that is present as a
# section that was filled in, so an empty "## Use Cases" hid the Features list.
LAUNCHGUIDE_SECTIONS = (
    ("Tagline", "tagline"),
    ("Description", "description"),
    ("Setup Requirements", "setup_requirements"),
    ("Category", "category"),
    ("Use Cases", "use_cases"),
    ("Features", "features"),
    ("Getting Started", "getting_started"),
    ("Tags", "tags"),
    ("Documentation URL", "docs_url"),
)


def render_launchguide(package_name: str, fields: dict[str, str]) -> str:
    """LAUNCHGUIDE.md text from already-sanitised field values; empty sections are omitted."""
    parts = [f"# {package_name}"]
    for heading, field in LAUNCHGUIDE_SECTIONS:
        content = (fields.get(field) or "").strip()
        if content:
            parts.append(f"## {heading}\n{content}")
    return "\n\n".join(parts) + "\n"


# LAUNCHGUIDE.md has two readers. MCP Marketplace PARSES it: a line starting with "## "
# opens a section, and each field is then shown as plain text. People and GitHub RENDER
# it as Markdown. So the rule here is about LINES: a value may never start a line that
# opens structure. Values are not backslash-escaped character by character, because the
# marketplace would show those backslashes and its Setup Requirements parser needs the
# backticks and parentheses as written.
LIMITS = {"tagline": 100, "category": 60, "item": 300, "items": 30, "list_item": 50, "block": 5000}
_URL_RE = re.compile(r"https?://[^\s<>()\[\]`\"'\\]+")
_OPENS_STRUCTURE = re.compile(r"(#|>|```|~~~|\t| {4,}|[=-]+\s*$)")


def _flat(text) -> str:
    """One line: every line break, tab and control character becomes a single space."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())


def _inert_start(line: str, changed: list | None = None, field: str = "") -> str:
    """Stop a line from opening a heading, quote, fence, code block or setext underline."""
    line = line.strip()
    if not _OPENS_STRUCTURE.match(line):
        return line
    if changed is not None:
        changed.append(f"{field}: a line that would open Markdown structure was escaped")
    return "\\" + line


def _cap(text: str, limit: int, changed: list, field: str) -> str:
    if len(text) > limit:
        changed.append(f"{field} shortened to {limit} characters")
        return text[:limit].rstrip()
    return text


def _one_line(text, field: str, limit: int, changed: list) -> str:
    flat = _flat(text)
    if flat != str(text).strip():
        changed.append(f"{field} put on one line")
    return _inert_start(_cap(flat, limit, changed, field), changed, field)


def _block(text, field: str, changed: list) -> str:
    """A multi-line value: its own line breaks are kept, but no line can open structure."""
    raw = _cap(str(text), LIMITS["block"], changed, field)
    lines = [_inert_start("".join(ch if ch.isprintable() else " " for ch in ln)) for ln in raw.splitlines()]
    out = "\n".join(lines).strip()
    if out != "\n".join(ln.strip() for ln in raw.splitlines()).strip():
        changed.append(f"{field}: lines that would open Markdown structure were escaped")
    return out


def _bullets(text, field: str, changed: list) -> str:
    """One `- item` per input line. The list is ours; each item is one inert line."""
    items = [_flat(re.sub(r"^\s*(?:[-*+]\s+)+", "", ln)) for ln in str(text).splitlines()]
    items = [i for i in items if i]
    if len(items) > LIMITS["items"]:
        changed.append(f"{field} cut to {LIMITS['items']} items")
        items = items[: LIMITS["items"]]
    return "\n".join("- " + _inert_start(_cap(i, LIMITS["item"], changed, field), changed, field) for i in items)


def _comma_list(text, field: str, changed: list) -> str:
    items = [i for i in (_flat(part) for part in str(text).split(",")) if i]
    if len(items) > LIMITS["items"]:
        changed.append(f"{field} cut to {LIMITS['items']} items")
        items = items[: LIMITS["items"]]
    return _inert_start(", ".join(_cap(i, LIMITS["list_item"], changed, field) for i in items), changed, field)


def generate_launchguide(
    project_dir: str,
    package_name: str,
    tagline: str,
    description: str,
    category: str,
    features: str,
    tags: str,
    setup_requirements: str = "No environment variables required.",
    docs_url: str = "",
    use_cases: str = "",
    getting_started: str = "",
    tools_summary: str = "",
) -> str:
    """Generate a LAUNCHGUIDE.md for MCP Marketplace submission.

    Args:
        project_dir: Absolute path to the project root.
        package_name: PyPI package name.
        tagline: One-liner (max 100 chars).
        description: What the server does, how it works, who it's for.
        category: One of: Developer Tools, Data & Analytics, Productivity, etc.
        features: Bullet-point features (one per line, prefixed with "- "). Max 30 items.
        tags: Comma-separated tags. Max 30.
        setup_requirements: Env vars or setup steps (default: none required).
        docs_url: Link to docs or README.
        use_cases: Comma-separated use cases (e.g. "Testing, Prototyping, CI/CD"). Max 30.
        getting_started: Example prompts and tool descriptions (one per line).
        tools_summary: Deprecated — use getting_started instead. Kept for backwards compat.

    Returns:
        JSON string with file path and next steps.
    """
    project, reason = check_project_dir(project_dir)
    if project is None:
        return json.dumps({"success": False, "error": reason})

    # tools_summary is the old name for getting_started — support both
    actual_getting_started = getting_started or tools_summary

    changed: list[str] = []
    name = _one_line(package_name, "package_name", 100, changed)
    default_url = f"https://pypi.org/project/{quote(name, safe='')}/"
    url = str(docs_url).strip()
    if url and not _URL_RE.fullmatch(url):
        changed.append("docs_url was not a plain http(s) URL and was replaced by the PyPI page")
        url = ""

    content = render_launchguide(name, dict(
        tagline=_one_line(tagline, "tagline", LIMITS["tagline"], changed),
        description=_block(description, "description", changed),
        setup_requirements=_block(setup_requirements, "setup_requirements", changed),
        category=_one_line(category, "category", LIMITS["category"], changed),
        use_cases=_comma_list(use_cases, "use_cases", changed),
        features=_bullets(features, "features", changed),
        getting_started=_bullets(actual_getting_started, "getting_started", changed),
        tags=_comma_list(tags, "tags", changed),
        docs_url=url or default_url,
    ))

    try:
        written = write_project_files(project, {"LAUNCHGUIDE.md": content})
    except UnsafePathError as exc:
        return json.dumps({"success": False, "error": str(exc)})

    result = {
        "success": True,
        "file": str(project / "LAUNCHGUIDE.md"),
        "next_steps": [
            "LAUNCHGUIDE.md created!",
            "Review it and make any final edits.",
            f"Submit to MCP Marketplace at https://mcp-marketplace.io with this file.",
        ],
    }
    if changed:
        result["normalized"] = changed

    return json.dumps(result, indent=2)
