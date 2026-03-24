"""
Built-in tool implementations (Phase 9.5, 9.6).

Security contract:
- read_file and list_dir: realpath() + prefix assertion against project_path.
- run_python: subprocess with timeout; no shell=True; stdout/stderr captured.
- web_search: stub returning an empty list (real impl requires API key config).
"""

from __future__ import annotations

import os
import subprocess
from typing import Any


# ─── Path helpers ─────────────────────────────────────────────────────────────

def _safe_resolve(project_path: str, rel_path: str) -> str:
    """
    Resolve rel_path inside project_path.
    Raises PermissionError on traversal attempts.
    """
    abs_project = os.path.realpath(project_path)
    candidate = os.path.realpath(os.path.join(abs_project, rel_path))
    if not candidate.startswith(abs_project + os.sep) and candidate != abs_project:
        raise PermissionError(
            f"Path traversal blocked: '{rel_path}' resolves outside project root."
        )
    return candidate


# ─── Tool implementations ─────────────────────────────────────────────────────

def read_file(path: str, project_path: str, max_bytes: int = 32768) -> dict[str, Any]:
    """Read a file from the project directory."""
    try:
        full = _safe_resolve(project_path, path)
        if not os.path.isfile(full):
            return {"error": f"Not a file: {path}"}
        with open(full, "rb") as f:
            raw = f.read(max_bytes)
        truncated = os.path.getsize(full) > max_bytes
        return {
            "content": raw.decode("utf-8", errors="replace"),
            "truncated": truncated,
            "size_bytes": os.path.getsize(full),
        }
    except PermissionError as e:
        return {"error": str(e)}
    except OSError as e:
        return {"error": f"OSError: {e}"}


def list_dir(path: str, project_path: str) -> dict[str, Any]:
    """List directory contents (non-recursive)."""
    try:
        full = _safe_resolve(project_path, path)
        if not os.path.isdir(full):
            return {"error": f"Not a directory: {path}"}
        entries = []
        for name in sorted(os.listdir(full)):
            entry_path = os.path.join(full, name)
            entries.append({
                "name": name,
                "type": "dir" if os.path.isdir(entry_path) else "file",
                "size_bytes": os.path.getsize(entry_path) if os.path.isfile(entry_path) else None,
            })
        return {"path": path, "entries": entries}
    except PermissionError as e:
        return {"error": str(e)}
    except OSError as e:
        return {"error": f"OSError: {e}"}


def run_python(code: str, timeout_s: int = 60) -> dict[str, Any]:
    """Execute a Python snippet in a subprocess. No shell=True, no network access bypass."""
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[:8192],
            "stderr": result.stderr[:2048],
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Timed out after {timeout_s}s", "returncode": -1}
    except OSError as e:
        return {"error": f"OSError: {e}", "returncode": -1}


def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Delegate to mas.tools.web (Tavily primary / DuckDuckGo fallback)."""
    try:
        from mas.tools.web import web_search as _ws
        return _ws(query=query, max_results=max_results)
    except ImportError as exc:
        return {"error": f"mas.tools.web unavailable: {exc}", "results": [], "query": query}


def web_fetch(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """Delegate to mas.tools.web.web_fetch."""
    try:
        from mas.tools.web import web_fetch as _wf
        return _wf(url=url, max_chars=max_chars)
    except ImportError as exc:
        return {"error": f"mas.tools.web unavailable: {exc}", "url": url, "content": None}


def run_bash(command: str, cwd: str | None = None, project_path: str | None = None) -> dict[str, Any]:
    """Delegate to mas.tools.sandbox.run_bash with project_path as default cwd."""
    try:
        from mas.tools.sandbox import run_bash as _rb
        effective_cwd = cwd or project_path
        return _rb(command=command, cwd=effective_cwd)
    except ImportError as exc:
        return {"error": f"mas.tools.sandbox unavailable: {exc}", "command": command}


def write_file(path: str, content: str, project_path: str) -> dict[str, Any]:
    """Delegate to mas.tools.filesystem.write_file."""
    try:
        from mas.tools.filesystem import write_file as _wf
        return _wf(path=path, content=content, project_path=project_path)
    except ImportError as exc:
        return {"path": path, "bytes_written": 0, "error": f"mas.tools.filesystem unavailable: {exc}"}


def str_replace(path: str, old_str: str, new_str: str, project_path: str) -> dict[str, Any]:
    """Delegate to mas.tools.filesystem.str_replace."""
    try:
        from mas.tools.filesystem import str_replace as _sr
        return _sr(path=path, old_str=old_str, new_str=new_str, project_path=project_path)
    except ImportError as exc:
        return {"path": path, "replaced": False, "occurrences": 0,
                "error": f"mas.tools.filesystem unavailable: {exc}"}


def comfyui_submit(workflow: dict, client_id: str | None = None) -> dict[str, Any]:
    """Delegate to mas.tools.comfyui.comfyui_submit."""
    try:
        from mas.tools.comfyui import comfyui_submit as _cs
        return _cs(workflow=workflow, client_id=client_id)
    except ImportError as exc:
        return {"prompt_id": None, "queue_number": None, "node_errors": {},
                "error": f"mas.tools.comfyui unavailable: {exc}"}


def comfyui_poll(prompt_id: str) -> dict[str, Any]:
    """Delegate to mas.tools.comfyui.comfyui_poll."""
    try:
        from mas.tools.comfyui import comfyui_poll as _cp
        return _cp(prompt_id=prompt_id)
    except ImportError as exc:
        return {"prompt_id": prompt_id, "status": "error", "outputs": [],
                "error": f"mas.tools.comfyui unavailable: {exc}"}


# ─── Dispatch table ───────────────────────────────────────────────────────────

# Tools that need project_path injected by execute_tool
_PROJECT_PATH_TOOLS = frozenset({"read_file", "list_dir", "run_bash", "write_file", "str_replace"})

TOOL_DISPATCH: dict[str, Any] = {
    "read_file": read_file,
    "list_dir": list_dir,
    "run_python": run_python,
    "web_search": web_search,
    "web_fetch": web_fetch,
    "run_bash": run_bash,
    "write_file": write_file,
    "str_replace": str_replace,
    "comfyui_submit": comfyui_submit,
    "comfyui_poll": comfyui_poll,
}


def execute_tool(tool_name: str, args: dict[str, Any], project_path: str) -> dict[str, Any]:
    """Dispatch a tool call by name. Injects project_path for file/sandbox tools."""
    fn = TOOL_DISPATCH.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: '{tool_name}'"}
    if tool_name in _PROJECT_PATH_TOOLS:
        return fn(project_path=project_path, **args)
    return fn(**args)