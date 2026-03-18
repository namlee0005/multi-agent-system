import json
import os
import subprocess
import time
import uuid
from typing import Optional, List
try:
    from .session_store import CLICallResult, SessionStore
except ImportError:
    # Fallback for direct testing
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from session_store import CLICallResult, SessionStore

class CLISession:
    """Handles low-level CLI subprocess calls with session persistence logic."""
    
    def __init__(
        self, 
        backend: str, 
        agent_name: str, 
        project_path: str, 
        command: str, 
        model: str, 
        session_store: SessionStore,
        timeout: int = 600
    ):
        self.backend = backend
        self.agent_name = agent_name
        self.project_path = project_path
        self.command = command
        self.model = model
        self.session_store = session_store
        self.timeout = timeout

    def _get_env(self) -> dict:
        """Strip CLAUDECODE to allow nested sessions."""
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        return env

    def call(self, prompt: str, extra_args: Optional[List[str]] = None) -> CLICallResult:
        """Execute the CLI call, handling session resume for Claude."""
        start_time = time.monotonic()
        is_resumed = False
        session_id = self.session_store.get(self.backend, self.agent_name, self.project_path)

        # Gemini is stateless by design — '--resume latest' is unsafe under
        # ThreadPoolExecutor (concurrent threads race to resume "latest" and
        # cross-contaminate sessions). Any session_id stored for a Gemini backend
        # is a bug; fail loudly rather than silently resuming.
        if self.backend == "gemini":
            assert session_id is None, (
                f"Gemini backend must never carry a session_id, but found "
                f"session_id={session_id!r} for agent '{self.agent_name}'. "
                "Gemini runs stateless by design (spec §5.3). "
                "Call SessionStore.invalidate() before retrying."
            )
        
        # Prepare base command
        # Note: --output-format json ensures we get parseable session metadata
        cmd = [self.command, "--print", "--output-format", "json"]
        if self.model:
            cmd.extend(["--model", self.model])
            
        if extra_args:
            cmd.extend(extra_args)

        # Claude session logic: pre-generate UUID if missing
        if self.backend == "claude":
            if session_id:
                cmd.extend(["--resume", session_id])
                is_resumed = True
            else:
                # First call: generate and use a new UUID
                session_id = str(uuid.uuid4())
                cmd.extend(["--session-id", session_id])
                # We'll persist this ID after a successful first call

        # Gemini logic: stateless by default as per spec (§5.3)
        # No --resume flag is ever added. The assert above ensures session_id
        # is None, so is_resumed remains False for the entire call.
        assert not (self.backend == "gemini" and is_resumed), (
            "Gemini backend reached is_resumed=True — this is a logic error. "
            "Gemini must never attempt session resumption."
        )

        try:
            # We need to capture the raw stdout for JSON parsing
            res = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=self._get_env()
            )
            
            duration = time.monotonic() - start_time
            
            if res.returncode != 0:
                # If resume fails, retry once without resume
                if is_resumed:
                    print(f"  ⚠ Session {session_id} failed for {self.agent_name}. Retrying stateless...")
                    self.session_store.invalidate(self.project_path)
                    return self.call(prompt, extra_args)
                
                return CLICallResult(
                    content=res.stderr.strip() or res.stdout.strip(), 
                    returncode=res.returncode,
                    duration_s=duration
                )
            
            # Parse content, session_id, and token usage from JSON output
            stdout_raw = res.stdout.strip()
            content = stdout_raw
            extracted_id = session_id
            input_tokens: Optional[int] = None
            output_tokens: Optional[int] = None

            try:
                data = json.loads(stdout_raw)
                # Handle nested result field in Claude Code JSON output
                content = data.get("result", data.get("text", data.get("content", stdout_raw)))
                extracted_id = data.get("session_id", session_id)
                # Extract token usage from the 'usage' block (Claude CLI JSON output).
                # Resumed sessions report context via cache_read_input_tokens, not
                # input_tokens — sum all three fields to get true total context size.
                usage = data.get("usage", {})
                if usage:
                    raw_input = usage.get("input_tokens") or 0
                    cache_read = usage.get("cache_read_input_tokens") or 0
                    cache_creation = usage.get("cache_creation_input_tokens") or 0
                    input_tokens = raw_input + cache_read + cache_creation
                    output_tokens = usage.get("output_tokens")
            except json.JSONDecodeError:
                pass

            # Persist session ID if this was a first successful call or it changed
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

        except Exception as e:
            return CLICallResult(
                content=f"Error: {str(e)}",
                returncode=1,
                duration_s=time.monotonic() - start_time
            )