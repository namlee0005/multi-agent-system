import json
import os
import subprocess
import time
import uuid
from typing import Optional, List, TYPE_CHECKING

try:
    from .session_store import CLICallResult, SessionStore
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from session_store import CLICallResult, SessionStore

# Lazy import to avoid circular dependency — interceptor only loaded when needed
if TYPE_CHECKING:
    from skills.functional.interceptor import parse_tool_call, build_resume_prompt
    from skills.functional.tools import execute_tool
    from skills.functional.models import ToolResult


class CLISession:
    """Handles low-level CLI subprocess calls with session persistence logic."""

    # Maximum tool-call / resume cycles per agent call to prevent infinite loops
    MAX_TOOL_CYCLES = 5

    def __init__(
        self,
        backend: str,
        agent_name: str,
        project_path: str,
        command: str,
        model: str,
        session_store: SessionStore,
        timeout: int = 600,
        enable_tools: bool = False,
    ):
        self.backend = backend
        self.agent_name = agent_name
        self.project_path = project_path
        self.command = command
        self.model = model
        self.session_store = session_store
        self.timeout = timeout
        self.enable_tools = enable_tools

    def _get_env(self) -> dict:
        """Strip CLAUDECODE to allow nested sessions."""
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        return env

    def _run_subprocess(
        self,
        cmd: list[str],
        prompt: str,
        start_time: float,
        is_resumed: bool,
        session_id: Optional[str],
    ) -> CLICallResult:
        """Execute the subprocess and return a CLICallResult."""
        try:
            res = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=self._get_env(),
                cwd=self.project_path,
            )
        except Exception as e:
            return CLICallResult(
                content=f"Error: {str(e)}",
                returncode=1,
                duration_s=time.monotonic() - start_time,
            )

        duration = time.monotonic() - start_time

        if res.returncode != 0:
            if is_resumed:
                print(f"  ⚠ Session {session_id} failed for {self.agent_name}. Retrying stateless...")
                self.session_store.invalidate(self.project_path)
                return self.call(res.stderr.strip())  # will rebuild cmd without --resume
            return CLICallResult(
                content=res.stderr.strip() or res.stdout.strip(),
                returncode=res.returncode,
                duration_s=duration,
            )

        # Parse JSON output
        stdout_raw = res.stdout.strip()
        content = stdout_raw
        extracted_id = session_id
        input_tokens: Optional[int] = None
        output_tokens: Optional[int] = None

        try:
            data = json.loads(stdout_raw)
            content = data.get("result", data.get("text", data.get("content", stdout_raw)))
            extracted_id = data.get("session_id", session_id)
            usage = data.get("usage", {})
            if usage:
                raw_input = usage.get("input_tokens") or 0
                cache_read = usage.get("cache_read_input_tokens") or 0
                cache_creation = usage.get("cache_creation_input_tokens") or 0
                input_tokens = raw_input + cache_read + cache_creation
                output_tokens = usage.get("output_tokens")
        except json.JSONDecodeError:
            pass

        if self.backend == "claude" and extracted_id:
            self.session_store.set(self.backend, self.agent_name, self.project_path, extracted_id)

        return CLICallResult(
            content=content,
            session_id=extracted_id,
            returncode=0,
            is_resumed=is_resumed,
            duration_s=duration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _build_cmd(
        self,
        session_id: Optional[str],
        extra_args: Optional[List[str]],
    ) -> tuple[list[str], bool, Optional[str]]:
        """Build CLI command, returning (cmd, is_resumed, session_id)."""
        cmd = [self.command, "--print", "--output-format", "json"]
        if self.model:
            cmd.extend(["--model", self.model])
        if extra_args:
            cmd.extend(extra_args)

        is_resumed = False
        if self.backend == "claude":
            if session_id:
                cmd.extend(["--resume", session_id])
                is_resumed = True
            else:
                session_id = str(uuid.uuid4())
                cmd.extend(["--session-id", session_id])

        return cmd, is_resumed, session_id

    def call(self, prompt: str, extra_args: Optional[List[str]] = None) -> CLICallResult:
        """
        Execute the CLI call with optional Functional Skill interception loop.

        If enable_tools=True, scans each response for [TOOL_CALL: ...] markers,
        executes the tool locally, and resumes via --resume up to MAX_TOOL_CYCLES.
        """
        start_time = time.monotonic()
        session_id = self.session_store.get(self.backend, self.agent_name, self.project_path)

        # Gemini stateless enforcement (spec §5.3)
        if self.backend == "gemini":
            assert session_id is None, (
                f"Gemini backend must never carry a session_id, but found "
                f"session_id={session_id!r} for agent '{self.agent_name}'. "
                "Gemini runs stateless by design (spec §5.3). "
                "Call SessionStore.invalidate() before retrying."
            )

        cmd, is_resumed, session_id = self._build_cmd(session_id, extra_args)

        assert not (self.backend == "gemini" and is_resumed), (
            "Gemini backend reached is_resumed=True — this is a logic error."
        )

        result = self._run_subprocess(cmd, prompt, start_time, is_resumed, session_id)

        if result.returncode != 0 or not self.enable_tools:
            return result

        # ── Phase 9.7: Interception & Resume loop ────────────────────────────
        from skills.functional.interceptor import (  # noqa: PLC0415
            parse_tool_call, has_tool_call, build_resume_prompt,
        )
        from skills.functional.tools import execute_tool  # noqa: PLC0415
        from skills.functional.models import ToolResult   # noqa: PLC0415

        current_prompt = prompt
        cycles = 0

        while cycles < self.MAX_TOOL_CYCLES and has_tool_call(result.content):
            tool_call = parse_tool_call(result.content)
            if tool_call is None:
                break  # malformed marker — pass raw output to caller

            tool_output = execute_tool(
                tool_call.tool_name,
                tool_call.args,
                self.project_path,
            )
            tool_result = ToolResult(
                tool_name=tool_call.tool_name,
                success="error" not in tool_output,
                data=tool_output if "error" not in tool_output else None,
                error=tool_output.get("error"),
            )
            print(
                f"  ⚙ Tool '{tool_call.tool_name}' executed "
                f"({'ok' if tool_result.success else 'error'})"
            )

            resume_prompt = build_resume_prompt(current_prompt, result.content, tool_result)

            # Always resume with the existing session after a tool call
            resume_session_id = self.session_store.get(
                self.backend, self.agent_name, self.project_path
            ) or session_id
            resume_cmd, _, _ = self._build_cmd(resume_session_id, extra_args)

            result = self._run_subprocess(
                resume_cmd, resume_prompt, time.monotonic(), True, resume_session_id
            )
            current_prompt = resume_prompt
            cycles += 1

            if result.returncode != 0:
                break

        return result