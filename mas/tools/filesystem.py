"""
mas/tools/filesystem.py — Safe file write and in-place string replacement tools.

Security contract:
- All paths are resolved with os.path.realpath() and asserted to start with
  the configured project_path prefix. Traversal attempts raise PermissionError.
- Writes are atomic: content is written to a .tmp sibling and renamed on success.
- str_replace fails loudly if old_str appears 0 or >1 times (ambiguous target).
"""
from __future__ import annotations

import os
import tempfile
from typing import Any


# ---------------------------------------------------------------------------
# Path guard
# ---------------------------------------------------------------------------

def _safe_resolve(project_path: str, rel_path: str) -> str:
    """
    Resolve rel_path inside project_path.
    Raises PermissionError on path traversal.
    """
    abs_project = os.path.realpath(project_path)
    candidate = os.path.realpath(os.path.join(abs_project, rel_path))
    if not candidate.startswith(abs_project + os.sep) and candidate != abs_project:
        raise PermissionError(
            f"Path traversal blocked: '{rel_path}' resolves outside project root."
        )
    return candidate


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------

def write_file(
    path: str,
    content: str,
    project_path: str,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """
    Write content to a project-relative path.

    - Parent directories are created automatically (os.makedirs).
    - Write is atomic: content goes to a .tmp sibling, then os.replace() renames it.
    - Refuses to write outside project_path (path traversal guard).

    Args:
        path: Project-relative file path (e.g. "src/main.py").
        content: UTF-8 string content to write.
        project_path: Absolute path to the project root (injected by execute_tool).
        encoding: File encoding (default "utf-8").

    Returns:
        dict with keys: path (resolved), bytes_written (int), error (str|None)
    """
    try:
        full_path = _safe_resolve(project_path, path)
    except PermissionError as exc:
        return {"path": path, "bytes_written": 0, "error": str(exc)}

    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Atomic write via temp file in same directory (same filesystem → rename is atomic)
        dir_name = os.path.dirname(full_path)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=dir_name,
            delete=False,
            suffix=".tmp",
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        os.replace(tmp_path, full_path)
        return {
            "path": full_path,
            "bytes_written": len(content.encode(encoding)),
            "error": None,
        }

    except OSError as exc:
        # Clean up orphaned tmp if rename failed
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return {"path": path, "bytes_written": 0, "error": f"OSError: {exc}"}


# ---------------------------------------------------------------------------
# str_replace
# ---------------------------------------------------------------------------

def str_replace(
    path: str,
    old_str: str,
    new_str: str,
    project_path: str,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """
    Replace exactly one occurrence of old_str with new_str in a file.

    Fails with a descriptive error if:
    - old_str appears 0 times (not found)
    - old_str appears >1 times (ambiguous — use a more unique context window)

    The replacement is written atomically (same .tmp → rename idiom as write_file).

    Args:
        path: Project-relative file path.
        old_str: Exact string to find. Must appear exactly once.
        new_str: Replacement string.
        project_path: Absolute project root path (injected by execute_tool).
        encoding: File encoding (default "utf-8").

    Returns:
        dict with keys: path (resolved), replaced (bool), occurrences (int), error (str|None)
    """
    try:
        full_path = _safe_resolve(project_path, path)
    except PermissionError as exc:
        return {"path": path, "replaced": False, "occurrences": 0, "error": str(exc)}

    try:
        with open(full_path, encoding=encoding) as f:
            original = f.read()
    except OSError as exc:
        return {"path": path, "replaced": False, "occurrences": 0, "error": f"Read error: {exc}"}

    occurrences = original.count(old_str)
    if occurrences == 0:
        return {
            "path": path,
            "replaced": False,
            "occurrences": 0,
            "error": "old_str not found in file.",
        }
    if occurrences > 1:
        return {
            "path": path,
            "replaced": False,
            "occurrences": occurrences,
            "error": (
                f"old_str appears {occurrences} times — ambiguous replacement. "
                "Expand context window to make old_str unique."
            ),
        }

    updated = original.replace(old_str, new_str, 1)

    dir_name = os.path.dirname(full_path)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=dir_name,
            delete=False,
            suffix=".tmp",
        ) as tmp:
            tmp.write(updated)
            tmp_path = tmp.name

        os.replace(tmp_path, full_path)
        return {"path": full_path, "replaced": True, "occurrences": 1, "error": None}

    except OSError as exc:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        return {"path": path, "replaced": False, "occurrences": 1, "error": f"Write error: {exc}"}
