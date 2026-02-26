"""Write generated files to disk."""

from __future__ import annotations

from pathlib import Path


def write_project_files(base_dir: str | Path, files: dict[str, str]) -> list[str]:
    """Write a dict of {relative_path: content} to base_dir.

    Creates parent directories as needed.

    Returns:
        List of absolute paths written.
    """
    base = Path(base_dir)
    written = []
    for rel_path, content in files.items():
        full_path = base / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        written.append(str(full_path))
    return written


def inject_after_sentinel(
    file_path: str | Path, sentinel: str, content: str
) -> bool:
    """Insert content after a sentinel comment line in a file.

    Returns True if injection succeeded, False if sentinel not found.
    """
    path = Path(file_path)
    text = path.read_text(encoding="utf-8")
    if sentinel not in text:
        return False
    text = text.replace(sentinel, sentinel + "\n" + content, 1)
    path.write_text(text, encoding="utf-8")
    return True
