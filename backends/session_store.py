import json
import os
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional

@dataclass
class CLISessionConfig:
    backend: str
    command: str
    agent_name: str
    project_path: str
    model: str

@dataclass
class CLICallResult:
    content: str
    session_id: Optional[str] = None
    returncode: int = 0
    is_resumed: bool = False
    duration_s: float = 0.0

class SessionStore:
    """Manages persistence of CLI session IDs across agent runs."""
    
    def __init__(self, storage_path: str = ".mas/sessions.json"):
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._sessions: dict[str, str] = {}
        self._load()

    def _get_key(self, backend: str, agent_name: str, project_path: str) -> str:
        # Normalize project path to absolute to avoid relative path mismatches
        abs_path = os.path.abspath(project_path)
        return f"{backend}:{agent_name}:{abs_path}"

    def _load(self):
        """Load sessions from disk."""
        with self._lock:
            if os.path.exists(self.storage_path):
                try:
                    with open(self.storage_path, "r") as f:
                        self._sessions = json.load(f)
                except (json.JSONDecodeError, IOError):
                    self._sessions = {}
            else:
                self._sessions = {}

    def _save(self):
        """Save sessions to disk."""
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, "w") as f:
            json.dump(self._sessions, f, indent=2)

    def get(self, backend: str, agent_name: str, project_path: str) -> Optional[str]:
        """Get a session ID for the given agent and project."""
        key = self._get_key(backend, agent_name, project_path)
        return self._sessions.get(key)

    def set(self, backend: str, agent_name: str, project_path: str, session_id: str):
        """Set or update a session ID."""
        key = self._get_key(backend, agent_name, project_path)
        with self._lock:
            self._sessions[key] = session_id
            self._save()

    def invalidate(self, project_path: str):
        """Clear all sessions for a specific project."""
        abs_path = os.path.abspath(project_path)
        with self._lock:
            # Filter out any keys belonging to this project path
            self._sessions = {
                k: v for k, v in self._sessions.items() 
                if not k.endswith(f":{abs_path}")
            }
            self._save()

    def clear_all(self):
        """Clear all stored sessions."""
        with self._lock:
            self._sessions = {}
            self._save()
