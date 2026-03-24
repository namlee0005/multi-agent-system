"""
mas/tools/sandbox.py — Sandboxed shell execution for MAS functional skills.

run_bash: Execute a restricted shell command from a strict allowlist.

Only the following commands are permitted as the first token:
    grep, find, ls, cat, wc, head, tail, git
"""
from __future__ import annotations

import shlex
import subprocess
from typing import Any

# Commands permitted as the leading executable
ALLOWED_COMMANDS: frozenset[str] = frozenset({
    "grep",
    "find",
    "ls",
    "cat",
    "wc",
    "head",
    "tail",
    "git",
})

# Hard cap on output to avoid context flooding
MAX_OUTPUT_CHARS = 4096

# Execution timeout (seconds)
DEFAULT_TIMEOUT = 30


def run_bash(command: str, cwd: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """
    Execute a shell command subject to the allowlist and return stdout/stderr.

    The command is parsed with shlex to extract the leading executable.
    If the executable is not in ALLOWED_COMMANDS, execution is refused.
    The command is always run without shell=True to prevent injection.

    Args:
        command: Shell command string (e.g. "grep -r TODO src/").
        cwd: Working directory for the subprocess (defaults to the process cwd).
        timeout: Seconds before the subprocess is killed (default 30).

    Returns:
        dict with keys:
            command (str): The command that was run.
            stdout (str): Captured standard output (truncated if > MAX_OUTPUT_CHARS).
            stderr (str): Captured standard error.
            returncode (int): Process exit code.
            truncated (bool): True if stdout was truncated.
            error (str | None): Error message if execution was refused or failed.
    """
    # Parse into tokens; reject empty or malformed commands
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return _error_result(command, f"Command parse error: {exc}")

    if not tokens:
        return _error_result(command, "Empty command.")

    executable = tokens[0]

    # Strip path components — only the base name is checked
    import os
    base_executable = os.path.basename(executable)

    if base_executable not in ALLOWED_COMMANDS:
        return _error_result(
            command,
            f"Command '{base_executable}' is not in the allowed list: "
            f"{sorted(ALLOWED_COMMANDS)}",
        )

    try:
        proc = subprocess.run(
            tokens,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return _error_result(command, f"Command timed out after {timeout}s.")
    except FileNotFoundError:
        return _error_result(command, f"Executable '{executable}' not found on PATH.")
    except Exception as exc:
        return _error_result(command, str(exc))

    stdout = proc.stdout
    truncated = len(stdout) > MAX_OUTPUT_CHARS
    if truncated:
        stdout = stdout[:MAX_OUTPUT_CHARS]

    return {
        "command": command,
        "stdout": stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
        "truncated": truncated,
        "error": None,
    }


def _error_result(command: str, error: str) -> dict[str, Any]:
    return {
        "command": command,
        "stdout": "",
        "stderr": "",
        "returncode": 1,
        "truncated": False,
        "error": error,
    }
