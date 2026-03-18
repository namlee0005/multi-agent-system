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
        
        # Gemini logic: stateless by default as per spec (Task 6.3)

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
            
            # Parse content and session_id from JSON output
            stdout_raw = res.stdout.strip()
            content = stdout_raw
            extracted_id = session_id

            try:
                data = json.loads(stdout_raw)
                # Handle nested result field in Claude Code JSON output
                content = data.get("result", data.get("text", data.get("content", stdout_raw)))
                extracted_id = data.get("session_id", session_id)
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
                duration_s=duration
            )

        except Exception as e:
            return CLICallResult(
                content=f"Error: {str(e)}",
                returncode=1,
                duration_s=time.monotonic() - start_time
            )
