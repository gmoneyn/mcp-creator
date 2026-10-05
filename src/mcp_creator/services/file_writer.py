"""Write generated files to disk, confined to one directory."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


class UnsafePathError(ValueError):
    """A write was asked for outside the directory it is confined to."""


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _is_inside(base: Path, resolved: Path) -> bool:
    """True when `resolved` is strictly inside `base`. Both are already resolved.

    Same spelling is the common case. A different spelling of the same folder (letter
    case, on a filesystem that ignores it) is settled by identity: some EXISTING
    ancestor of the target must be the base folder itself. A path outside the base has
    no such ancestor however it is spelled.
    """
    if resolved == base or _same(resolved, base):
        return False
    if base in resolved.parents:
        return True
    return any(_same(ancestor, base) for ancestor in resolved.parents)


def _confine(base: Path, target: str | Path) -> Path:
    """Resolve `target` under `base` (already resolved) and refuse anything outside it.

    Resolving follows symlinks, so `..`, an absolute path elsewhere, and a symlink
    that points out of `base` are all caught by the same comparison.
    """
    rel = Path(target)
    resolved = rel.resolve() if rel.is_absolute() else (base / rel).resolve()
    if not _is_inside(base, resolved):
        raise UnsafePathError(
            f"Refusing to write {str(target)!r}: it is not inside {base}."
        )
    return resolved


def write_project_files(base_dir: str | Path, files: dict[str, str]) -> list[str]:
    """Write a dict of {relative_path: content} to base_dir.

    Creates parent directories as needed. Every path is checked before anything is
    written, so a refused path leaves nothing behind.

    Returns:
        List of absolute paths written.

    Raises:
        UnsafePathError: a path would land outside base_dir.
    """
    base = Path(base_dir).resolve()
    targets = [(_confine(base, rel_path), content) for rel_path, content in files.items()]
    for full_path, _ in targets:
        _refuse_shared_file(full_path)
    written = []
    for full_path, content in targets:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        _write_replacing(full_path, content)
        written.append(str(full_path))
    return written


def _refuse_shared_file(path: Path) -> None:
    """Refuse to overwrite a regular file that has another name somewhere (a hard link).

    Such a file passes every path check, because its path IS inside the project, yet
    its content is shared with a file that may be anywhere on the same disk.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return                      # nothing there yet
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise UnsafePathError(
            f"Refusing to overwrite {str(path)!r}: it is hard-linked to another file "
            f"({info.st_nlink} names for one file), so writing it would change that file too."
        )
    if not stat.S_ISREG(info.st_mode):
        raise UnsafePathError(f"Refusing to overwrite {str(path)!r}: it is not a regular file.")


def _write_replacing(path: Path, content: str) -> None:
    """Write `content` as a NEW file next to `path`, then rename it into place.

    The new file is created exclusively (never through a symlink), and the rename swaps
    the directory entry instead of truncating whatever was there, so a file shared with
    another location is never written through.

    Known limit, not closed here: between the path check and this write, someone who can
    already write to the project folder could replace one of its sub-directories with a
    symlink. That needs a local attacker with write access at that instant.
    """
    try:
        mode = stat.S_IMODE(os.lstat(path).st_mode)
    except OSError:
        current = os.umask(0)
        os.umask(current)
        mode = 0o666 & ~current
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".mcp-creator-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def inject_after_sentinel(
    file_path: str | Path,
    sentinel: str,
    content: str,
    base_dir: str | Path | None = None,
) -> bool:
    """Insert content after a sentinel comment line in a file.

    With base_dir, the file must resolve to a path inside it.

    Returns True if injection succeeded, False if sentinel not found.

    Raises:
        UnsafePathError: base_dir was given and the file is outside it.
    """
    path = Path(file_path)
    if base_dir is not None:
        path = _confine(Path(base_dir).resolve(), path)
        _refuse_shared_file(path)
    text = path.read_text(encoding="utf-8")
    if sentinel not in text:
        return False
    text = text.replace(sentinel, sentinel + "\n" + content, 1)
    _write_replacing(path, text)
    return True
